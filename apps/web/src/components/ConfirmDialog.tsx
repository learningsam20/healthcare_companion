import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../lib/i18n";
import { Modal } from "./Modal";

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel,
  tone = "primary",
  busy = false,
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      busy={busy}
      size="sm"
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {cancelLabel ?? t("common.cancel")}
          </button>
          <button
            type="button"
            className={`btn ${tone === "danger" ? "btn-danger" : "btn-primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : null}
            {confirmLabel}
          </button>
        </>
      }
    >
      {children}
      <div className="confirm-body">{body}</div>
    </Modal>
  );
}
