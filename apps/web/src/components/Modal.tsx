import { X } from "lucide-react";
import { useEffect, useEffectEvent, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { IconButton } from "./IconButton";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  size = "md",
  busy = false,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  busy?: boolean;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  // Keep latest onClose without re-running the focus trap on every parent render
  // (inline onClose={() => ...} would otherwise steal focus from controlled inputs).
  const onCloseEvent = useEffectEvent(onClose);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusables = () =>
      panel
        ? Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
            (el) => !el.hasAttribute("disabled") && el.tabIndex !== -1,
          )
        : [];

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) {
        event.stopPropagation();
        onCloseEvent();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const nodes = focusables();
      if (nodes.length === 0) {
        event.preventDefault();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Move focus into the dialog once when it opens — not on every keystroke.
    requestAnimationFrame(() => {
      const nodes = focusables();
      const active = document.activeElement;
      if (panel && active instanceof Node && panel.contains(active)) return;
      (nodes[0] ?? panel)?.focus();
    });
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      previouslyFocused.current?.focus?.();
    };
    // onCloseEvent is an Effect Event — intentionally omitted from deps.
  }, [open, busy]);

  if (!open) return null;

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={panelRef}
        className={`modal modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <header className="modal-header">
          <div>
            <h2 id={titleId}>{title}</h2>
            {description ? (
              <p id={descriptionId} className="modal-description">
                {description}
              </p>
            ) : null}
          </div>
          <IconButton label="Close" icon={<X size={18} />} onClick={onClose} disabled={busy} />
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-footer">{footer}</footer> : null}
      </div>
    </div>,
    document.body,
  );
}
