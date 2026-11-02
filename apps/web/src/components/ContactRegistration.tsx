import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { useState } from "react";

import { api, errorMessage } from "../lib/api";
import { humanize } from "../lib/format";
import { useI18n } from "../lib/i18n";
import type { ContactChannel } from "../lib/types";
import { Badge } from "./Badge";
import { ContactVerify } from "./ContactVerify";
import { Callout, Field, FormError, Spinner } from "./primitives";

const SLACK_MEMBER_ID = /^[UW][A-Z0-9]{6,39}$/;

/**
 * Patient/caregiver self-registration of a Slack member ID (G-06/G-07).
 * Saved contacts are always unverified until the one-time code is confirmed.
 */
export function ContactRegistration({
  adapters,
  environment,
}: {
  adapters: Record<string, { status: string }> | undefined;
  environment: string | undefined;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [slackId, setSlackId] = useState("");
  const [optIn, setOptIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const contactsQuery = useQuery({
    queryKey: ["me", "contacts"],
    queryFn: () => api<ContactChannel[]>("/api/v1/me/contacts"),
  });

  const register = useMutation({
    mutationFn: () =>
      api<ContactChannel>("/api/v1/me/contacts", {
        method: "POST",
        body: { channel: "slack_patient", address: slackId.trim(), opt_in: optIn },
      }),
    onSuccess: () => {
      setSlackId("");
      setError(null);
      setNotice(t("notifications.registerNote"));
      void queryClient.invalidateQueries({ queryKey: ["me", "contacts"] });
    },
    onError: (err) => {
      setNotice(null);
      setError(errorMessage(err));
    },
  });

  const submit = () => {
    if (!SLACK_MEMBER_ID.test(slackId.trim())) {
      setNotice(null);
      setError(t("notifications.slackMemberIdHint"));
      return;
    }
    setError(null);
    register.mutate();
  };

  return (
    <section className="panel" data-testid="contact-registration">
      <div className="panel-head">
        <h3>
          <MessageSquare size={17} aria-hidden="true" /> {t("notifications.myContacts")}
        </h3>
      </div>
      <p className="muted small">{t("notifications.myContactsHint")}</p>
      <div className="preference-list">
        <Field
          label={t("notifications.slackMemberId")}
          hint={t("notifications.slackMemberIdHint")}
        >
          <input
            value={slackId}
            maxLength={40}
            autoComplete="off"
            onChange={(event) => setSlackId(event.target.value)}
          />
        </Field>
        <label className="check-row inline">
          <input
            type="checkbox"
            checked={optIn}
            onChange={(event) => setOptIn(event.target.checked)}
          />
          <span>{t("notifications.optIn")}</span>
        </label>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!slackId.trim() || register.isPending}
          onClick={submit}
        >
          {register.isPending ? <Spinner /> : null}
          {t("notifications.registerSlack")}
        </button>
      </div>
      <FormError message={error} />
      {notice ? <Callout tone="success">{notice}</Callout> : null}
      <ul className="plain-list" style={{ marginTop: 12 }}>
        {(contactsQuery.data ?? []).map((contact) => (
          <li key={contact.id}>
            <div>
              <strong>{humanize(contact.channel)}</strong>
              <span className="muted small"> · {contact.address}</span>{" "}
              {contact.opt_in ? <Badge tone="success">{t("notifications.optIn")}</Badge> : null}
            </div>
            <ContactVerify
              contact={contact}
              channelStatus={adapters?.[contact.channel]?.status}
              environment={environment}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
