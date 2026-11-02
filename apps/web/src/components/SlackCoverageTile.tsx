import { useQuery } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";

import { api, errorMessage } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { Badge } from "./Badge";
import { Callout, FormError, Spinner, Stat } from "./primitives";

export interface SlackCoverage {
  opted_in: number;
  verified: number;
  coverage_percent: number | null;
  status: "no_opted_in_contacts" | "complete" | "below_target";
  meets_target: boolean;
  delivery_ready: boolean;
  not_covered: Record<string, number>;
  metadata_only_unverified: number;
}

/** G-07: % of opted-in patient Slack contacts that are verified and deliverable (admin). */
export function SlackCoverageTile() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["notifications", "slack-coverage"],
    queryFn: () => api<SlackCoverage>("/api/v1/notifications/slack-coverage"),
    staleTime: 60_000,
  });
  const data = query.data;

  return (
    <section className="panel" data-testid="slack-coverage">
      <div className="panel-head">
        <h3>
          <MessageSquare size={17} aria-hidden="true" /> {t("notifications.slackCoverage")}
        </h3>
        {data ? (
          <Badge tone={data.status === "complete" ? "success" : "warning"}>
            {data.coverage_percent === null ? "—" : `${data.coverage_percent}%`}
          </Badge>
        ) : null}
      </div>
      {query.isPending ? <Spinner /> : null}
      {query.isError ? <FormError message={errorMessage(query.error)} /> : null}
      {data ? (
        <>
          <Stat
            label={t("notifications.slackCoverage")}
            value={data.coverage_percent === null ? "—" : `${data.coverage_percent}%`}
            hint={
              data.opted_in
                ? t("notifications.slackCoverageDetail", {
                    verified: data.verified,
                    optedIn: data.opted_in,
                  })
                : t("notifications.slackCoverageEmpty")
            }
          />
          {data.status === "below_target" ? (
            <Callout tone="warning">{t("notifications.slackCoverageBelow")}</Callout>
          ) : null}
          {!data.delivery_ready ? (
            <Callout tone="info">{t("notifications.slackDeliveryNotReady")}</Callout>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
