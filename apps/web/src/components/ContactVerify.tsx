import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, errorMessage } from "../lib/api";
import { humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { ContactChannel } from "../lib/types";
import { Badge } from "./Badge";
import { FormError, Spinner } from "./primitives";

interface VerificationRequested {
  expires_at: string;
  code?: string | null;
  delivery: "sent" | "unconfigured" | "external_disabled" | "failed";
  delivery_error?: string | null;
}

/**
 * One-time-code verification for a contact (G-06/G-07).
 *
 * The code is sent over the contact's own channel only when that adapter is configured
 * (token present). Otherwise the UI says so; the code is only shown in dev/test builds
 * because the API only returns it there.
 */
export function ContactVerify({
  contact,
  channelStatus,
  environment,
}: {
  contact: ContactChannel;
  /** `/meta` adapter status for this channel: configured | unconfigured | disabled. */
  channelStatus: string | undefined;
  environment: string | undefined;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [code, setCode] = useState("");
  const [requested, setRequested] = useState<VerificationRequested | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const devEnvironment = environment === "dev" || environment === "test";
  const canDeliver = channelStatus === "configured";

  const requestCode = useMutation({
    mutationFn: () =>
      api<VerificationRequested>(
        `/api/v1/notifications/contacts/${contact.id}/request-verification`,
        { method: "POST" },
      ),
    onSuccess: (result) => {
      setRequested(result);
      setError(null);
    },
    onError: (err) => setError(errorMessage(err)),
  });

  const confirm = useMutation({
    mutationFn: () =>
      api<ContactChannel>(`/api/v1/notifications/contacts/${contact.id}/verify`, {
        method: "POST",
        body: { code },
      }),
    onSuccess: () => {
      setDone(true);
      setError(null);
      setCode("");
      void queryClient.invalidateQueries({ queryKey: ["notifications", "contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["me", "contacts"] });
      void queryClient.invalidateQueries({ queryKey: ["notifications", "slack-coverage"] });
    },
    onError: (err) => setError(errorMessage(err)),
  });

  if (contact.verified || done) {
    return <Badge tone="success">{done ? t("notifications.verifiedNow") : t("notifications.verified")}</Badge>;
  }

  if (!canDeliver && !devEnvironment) {
    return <Badge tone="warning">{t("notifications.channelUnconfigured")}</Badge>;
  }

  return (
    <div className="stack" data-testid={`contact-verify-${contact.channel}`}>
      {!canDeliver ? (
        <span className="muted small">{t("notifications.channelUnconfigured")}</span>
      ) : null}
      <div className="field-row">
        <button
          type="button"
          className="btn btn-sm"
          disabled={requestCode.isPending}
          onClick={() => requestCode.mutate()}
        >
          {requestCode.isPending ? <Spinner /> : null}
          {t("notifications.sendCode")}
        </button>
        {requested ? (
          <>
            <input
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              value={code}
              placeholder={t("notifications.enterCode")}
              aria-label={t("notifications.enterCode")}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
            />
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={code.length !== 6 || confirm.isPending}
              onClick={() => confirm.mutate()}
            >
              {confirm.isPending ? <Spinner /> : null}
              {t("notifications.confirmCode")}
            </button>
          </>
        ) : null}
      </div>
      {requested ? (
        <p className="muted small" role="status">
          {requested.delivery === "sent"
            ? t("notifications.codeSent", { channel: humanize(contact.channel) })
            : t("notifications.codeNotDelivered", {
                reason: requested.delivery_error ?? requested.delivery,
              })}
          {requested.code ? ` ${t("notifications.codeDevOnly", { code: requested.code })}` : ""}
        </p>
      ) : null}
      <FormError message={error} />
    </div>
  );
}
