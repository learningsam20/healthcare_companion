import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bell,
  CalendarDays,
  ChevronDown,
  ClipboardList,
  FileCheck,
  FolderOpen,
  HeartHandshake,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  MessageCircle,
  Mic,
  Moon,
  Package,
  Settings,
  Shield,
  Sun,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { api, qs } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useCareContext } from "../lib/careContext";
import { initials } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import type { GridMeta, Meta, NotificationRow, Role } from "../lib/types";
import type { TranslationKey } from "../i18n/locales";
import { Badge } from "./Badge";
import { IconButton, useOutsideClose } from "./IconButton";

interface NavItem {
  to: string;
  label: TranslationKey;
  icon: LucideIcon;
  roles: Role[];
}

interface NavSection {
  label: TranslationKey;
  items: NavItem[];
}

const ALL_ROLES: Role[] = [
  "patient",
  "caregiver",
  "doctor",
  "front_desk",
  "pharmacist",
  "compliance",
  "admin",
];

const NAV: NavSection[] = [
  {
    label: "nav.workspace",
    items: [
      { to: "/", label: "nav.dashboard", icon: LayoutDashboard, roles: ALL_ROLES },
      {
        to: "/chat",
        label: "nav.chat",
        icon: MessageCircle,
        roles: ["patient", "caregiver", "doctor", "front_desk", "admin"],
      },
      {
        to: "/appointments",
        label: "nav.appointments",
        icon: CalendarDays,
        roles: ["patient", "caregiver", "doctor", "front_desk", "admin"],
      },
      {
        to: "/patients",
        label: "nav.patients",
        icon: Users,
        roles: ["front_desk", "doctor", "compliance", "admin"],
      },
      {
        to: "/records",
        label: "nav.records",
        icon: FolderOpen,
        roles: ["patient", "caregiver", "doctor", "front_desk", "admin"],
      },
      {
        to: "/care-circle",
        label: "nav.careCircle",
        icon: HeartHandshake,
        roles: ["patient", "caregiver", "admin"],
      },
    ],
  },
  {
    label: "nav.clinical",
    items: [
      { to: "/scribe", label: "nav.scribe", icon: Mic, roles: ["doctor"] },
      {
        to: "/notes",
        label: "nav.notes",
        icon: FileCheck,
        roles: ["patient", "caregiver", "doctor", "pharmacist", "compliance", "admin"],
      },
      {
        to: "/pharmacy",
        label: "nav.pharmacy",
        icon: Package,
        roles: ["pharmacist", "front_desk", "admin"],
      },
      {
        to: "/review-queue",
        label: "nav.review",
        icon: ClipboardList,
        roles: ["doctor", "pharmacist", "front_desk", "compliance", "admin"],
      },
      {
        to: "/escalations",
        label: "nav.escalations",
        icon: ClipboardList,
        roles: ["doctor", "front_desk", "compliance", "admin"],
      },
      {
        to: "/front-desk",
        label: "nav.frontDesk",
        icon: CalendarDays,
        roles: ["front_desk", "admin"],
      },
      {
        to: "/waitlist",
        label: "nav.waitlist",
        icon: ListChecks,
        roles: ["front_desk", "admin"],
      },
    ],
  },
  {
    label: "nav.insights",
    items: [
      {
        to: "/analytics",
        label: "nav.analytics",
        icon: BarChart3,
        roles: ["compliance", "admin"],
      },
      {
        to: "/ops",
        label: "nav.ops",
        icon: Activity,
        roles: ["admin"],
      },
    ],
  },
  {
    label: "nav.operations",
    items: [
      { to: "/notifications", label: "nav.notifications", icon: Bell, roles: ALL_ROLES },
      {
        to: "/governance",
        label: "nav.governance",
        icon: Shield,
        roles: ["compliance", "admin"],
      },
      { to: "/settings", label: "nav.settings", icon: Settings, roles: ALL_ROLES },
    ],
  },
];

interface NotificationPeek {
  items: NotificationRow[];
  meta: GridMeta;
  unread: number;
}

export function AppShell({ children }: { children?: ReactNode }) {
  const { me, name, email, signOut, hasRole } = useAuth();
  const care = useCareContext();
  const { t, locale, setLocale, locales } = useI18n();
  const theme = useTheme();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const userRef = useRef<HTMLDivElement>(null);
  useOutsideClose(userRef, () => setUserOpen(false), userOpen);

  const metaQuery = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/api/v1/meta"),
    staleTime: 5 * 60_000,
  });

  const unreadQuery = useQuery({
    queryKey: ["notifications", "unread-count", me.subject],
    queryFn: () =>
      api<NotificationPeek>(`/api/v1/notifications${qs({ status: "unread", page_size: 1 })}`),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const sections = NAV.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.roles.some((role) => hasRole(role))),
  })).filter((section) => section.items.length > 0);

  const currentItem = NAV.flatMap((section) => section.items).find((item) =>
    item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to),
  );
  const title = currentItem ? t(currentItem.label) : t("nav.dashboard");
  const unread = unreadQuery.data?.meta.total ?? 0;
  const appName = metaQuery.data?.app.name ?? "Sahyog Care Companion";
  const clinics = metaQuery.data?.clinics ?? [];
  const clinicNames = clinics
    .filter((clinic) => me.clinic_ids.includes(clinic.code))
    .map((clinic) => clinic.name);

  return (
    <div className="app-shell" data-testid="app-shell">
      <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`}>
        <div className="sidebar-brand">
          <Link to="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              स
            </span>
            <span className="brand-text">
              <strong>{appName}</strong>
              <small>Care Companion</small>
            </span>
          </Link>
          <button
            type="button"
            className="sidebar-close"
            onClick={() => setMobileOpen(false)}
            aria-label={t("common.close")}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation" data-testid="shell-nav">
          {sections.map((section) => (
            <div className="nav-section" key={section.label}>
              <span className="nav-section-label">{t(section.label)}</span>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) => `nav-link ${isActive ? "is-active" : ""}`}
                >
                  <item.icon size={18} aria-hidden="true" />
                  <span>{t(item.label)}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="env-chip">{metaQuery.data?.app.environment ?? "—"}</span>
        </div>
      </aside>

      {mobileOpen ? (
        <button
          type="button"
          className="sidebar-scrim"
          aria-label={t("common.close")}
          onClick={() => setMobileOpen(false)}
        />
      ) : null}

      <div className="main-area">
        <header className="topbar">
          <div className="topbar-start">
            <button
              type="button"
              className="menu-btn"
              data-testid="shell-menu"
              onClick={() => setMobileOpen(true)}
              aria-label={t("shell.menuToggle")}
            >
              <Menu size={20} aria-hidden="true" />
            </button>
            <h2 className="topbar-title">{title}</h2>
            <Badge tone={me.traffic_class === "synthetic" ? "warning" : "violet"}>
              {me.traffic_class}
            </Badge>
          </div>

          <div className="topbar-end">
            {me.primary_role === "caregiver" ? (
              care.contexts.length ? (
                <div className="lang-select context-select" data-tooltip={t("careCircle.contextHint")}>
                  <select
                    value={care.active?.consent_id ?? ""}
                    onChange={(event) => {
                      const next =
                        care.contexts.find((item) => item.consent_id === event.target.value) ?? null;
                      void care.select(next).catch(() => undefined);
                    }}
                    aria-label={t("careCircle.selectContext")}
                  >
                    <option value="">{t("careCircle.selectContext")}</option>
                    {care.contexts.map((item) => (
                      <option key={item.consent_id} value={item.consent_id}>
                        {item.patient_name ?? item.patient_id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </div>
              ) : (
                <Link to="/care-circle" className="context-empty">
                  {t("careCircle.noContextsShort")}
                </Link>
              )
            ) : null}

            <div className="notification-wrap">
              <Link
                to="/notifications"
                className="icon-btn notification-btn tooltip-below"
                aria-label={
                  unread > 0
                    ? `${t("shell.notifications")} (${unread > 9 ? "9+" : unread})`
                    : t("shell.notifications")
                }
                data-tooltip={t("shell.notifications")}
              >
                <Bell size={18} aria-hidden="true" />
              </Link>
              {unread > 0 ? (
                <span className="notification-dot" aria-hidden="true">
                  {unread > 9 ? "9+" : unread}
                </span>
              ) : null}
            </div>

            <div className="lang-select" data-tooltip={t("shell.language")}>
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

            <IconButton
              label={theme.resolved === "dark" ? t("shell.themeLight") : t("shell.themeDark")}
              icon={theme.resolved === "dark" ? <Sun size={18} /> : <Moon size={18} />}
              onClick={theme.toggle}
            />

            <div className="user-menu" ref={userRef}>
              <button
                type="button"
                className="user-trigger"
                onClick={() => setUserOpen((current) => !current)}
                aria-haspopup="menu"
                aria-expanded={userOpen}
              >
                <span className="avatar">{initials(name)}</span>
                <span className="user-trigger-text">
                  <strong>{name}</strong>
                  <small>{me.primary_role.replace("_", " ")}</small>
                </span>
                <ChevronDown size={14} aria-hidden="true" />
              </button>
              {userOpen ? (
                <div className="user-popover" role="menu">
                  <div className="user-popover-head">
                    <span className="avatar avatar-lg">{initials(name)}</span>
                    <div>
                      <strong>{name}</strong>
                      {email ? <small>{email}</small> : null}
                      <code className="subject">{me.subject.slice(0, 8)}…</code>
                    </div>
                  </div>
                  <div className="user-roles">
                    {me.roles.map((role) => (
                      <Badge key={role} tone={role === me.primary_role ? "info" : "neutral"}>
                        {role.replace("_", " ")}
                      </Badge>
                    ))}
                  </div>
                  <div className="user-clinics">
                    <span className="muted">{t("shell.clinicScope")}</span>
                    <span>{clinicNames.length ? clinicNames.join(", ") : t("shell.noClinic")}</span>
                  </div>
                  <Link to="/settings" className="popover-link" onClick={() => setUserOpen(false)}>
                    <Settings size={15} aria-hidden="true" /> {t("nav.settings")}
                  </Link>
                  <button type="button" className="popover-link" onClick={signOut}>
                    <LogOut size={15} aria-hidden="true" /> {t("auth.signOut")}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <main className="content" id="main-content" tabIndex={-1}>
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  );
}
