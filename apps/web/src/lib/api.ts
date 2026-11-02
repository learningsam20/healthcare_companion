const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
export const API_BASE = RAW_BASE.replace(/\/+$/, "");

let accessToken: string | null = null;
let consentId: string | null = null;

export function setApiAccessToken(token: string | null): void {
  accessToken = token;
}

export function setApiConsentId(value: string | null): void {
  consentId = value;
}

export type QueryValue = string | number | boolean | null | undefined;

export function qs(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface ProblemBody {
  type?: string;
  title?: string;
  status?: number;
  code?: string;
  detail?: string;
  instance?: string;
  trace_id?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly traceId: string | null;

  constructor(status: number, body: ProblemBody) {
    const detail = body.detail || body.title || "The request could not be completed.";
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || "request_failed";
    this.title = body.title || "Request failed";
    this.detail = detail;
    this.traceId = body.trace_id ?? null;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return error.detail;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function problemFrom(response: Response): Promise<ApiError> {
  let body: ProblemBody = {};
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === "object") body = parsed as ProblemBody;
  } catch {
    // Non-JSON upstream errors fall back to the HTTP status.
  }
  const trace = response.headers.get("x-trace-id");
  if (trace && !body.trace_id) body.trace_id = trace;
  return new ApiError(response.status, body);
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (consentId) headers["X-Consent-Id"] = consentId;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, {
      code: "network_unavailable",
      title: "Network unavailable",
      detail: "The API could not be reached. Check your connection and try again.",
    });
  }
  if (!response.ok) throw await problemFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Consume an SSE response body; calls onEvent for each named event. */
export async function apiSse(
  path: string,
  options: {
    method?: "GET" | "POST";
    body?: unknown;
    signal?: AbortSignal;
    onEvent: (event: string, data: unknown) => void;
  },
): Promise<void> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (consentId) headers["X-Consent-Id"] = consentId;
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, {
      code: "network_unavailable",
      title: "Network unavailable",
      detail: "The API could not be reached. Check your connection and try again.",
    });
  }
  if (!response.ok) throw await problemFrom(response);
  if (!response.body) {
    throw new ApiError(502, {
      code: "stream_unavailable",
      title: "Stream unavailable",
      detail: "The server did not return a stream body.",
    });
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];
  const flush = () => {
    if (!dataLines.length) {
      eventName = "message";
      return;
    }
    const raw = dataLines.join("\n");
    dataLines = [];
    const name = eventName;
    eventName = "message";
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw) as unknown;
    } catch {
      // keep raw string
    }
    options.onEvent(name, parsed);
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";
    for (const line of parts) {
      if (line === "") {
        flush();
        continue;
      }
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
  }
  flush();
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (consentId) headers["X-Consent-Id"] = consentId;
  const response = await fetch(`${API_BASE}${path}`, { headers });
  if (!response.ok) throw await problemFrom(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await response.blob(),
    filename: match?.[1] ?? "download",
  };
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
