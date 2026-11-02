import { useQuery } from "@tanstack/react-query";
import Keycloak from "keycloak-js";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, errorMessage, isApiError, setApiAccessToken } from "./api";
import { useI18n } from "./i18n";
import type { Me, Role } from "./types";

const authority = (import.meta.env.VITE_OIDC_AUTHORITY as string | undefined)?.trim();
const clientId = (import.meta.env.VITE_OIDC_CLIENT_ID as string | undefined)?.trim();
const configuredRedirect = (import.meta.env.VITE_OIDC_REDIRECT_URI as string | undefined)?.trim();
const configuredLogout = (
  import.meta.env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI as string | undefined
)?.trim();

type Status = "initializing" | "ready" | "config-missing" | "error" | "unauthenticated";

interface AuthValue {
  me: Me;
  name: string;
  email: string | null;
  signIn: () => void;
  signOut: () => void;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

let instance: Keycloak | null = null;
let initPromise: Promise<Keycloak> | null = null;

function realmConfig(): { url: string; realm: string; clientId: string } | null {
  if (!authority || !clientId) return null;
  const match = /^(.*)\/realms\/([^/]+)\/?$/.exec(authority);
  if (!match) return null;
  return { url: match[1], realm: match[2], clientId };
}

function sameOrigin(uri: string | undefined): string | undefined {
  if (!uri) return undefined;
  try {
    return new URL(uri).origin === window.location.origin ? uri : undefined;
  } catch {
    return undefined;
  }
}

function initialize(): Promise<Keycloak> {
  if (initPromise) return initPromise;
  const config = realmConfig();
  if (!config) return Promise.reject(new Error("identity_config_missing"));
  instance = new Keycloak(config);
  initPromise = instance
    .init({
      onLoad: "login-required",
      flow: "standard",
      pkceMethod: "S256",
      checkLoginIframe: false,
      redirectUri: sameOrigin(configuredRedirect),
    })
    .then((authenticated) => {
      if (!authenticated) throw new Error("not_authenticated");
      return instance as Keycloak;
    });
  return initPromise;
}

function profileName(keycloak: Keycloak): string {
  const parsed = keycloak.tokenParsed as Record<string, unknown> | undefined;
  const name = parsed?.name ?? parsed?.preferred_username;
  return typeof name === "string" && name ? name : "Care team member";
}

function profileEmail(keycloak: Keycloak): string | null {
  const parsed = keycloak.tokenParsed as Record<string, unknown> | undefined;
  return typeof parsed?.email === "string" ? parsed.email : null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<Status>("initializing");
  const [keycloak, setKeycloak] = useState<Keycloak | null>(null);
  const [name, setName] = useState("Care team member");
  const [email, setEmail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    initialize()
      .then((kc) => {
        if (!active) return;
        if (window.location.pathname === "/auth/callback") {
          window.history.replaceState({}, "", "/");
        }
        setApiAccessToken(kc.token ?? null);
        setKeycloak(kc);
        setName(profileName(kc));
        setEmail(profileEmail(kc));
        setStatus("ready");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (reason instanceof Error && reason.message === "identity_config_missing") {
          setStatus("config-missing");
          return;
        }
        setError(reason instanceof Error ? reason.message : null);
        setStatus("error");
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!keycloak) return;
    const refresh = () => {
      keycloak
        .updateToken(60)
        .then(() => {
          setApiAccessToken(keycloak.token ?? null);
          setName(profileName(keycloak));
        })
        .catch(() => {
          keycloak.login({ redirectUri: sameOrigin(configuredRedirect) }).catch(() => undefined);
        });
    };
    keycloak.onTokenExpired = refresh;
    const timer = window.setInterval(refresh, 30_000);
    return () => {
      window.clearInterval(timer);
    };
  }, [keycloak]);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/api/v1/auth/me"),
    enabled: status === "ready",
    retry: false,
    staleTime: 60_000,
  });

  const signIn = useCallback(() => {
    if (!instance) {
      window.location.reload();
      return;
    }
    instance.login({ redirectUri: sameOrigin(configuredRedirect) }).catch(() => {
      setError(t("auth.unavailableBody"));
      setStatus("error");
    });
  }, [t]);

  const signOut = useCallback(() => {
    if (!keycloak) return;
    setApiAccessToken(null);
    // Prefer the page origin so Vite (:5729) and Compose web (:5705) both work.
    // Configured POST_LOGOUT URI is only used when it matches this origin.
    const redirectUri =
      sameOrigin(configuredLogout) ?? `${window.location.origin}/`;
    keycloak
      .logout({ redirectUri })
      .catch(() => {
        // Keycloak reject (missing post.logout allowlist) still clears local session.
        try {
          keycloak.clearToken();
        } catch {
          /* ignore */
        }
        window.location.assign(redirectUri);
      });
  }, [keycloak]);

  const hasRole = useCallback(
    (...roles: Role[]) => Boolean(meQuery.data?.roles.some((role) => roles.includes(role as Role))),
    [meQuery.data],
  );

  const value = useMemo<AuthValue | null>(() => {
    if (!meQuery.data) return null;
    return {
      me: meQuery.data,
      name,
      email,
      signIn,
      signOut,
      hasRole,
    };
  }, [meQuery.data, name, email, signIn, signOut, hasRole]);

  if (status === "config-missing") {
    return <StatusScreen title={t("auth.configMissingTitle")} body={t("auth.configMissingBody")} />;
  }

  if (status === "initializing") {
    return <LoadingScreen label={t("auth.signingIn")} />;
  }

  if (status === "error" || status === "unauthenticated") {
    return (
      <StatusScreen
        title={t("auth.unavailable")}
        body={error ?? t("auth.unavailableBody")}
        actionLabel={t("auth.signIn")}
        onAction={signIn}
      />
    );
  }

  if (meQuery.isPending) {
    return <LoadingScreen label={t("common.loading")} />;
  }

  if (meQuery.isError || !value) {
    const detail = isApiError(meQuery.error)
      ? meQuery.error.detail
      : errorMessage(meQuery.error);
    return (
      <StatusScreen
        title={t("auth.accessDenied")}
        body={detail}
        actionLabel={t("auth.signIn")}
        onAction={signIn}
        secondaryLabel={t("auth.signOut")}
        onSecondary={signOut}
      />
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

function BrandMark() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <span>स</span>
    </div>
  );
}

function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="auth-screen">
      <div className="auth-card">
        <BrandMark />
        <div className="spinner" aria-hidden="true" />
        <p className="muted">{label}</p>
      </div>
    </main>
  );
}

function StatusScreen({
  title,
  body,
  actionLabel,
  onAction,
  secondaryLabel,
  onSecondary,
}: {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryLabel?: string;
  onSecondary?: () => void;
}) {
  return (
    <main className="auth-screen">
      <div className="auth-card">
        <BrandMark />
        <h1>{title}</h1>
        <p className="muted">{body}</p>
        <div className="auth-actions">
          {actionLabel && onAction ? (
            <button type="button" className="btn btn-primary" onClick={onAction}>
              {actionLabel}
            </button>
          ) : null}
          {secondaryLabel && onSecondary ? (
            <button type="button" className="btn" onClick={onSecondary}>
              {secondaryLabel}
            </button>
          ) : null}
        </div>
      </div>
    </main>
  );
}
