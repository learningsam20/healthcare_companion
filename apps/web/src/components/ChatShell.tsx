import { LogOut, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { clearChatStandalone, useAuth } from "../lib/auth";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";

/** Chat-only frame for a direct /chat sign-in. The workspace shell stays available. */
export function ChatShell({ children }: { children: ReactNode }) {
  const { name, signOut } = useAuth();
  const { t, locale, setLocale, locales } = useI18n();
  const theme = useTheme();

  return (
    <div className="chat-shell" data-testid="chat-shell">
      <header className="topbar">
        <div className="topbar-start">
          <span className="brand-mark" aria-hidden="true">
            स
          </span>
          <h2 className="topbar-title">{t("nav.chat")}</h2>
        </div>
        <div className="topbar-end">
          <Link to="/" className="btn btn-sm" onClick={() => clearChatStandalone()}>
            {t("shell.openWorkspace")}
          </Link>
          <div className="lang-select">
            <select
              value={locale}
              onChange={(event) => setLocale(event.target.value as typeof locale)}
              aria-label={t("shell.language")}
            >
              {locales.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label={theme.resolved === "dark" ? t("shell.themeLight") : t("shell.themeDark")}
            onClick={theme.toggle}
          >
            {theme.resolved === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <span className="chat-shell-user">{name}</span>
          <button type="button" className="btn btn-sm" onClick={() => signOut()}>
            <LogOut size={14} aria-hidden="true" /> {t("auth.signOut")}
          </button>
        </div>
      </header>
      <main className="content" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
