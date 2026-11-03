import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  MessageCircle,
  Paperclip,
  Pencil,
  Plus,
  RotateCcw,
  Send,
  ShieldAlert,
  Square,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "../components/Badge";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { IconButton } from "../components/IconButton";
import { Modal } from "../components/Modal";
import { SourceList } from "../components/SourceList";
import {
  Callout,
  EmptyState,
  Field,
  FormError,
  PageHeader,
  Spinner,
} from "../components/primitives";
import { ApiError, api, apiSse, errorMessage, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatDateTime, truncate } from "../lib/format";
import { useGridState } from "../lib/grid";
import { useI18n } from "../lib/i18n";
import type {
  ChatInterrupt,
  ChatMessage,
  ChatSession,
  GridResponse,
  HeldAppointment,
  Meta,
  SendResult,
} from "../lib/types";
import type { TranslationKey } from "../i18n/locales";

const SORTS: { key: string; value: "updated_at" | "created_at" | "title" }[] = [
  { key: "chat.sortUpdated", value: "updated_at" },
  { key: "chat.sortCreated", value: "created_at" },
  { key: "chat.sortTitle", value: "title" },
];

const LANGUAGES = [
  { value: "en-IN", label: "English" },
  { value: "hi-IN", label: "हिन्दी" },
  { value: "mr-IN", label: "मराठी" },
] as const;

const RECORD_KINDS = [
  "lab_report",
  "discharge_summary",
  "prescription",
  "imaging",
  "other",
] as const;

function useCountdown(expiresAt: string | null | undefined): number {
  const [remaining, setRemaining] = useState(() => {
    if (!expiresAt) return 0;
    return Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
  });
  useEffect(() => {
    if (!expiresAt) {
      setRemaining(0);
      return;
    }
    const tick = () => {
      setRemaining(Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000)));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [expiresAt]);
  return remaining;
}

function formatCountdown(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ChatPage() {
  const { t, locale } = useI18n();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const grid = useGridState("updated_at", "desc");
  const [selected, setSelected] = useState<ChatSession | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [composer, setComposer] = useState("");
  const [messageLanguage, setMessageLanguage] = useState<string>(locale);
  const [sendError, setSendError] = useState<string | null>(null);
  const [redFlag, setRedFlag] = useState<SendResult["red_flag"]>(null);
  const [interrupt, setInterrupt] = useState<SendResult["interrupt"]>(null);
  const [heldAppointment, setHeldAppointment] = useState<HeldAppointment | null>(null);
  const [holdError, setHoldError] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameTitle, setRenameTitle] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ChatSession | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [feedbackDone, setFeedbackDone] = useState<Record<string, "up" | "down">>({});
  const [feedbackNote, setFeedbackNote] = useState<string | null>(null);
  const [attachOpen, setAttachOpen] = useState(false);
  const [attachFile, setAttachFile] = useState<File | null>(null);
  const [attachTitle, setAttachTitle] = useState("");
  const [attachKind, setAttachKind] = useState<(typeof RECORD_KINDS)[number]>("lab_report");
  const [attachError, setAttachError] = useState<string | null>(null);
  const [streamDraft, setStreamDraft] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (debouncedSearch !== grid.query) grid.setQuery(debouncedSearch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  useEffect(() => {
    setMessageLanguage(locale);
  }, [locale]);

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 5 * 60_000,
  });

  const sessionsQuery = useQuery({
    queryKey: ["chat-sessions", grid.params],
    queryFn: () =>
      api<GridResponse<ChatSession>>(`/api/v1/chat/sessions${qs({ ...grid.params })}`),
    enabled: metaQuery.data?.capabilities.chat !== false,
  });

  useEffect(() => {
    if (!selected && sessionsQuery.data?.items.length) {
      setSelected(sessionsQuery.data.items[0]);
    }
  }, [selected, sessionsQuery.data]);

  const messagesQuery = useQuery({
    queryKey: ["chat-messages", selected?.id],
    queryFn: () => api<ChatMessage[]>(`/api/v1/chat/sessions/${selected?.id}/messages`),
    enabled: Boolean(selected?.id),
  });

  useEffect(() => {
    const messages = messagesQuery.data;
    if (!messages?.length) return;
    const flagged = [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.safety?.red_flag);
    if (flagged?.safety) {
      setRedFlag({
        rule_ids: flagged.safety.rule_ids ?? [],
        severity: flagged.safety.severity ?? "emergency",
        guidance: flagged.safety.guidance ?? flagged.content,
      });
    }
  }, [messagesQuery.data, selected?.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messagesQuery.data, messagesQuery.isPending]);

  const createMutation = useMutation({
    mutationFn: () =>
      api<ChatSession>("/api/v1/chat/sessions", {
        method: "POST",
        body: { title: newTitle.trim() || undefined, locale },
      }),
    onSuccess: (session) => {
      setSelected(session);
      setNewOpen(false);
      setNewTitle("");
      setCreateError(null);
      setRedFlag(null);
      setSendError(null);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: (error) => setCreateError(errorMessage(error)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/v1/chat/sessions/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      if (selected?.id === id) setSelected(null);
      setDeleteTarget(null);
      setLastRunId(null);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  const renameMutation = useMutation({
    mutationFn: (title: string) =>
      api<ChatSession>(`/api/v1/chat/sessions/${selected?.id}`, {
        method: "PATCH",
        body: { title },
      }),
    onSuccess: (session) => {
      setSelected(session);
      setRenameOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const sendMutation = useMutation({
    mutationFn: async (content: string): Promise<SendResult> => {
      if (!selected?.id) throw new Error("No session");
      const sessionId = selected.id;
      let userMessage: ChatMessage | undefined;
      let assistantMessage: ChatMessage | undefined;
      let red: SendResult["red_flag"] = null;
      let nextInterrupt: ChatInterrupt | null = null;
      let runId: string | null = null;
      let errorCode: string | null = null;
      let errorDetail: string | null = null;
      setStreamDraft("");
      await apiSse(`/api/v1/chat/sessions/${sessionId}/messages/stream`, {
        method: "POST",
        body: { content, language: messageLanguage },
        onEvent: (event, data) => {
          const payload = (data ?? {}) as Record<string, unknown>;
          if (typeof payload.run_id === "string") runId = payload.run_id;
          if (event === "user" && payload.message) {
            const msg = payload.message as ChatMessage;
            userMessage = msg;
            queryClient.setQueryData<ChatMessage[]>(
              ["chat-messages", sessionId],
              (current) => [...(current ?? []), msg],
            );
          } else if (event === "token" && typeof payload.delta === "string") {
            setStreamDraft((prev) => `${prev ?? ""}${payload.delta}`);
          } else if (event === "interrupt") {
            assistantMessage = payload.assistant_message as ChatMessage | undefined;
            nextInterrupt = (payload.interrupt as ChatInterrupt) ?? null;
            red = (payload.red_flag as SendResult["red_flag"]) ?? null;
            setStreamDraft(null);
          } else if (event === "final") {
            assistantMessage = payload.assistant_message as ChatMessage | undefined;
            red = (payload.red_flag as SendResult["red_flag"]) ?? null;
            nextInterrupt = (payload.interrupt as ChatInterrupt) ?? null;
            setStreamDraft(null);
          } else if (event === "error") {
            errorCode = typeof payload.code === "string" ? payload.code : "stream_failed";
            errorDetail =
              typeof payload.detail === "string" ? payload.detail : "Streaming failed.";
            setStreamDraft(null);
          }
        },
      });
      if (errorCode) {
        throw new ApiError(503, {
          code: errorCode,
          title: "Assistant unavailable",
          detail: errorDetail || "Streaming failed.",
        });
      }
      if (!userMessage || !assistantMessage) {
        throw new ApiError(502, {
          code: "stream_incomplete",
          title: "Incomplete reply",
          detail: "The assistant stream ended before a full reply.",
        });
      }
      return {
        user_message: userMessage,
        assistant_message: assistantMessage,
        red_flag: red,
        run_id: runId,
        interrupt: nextInterrupt,
      };
    },
    onMutate: () => {
      setSendError(null);
      setRedFlag(null);
      setInterrupt(null);
      setHeldAppointment(null);
      setHoldError(null);
      setFeedbackNote(null);
      setStreamDraft(null);
    },
    onSuccess: (result) => {
      setComposer("");
      setStreamDraft(null);
      setRedFlag(result.red_flag ?? null);
      setInterrupt(result.interrupt ?? null);
      if (result.run_id) setLastRunId(result.run_id);
      if (result.interrupt?.run_id) setLastRunId(result.interrupt.run_id);
      queryClient.setQueryData<ChatMessage[]>(
        ["chat-messages", selected?.id],
        (current) => {
          const withoutDupUser = (current ?? []).filter(
            (m) => m.id !== result.user_message.id && m.id !== result.assistant_message.id,
          );
          return [...withoutDupUser, result.user_message, result.assistant_message];
        },
      );
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: (error) => {
      setStreamDraft(null);
      setSendError(errorMessage(error));
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", selected?.id] });
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  const stopMutation = useMutation({
    mutationFn: (runId: string) =>
      api<{ run_id: string; status: string }>(`/api/v1/chat/runs/${runId}/stop`, {
        method: "POST",
      }),
    onSuccess: () => {
      setInterrupt(null);
      setSendError(null);
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const retryMutation = useMutation({
    mutationFn: (runId: string) =>
      api<SendResult>(`/api/v1/chat/runs/${runId}/retry`, { method: "POST" }),
    onSuccess: (result) => {
      setRedFlag(result.red_flag ?? null);
      setInterrupt(result.interrupt ?? null);
      if (result.run_id) setLastRunId(result.run_id);
      queryClient.setQueryData<ChatMessage[]>(
        ["chat-messages", selected?.id],
        (current) => [
          ...(current ?? []),
          result.user_message,
          result.assistant_message,
        ],
      );
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const feedbackMutation = useMutation({
    mutationFn: ({ messageId, rating }: { messageId: string; rating: "up" | "down" }) =>
      api(`/api/v1/chat/messages/${messageId}/feedback`, {
        method: "POST",
        body: { rating },
      }),
    onSuccess: (_data, vars) => {
      setFeedbackDone((prev) => ({ ...prev, [vars.messageId]: vars.rating }));
      setFeedbackNote(t("chat.feedbackThanks"));
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const attachMutation = useMutation({
    mutationFn: (form: FormData) =>
      api<{ id: string; title: string; kind: string; status: string }>(
        "/api/v1/records/documents",
        { method: "POST", form },
      ),
    onSuccess: (doc) => {
      setAttachOpen(false);
      setAttachFile(null);
      setAttachTitle("");
      setAttachError(null);
      setFeedbackNote(
        `Report queued for your records: ${doc.title} (${doc.kind}, status=${doc.status}). It will be available for questions after indexing.`,
      );
      void queryClient.invalidateQueries({ queryKey: ["records-documents"] });
    },
    onError: (error) => setAttachError(errorMessage(error)),
  });

  const resumeMutation = useMutation({
    mutationFn: (choiceIndex: number) => {
      if (!interrupt) throw new Error("No interrupt");
      const candidate = interrupt.payload.candidates?.[choiceIndex - 1];
      const command =
        interrupt.interrupt_type === "specialty_choice"
          ? "specialty_choice"
          : interrupt.interrupt_type === "language_choice"
            ? "language_choice"
            : interrupt.interrupt_type === "doctor_choice"
              ? "doctor_choice"
              : "slot_choice";
      // Slot picks soft-hold first so the booking card can show a hold countdown.
      const confirm = command !== "slot_choice";
      return api<SendResult>(`/api/v1/chat/runs/${interrupt.run_id}/resume`, {
        method: "POST",
        body: {
          interrupt_id: interrupt.interrupt_id,
          command,
          choice_index: choiceIndex,
          specialty_code: candidate?.specialty_code,
          locale: candidate?.locale,
          starts_at: candidate?.starts_at ?? candidate?.next_slot ?? undefined,
          confirm,
          idempotency_key: `chat-${interrupt.run_id}-${choiceIndex}`,
        },
      });
    },
    onSuccess: (result) => {
      setInterrupt(result.interrupt ?? null);
      setHeldAppointment(result.appointment ?? null);
      setHoldError(null);
      if (result.run_id) setLastRunId(result.run_id);
      queryClient.setQueryData<ChatMessage[]>(
        ["chat-messages", selected?.id],
        (current) => {
          const next = [...(current ?? [])];
          if (result.user_message) next.push(result.user_message);
          if (result.assistant_message) next.push(result.assistant_message);
          return next;
        },
      );
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", selected?.id] });
    },
    onError: (error) => setSendError(errorMessage(error)),
  });

  const confirmHoldMutation = useMutation({
    mutationFn: (appointmentId: string) =>
      api(`/api/v1/appointments/${appointmentId}/confirm`, { method: "POST" }),
    onSuccess: () => {
      setHeldAppointment(null);
      setHoldError(null);
      setFeedbackNote(t("chat.bookingConfirmed"));
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", selected?.id] });
      void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["appointments"] });
    },
    onError: (error) => setHoldError(errorMessage(error)),
  });

  const releaseHoldMutation = useMutation({
    mutationFn: (appointmentId: string) =>
      api(`/api/v1/appointments/${appointmentId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setHeldAppointment(null);
      setHoldError(null);
      void queryClient.invalidateQueries({ queryKey: ["chat-messages", selected?.id] });
    },
    onError: (error) => setHoldError(errorMessage(error)),
  });

  const choiceSecondsLeft = useCountdown(interrupt?.payload?.choice_expires_at);
  const holdSecondsLeft = useCountdown(heldAppointment?.hold_expires_at);
  const choiceExpired =
    Boolean(interrupt?.payload?.choice_expires_at) && choiceSecondsLeft === 0;
  const holdExpired =
    Boolean(heldAppointment?.hold_expires_at) && holdSecondsLeft === 0;

  useEffect(() => {
    if (!heldAppointment || holdSecondsLeft > 0) return;
    const id = heldAppointment.id;
    setHoldError(t("chat.holdExpired"));
    setHeldAppointment(null);
    void api(`/api/v1/appointments/${id}/cancel`, { method: "POST" }).catch(() => {
      /* best-effort release after client countdown */
    });
  }, [heldAppointment, holdSecondsLeft, t]);

  const submit = () => {
    const content = composer.trim();
    if (!content || !selected || sendMutation.isPending || resumeMutation.isPending) return;
    sendMutation.mutate(content);
  };

  const activeRunId = interrupt?.run_id ?? lastRunId;

  const pages = sessionsQuery.data?.meta.pages ?? 0;
  const page = sessionsQuery.data?.meta.page ?? grid.page;
  const total = sessionsQuery.data?.meta.total ?? 0;
  const chatEnabled = metaQuery.data?.capabilities.chat !== false;
  const messages = messagesQuery.data ?? [];

  if (chatEnabled === false) {
    return (
      <div className="page">
        <PageHeader title={t("chat.title")} subtitle={t("chat.subtitle")} />
        <Callout tone="warning">{t("common.featureDisabled")}</Callout>
      </div>
    );
  }

  return (
    <div className="page chat-page">
      <PageHeader
        title={t("chat.title")}
        subtitle={t("chat.subtitle")}
        actions={
          <button
            type="button"
            className="btn btn-primary"
            data-testid="chat-new-session"
            onClick={() => {
              setCreateError(null);
              setNewOpen(true);
            }}
          >
            <Plus size={16} aria-hidden="true" /> {t("chat.newSession")}
          </button>
        }
      />

      <div className="chat-layout">
        <aside className="chat-rail panel">
          <div className="rail-search">
            <div className="search-box search-box-sm">
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("chat.searchSessions")}
                aria-label={t("chat.searchSessions")}
              />
              {search ? (
                <button
                  type="button"
                  className="search-clear"
                  aria-label={t("common.clear")}
                  onClick={() => {
                    setSearch("");
                    setDebouncedSearch("");
                    grid.setQuery("");
                  }}
                >
                  <X size={13} aria-hidden="true" />
                </button>
              ) : null}
            </div>
            <div className="rail-sort">
              <select
                value={grid.sort}
                onChange={(event) => grid.setSort(event.target.value)}
                aria-label={t("common.sort")}
              >
                {SORTS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.key as TranslationKey)}
                  </option>
                ))}
              </select>
              <IconButton
                label={grid.order === "asc" ? t("common.sortDesc") : t("common.sortAsc")}
                icon={grid.order === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
                onClick={() => grid.setOrder(grid.order === "asc" ? "desc" : "asc")}
              />
            </div>
          </div>

          <div className="session-list">
            {sessionsQuery.isPending ? (
              <div className="mini-loading">{t("common.loading")}</div>
            ) : !sessionsQuery.data?.items.length ? (
              <EmptyState title={t("chat.emptyChatTitle")} hint={t("chat.emptyChatBody")} />
            ) : (
              groupSessionsByDay(
                sessionsQuery.data.items,
                metaQuery.data?.app.timezone,
              ).map((group) => (
                <div key={group.label} className="session-group">
                  <div className="session-group-label muted small">{group.label}</div>
                  {group.items.map((session) => (
                    <div
                      key={session.id}
                      className={`session-item ${selected?.id === session.id ? "is-active" : ""}`}
                    >
                      <button
                        type="button"
                        className="session-select"
                        onClick={() => {
                          setSelected(session);
                          setRedFlag(null);
                          setSendError(null);
                        }}
                      >
                        <span className="session-title">{truncate(session.title, 36)}</span>
                        <span className="session-meta">
                          {formatDateTime(
                            session.updated_at,
                            locale,
                            metaQuery.data?.app.timezone,
                          )}
                        </span>
                      </button>
                      <button
                        type="button"
                        className="session-delete"
                        aria-label={t("chat.deleteSession")}
                        onClick={() => setDeleteTarget(session)}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>

          <div className="rail-pager">
            <span className="muted small">
              {total} · {page}/{Math.max(pages, 1)}
            </span>
            <div>
              <IconButton
                label={t("common.previous")}
                icon={<ChevronLeft size={14} />}
                disabled={page <= 1}
                onClick={() => grid.setPage(page - 1)}
              />
              <IconButton
                label={t("common.next")}
                icon={<ChevronRight size={14} />}
                disabled={page >= pages || pages === 0}
                onClick={() => grid.setPage(page + 1)}
              />
            </div>
          </div>
        </aside>

        <section className="chat-main panel">
          {!selected ? (
            <div className="chat-empty">
              <EmptyState
                icon={<MessageCircle size={24} aria-hidden="true" />}
                title={t("chat.selectSession")}
                hint={t("chat.selectSessionHint")}
                action={
                  <button type="button" className="btn btn-primary" onClick={() => setNewOpen(true)}>
                    <Plus size={15} aria-hidden="true" /> {t("chat.newSession")}
                  </button>
                }
              />
            </div>
          ) : (
            <>
              <header className="chat-header">
                <div>
                  <h2>{selected.title}</h2>
                  <span className="muted small">
                    {formatDateTime(selected.created_at, locale, metaQuery.data?.app.timezone)} ·{" "}
                    {selected.locale}
                  </span>
                </div>
                <div className="chat-header-actions">
                  <Badge tone="neutral">{me.traffic_class}</Badge>
                  <IconButton
                    label={t("chat.renameSession")}
                    icon={<Pencil size={16} />}
                    onClick={() => {
                      setRenameTitle(selected.title);
                      setRenameOpen(true);
                    }}
                  />
                  {activeRunId && (sendMutation.isPending || interrupt) ? (
                    <IconButton
                      label={t("chat.stop")}
                      icon={<Square size={16} />}
                      tone="danger"
                      onClick={() => stopMutation.mutate(activeRunId)}
                    />
                  ) : null}
                  {lastRunId && !sendMutation.isPending && !interrupt ? (
                    <IconButton
                      label={t("chat.retry")}
                      icon={<RotateCcw size={16} />}
                      onClick={() => retryMutation.mutate(lastRunId)}
                    />
                  ) : null}
                  <IconButton
                    label={t("chat.deleteSession")}
                    icon={<Trash2 size={16} />}
                    tone="danger"
                    onClick={() => setDeleteTarget(selected)}
                  />
                </div>
              </header>

              <div className="message-list" aria-live="polite">
                {messagesQuery.isPending ? (
                  <div className="mini-loading">{t("common.loading")}</div>
                ) : messagesQuery.isError ? (
                  <FormError message={errorMessage(messagesQuery.error)} />
                ) : messages.length === 0 ? (
                  <EmptyState title={t("chat.emptyChatTitle")} hint={t("chat.emptyChatBody")} />
                ) : (
                  messages.map((message) => (
                    <article
                      key={message.id}
                      className={`message message-${message.role === "assistant" ? "assistant" : "user"}`}
                    >
                      <div className="message-meta">
                        <strong>
                          {message.role === "assistant" ? t("chat.assistant") : t("chat.you")}
                        </strong>
                        <span className="muted small">
                          {formatDateTime(message.created_at, locale, metaQuery.data?.app.timezone)}
                          {message.model_alias ? ` · ${message.model_alias}` : ""}
                        </span>
                      </div>
                      <div className="message-body">{message.content}</div>
                      {message.role === "assistant" ? (
                        <>
                          <details className="message-sources" data-testid="chat-message-sources">
                            <summary>
                              {t("common.sources")} ({message.sources.length})
                            </summary>
                            <SourceList sources={message.sources} compact />
                          </details>
                          <div className="tag-row" style={{ marginTop: 8 }}>
                            <IconButton
                              label={t("chat.feedbackUp")}
                              icon={<ThumbsUp size={14} />}
                              onClick={() =>
                                feedbackMutation.mutate({ messageId: message.id, rating: "up" })
                              }
                              disabled={Boolean(feedbackDone[message.id])}
                            />
                            <IconButton
                              label={t("chat.feedbackDown")}
                              icon={<ThumbsDown size={14} />}
                              onClick={() =>
                                feedbackMutation.mutate({ messageId: message.id, rating: "down" })
                              }
                              disabled={Boolean(feedbackDone[message.id])}
                            />
                          </div>
                        </>
                      ) : null}
                    </article>
                  ))
                )}
                {sendMutation.isPending ? (
                  <article className="message message-assistant" data-testid="chat-stream-draft">
                    <div className="message-meta">
                      <strong>{t("chat.assistant")}</strong>
                    </div>
                    <div className="message-body typing">
                      {streamDraft ? (
                        streamDraft
                      ) : (
                        <>
                          <Spinner label={t("common.loading")} /> {t("common.loading")}
                        </>
                      )}
                    </div>
                  </article>
                ) : null}
                <div ref={endRef} />
              </div>

              {redFlag ? (
                <div className="red-flag-banner" role="alert">
                  <ShieldAlert size={18} aria-hidden="true" />
                  <div>
                    <strong>{t("chat.redFlagTitle")}</strong>
                    <p>{redFlag.guidance}</p>
                    <span className="muted small">
                      {t("chat.redFlagBody")} · {redFlag.severity}
                    </span>
                  </div>
                  <IconButton
                    label={t("common.close")}
                    icon={<X size={15} />}
                    onClick={() => setRedFlag(null)}
                  />
                </div>
              ) : null}

              {interrupt?.payload?.candidates?.length ? (
                <div className="booking-panel" data-testid="chat-booking-interrupt">
                  <header className="booking-panel-head">
                    <div>
                      <strong>
                        {interrupt.interrupt_type === "specialty_choice"
                          ? t("chat.confirmSpecialty")
                          : interrupt.interrupt_type === "language_choice"
                            ? t("chat.confirmLanguage")
                            : interrupt.interrupt_type === "slot_choice"
                              ? t("chat.pickSlot")
                              : t("chat.chooseDoctor")}
                      </strong>
                      {interrupt.payload.specialty_label ? (
                        <p className="muted small">
                          {t("chat.suggestedSpecialty", {
                            label: interrupt.payload.specialty_label,
                            code: interrupt.payload.specialty_code
                              ? ` (${interrupt.payload.specialty_code})`
                              : "",
                          })}
                        </p>
                      ) : null}
                    </div>
                    {interrupt.payload.choice_expires_at ? (
                      <span
                        className={`hold-countdown${choiceSecondsLeft <= 30 ? " hold-countdown-urgent" : ""}`}
                        data-testid="chat-choice-countdown"
                        aria-live="polite"
                      >
                        {t("chat.choiceCountdown", { time: formatCountdown(choiceSecondsLeft) })}
                      </span>
                    ) : null}
                  </header>
                  <div
                    className={
                      interrupt.interrupt_type === "slot_choice"
                        ? "slot-chip-grid"
                        : "doctor-card-grid"
                    }
                  >
                    {interrupt.payload.candidates.map((candidate, index) => {
                      const name =
                        candidate.label ||
                        candidate.doctor_name ||
                        candidate.name ||
                        candidate.locale ||
                        t("chat.optionN", { n: index + 1 });
                      const slotLabel =
                        candidate.label ||
                        (candidate.starts_at
                          ? formatDateTime(candidate.starts_at, locale)
                          : candidate.next_slot
                            ? formatDateTime(candidate.next_slot, locale)
                            : candidate.locale
                              ? candidate.locale
                              : t("chat.openSlot"));
                      if (interrupt.interrupt_type === "slot_choice") {
                        return (
                          <button
                            key={`${name}-${candidate.starts_at || index}`}
                            type="button"
                            className="slot-chip"
                            data-testid={`chat-slot-choice-${index + 1}`}
                            disabled={resumeMutation.isPending || choiceExpired}
                            onClick={() => resumeMutation.mutate(index + 1)}
                          >
                            <span className="slot-chip-index">{index + 1}</span>
                            <span className="slot-chip-label">{slotLabel}</span>
                            {candidate.doctor_name ? (
                              <span className="muted small">{candidate.doctor_name}</span>
                            ) : null}
                          </button>
                        );
                      }
                      return (
                        <button
                          key={`${name}-${candidate.starts_at || index}`}
                          type="button"
                          className="doctor-card"
                          data-testid={`chat-slot-choice-${index + 1}`}
                          disabled={resumeMutation.isPending || choiceExpired}
                          onClick={() => resumeMutation.mutate(index + 1)}
                        >
                          <strong>{name}</strong>
                          <span className="muted small">
                            {[candidate.clinic_code, candidate.specialty_code]
                              .filter(Boolean)
                              .join(" · ") || t("chat.fromClinicSystems")}
                          </span>
                          <span className="doctor-card-slot">{slotLabel}</span>
                          <Badge tone="info">{t("chat.clinicSource")}</Badge>
                        </button>
                      );
                    })}
                  </div>
                  <div className="tag-row" style={{ marginTop: 10 }}>
                    <button
                      type="button"
                      className="btn"
                      disabled={resumeMutation.isPending}
                      onClick={() => {
                        if (!interrupt) return;
                        void api(`/api/v1/chat/runs/${interrupt.run_id}/resume`, {
                          method: "POST",
                          body: {
                            interrupt_id: interrupt.interrupt_id,
                            command: "cancel",
                          },
                        }).then(() => setInterrupt(null));
                      }}
                    >
                      {t("common.cancel")}
                    </button>
                  </div>
                </div>
              ) : null}

              {heldAppointment ? (
                <div className="booking-card" data-testid="chat-booking-hold">
                  <header className="booking-panel-head">
                    <div>
                      <strong>{t("chat.bookingHeld")}</strong>
                      <p className="muted small">{t("chat.bookingHeldHint")}</p>
                    </div>
                    <span
                      className={`hold-countdown${holdSecondsLeft <= 30 ? " hold-countdown-urgent" : ""}`}
                      data-testid="chat-hold-countdown"
                      aria-live="polite"
                    >
                      {t("chat.holdCountdown", { time: formatCountdown(holdSecondsLeft) })}
                    </span>
                  </header>
                  <dl className="booking-card-meta">
                    <div>
                      <dt>{t("appointments.doctorName")}</dt>
                      <dd>{heldAppointment.doctor_name}</dd>
                    </div>
                    <div>
                      <dt>{t("common.clinic")}</dt>
                      <dd>{heldAppointment.clinic_code}</dd>
                    </div>
                    <div>
                      <dt>{t("appointments.slot")}</dt>
                      <dd>{formatDateTime(heldAppointment.starts_at, locale)}</dd>
                    </div>
                  </dl>
                  <FormError message={holdError} />
                  <div className="tag-row">
                    <button
                      type="button"
                      className="btn btn-primary"
                      data-testid="chat-confirm-hold"
                      disabled={
                        confirmHoldMutation.isPending ||
                        releaseHoldMutation.isPending ||
                        holdExpired
                      }
                      onClick={() => confirmHoldMutation.mutate(heldAppointment.id)}
                    >
                      {confirmHoldMutation.isPending ? <Spinner /> : null}
                      {t("chat.confirmBooking")}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      data-testid="chat-release-hold"
                      disabled={confirmHoldMutation.isPending || releaseHoldMutation.isPending}
                      onClick={() => releaseHoldMutation.mutate(heldAppointment.id)}
                    >
                      {t("chat.releaseHold")}
                    </button>
                  </div>
                </div>
              ) : null}

              <FormError message={sendError} />
              {feedbackNote ? <Callout tone="success">{feedbackNote}</Callout> : null}

              <footer className="composer">
                <textarea
                  value={composer}
                  onChange={(event) => setComposer(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      submit();
                    }
                  }}
                  placeholder={t("chat.messagePlaceholder")}
                  rows={2}
                  maxLength={8000}
                  aria-label={t("chat.messagePlaceholder")}
                  data-testid="chat-composer"
                />
                <div className="composer-actions">
                  <label className="composer-lang">
                    <span className="muted small">{t("chat.messageLanguage")}</span>
                    <select
                      value={messageLanguage}
                      onChange={(event) => setMessageLanguage(event.target.value)}
                    >
                      {LANGUAGES.map((language) => (
                        <option key={language.value} value={language.value}>
                          {language.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <IconButton
                    label="Attach report to records"
                    icon={<Paperclip size={16} />}
                    data-testid="chat-attach"
                    onClick={() => {
                      setAttachError(null);
                      setAttachOpen(true);
                    }}
                    disabled={!selected || !me?.patient_id}
                  />
                  <button
                    type="button"
                    className="btn btn-primary"
                    data-testid="chat-send"
                    onClick={submit}
                    disabled={!composer.trim() || sendMutation.isPending}
                  >
                    {sendMutation.isPending ? <Spinner /> : <Send size={15} aria-hidden="true" />}
                    {t("chat.sendMessage")}
                  </button>
                </div>
                <p className="composer-note muted small">{t("chat.notClinical")}</p>
              </footer>
            </>
          )}
        </section>
      </div>

      <Modal
        open={attachOpen}
        title="Add report to your records"
        onClose={() => !attachMutation.isPending && setAttachOpen(false)}
        busy={attachMutation.isPending}
        footer={
          <>
            <button
              type="button"
              className="btn"
              disabled={attachMutation.isPending}
              onClick={() => setAttachOpen(false)}
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              data-testid="chat-attach-submit"
              disabled={attachMutation.isPending || !attachFile || attachTitle.trim().length < 2}
              onClick={() => {
                if (!attachFile || !selected) return;
                const form = new FormData();
                form.append("file", attachFile);
                form.append("title", attachTitle.trim());
                form.append("kind", attachKind);
                form.append("language", messageLanguage);
                if (me?.patient_id) form.append("patient_id", me.patient_id);
                setAttachError(null);
                attachMutation.mutate(form);
              }}
            >
              {attachMutation.isPending ? <Spinner /> : <Upload size={16} aria-hidden="true" />}
              Upload
            </button>
          </>
        }
      >
        <p className="muted small">
          Files are stored as clinical documents (same path as Records), scanned for malware, then
          indexed for later assistant questions.
        </p>
        <Field label="Title">
          <input
            value={attachTitle}
            onChange={(event) => setAttachTitle(event.target.value)}
            maxLength={200}
            data-testid="chat-attach-title"
          />
        </Field>
        <Field label="Report type">
          <select
            value={attachKind}
            onChange={(event) =>
              setAttachKind(event.target.value as (typeof RECORD_KINDS)[number])
            }
            data-testid="chat-attach-kind"
          >
            {RECORD_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="File">
          <input
            type="file"
            data-testid="chat-attach-file"
            onChange={(event) => setAttachFile(event.target.files?.[0] ?? null)}
          />
        </Field>
        <FormError message={attachError} />
      </Modal>

      <Modal
        open={newOpen}
        title={t("chat.newSession")}
        onClose={() => setNewOpen(false)}
        busy={createMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setNewOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? <Spinner /> : <Plus size={15} aria-hidden="true" />}
              {t("common.create")}
            </button>
          </>
        }
      >
        <div className="form-stack">
          <Field label={t("chat.sessionTitle")} hint={t("common.optional")}>
            <input
              value={newTitle}
              maxLength={80}
              onChange={(event) => setNewTitle(event.target.value)}
              placeholder={t("chat.sessionFallback")}
              autoFocus
            />
          </Field>
          <FormError message={createError} />
        </div>
      </Modal>

      <Modal
        open={renameOpen}
        title={t("chat.renameSession")}
        onClose={() => setRenameOpen(false)}
        busy={renameMutation.isPending}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setRenameOpen(false)}>
              {t("common.cancel")}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!renameTitle.trim() || renameMutation.isPending}
              onClick={() => renameMutation.mutate(renameTitle.trim())}
            >
              {renameMutation.isPending ? <Spinner /> : null}
              {t("chat.rename")}
            </button>
          </>
        }
      >
        <Field label={t("chat.sessionTitle")}>
          <input
            value={renameTitle}
            maxLength={80}
            onChange={(event) => setRenameTitle(event.target.value)}
            autoFocus
          />
        </Field>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={t("chat.deleteSession")}
        body={<p>{t("chat.deleteSessionBody")}</p>}
        confirmLabel={t("common.delete")}
        tone="danger"
        busy={deleteMutation.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
}

function groupSessionsByDay(
  sessions: ChatSession[],
  timezone?: string,
): Array<{ label: string; items: ChatSession[] }> {
  const tz = timezone || "Asia/Kolkata";
  const todayKey = dayKey(new Date(), tz);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayKey = dayKey(yesterday, tz);
  const groups = new Map<string, ChatSession[]>();
  const order: string[] = [];
  for (const session of sessions) {
    const key = dayKey(new Date(session.updated_at), tz);
    const label =
      key === todayKey ? "Today" : key === yesterdayKey ? "Yesterday" : key;
    if (!groups.has(label)) {
      groups.set(label, []);
      order.push(label);
    }
    groups.get(label)!.push(session);
  }
  return order.map((label) => ({ label, items: groups.get(label) ?? [] }));
}

function dayKey(date: Date, timezone: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
  } catch {
    return date.toISOString().slice(0, 10);
  }
}
