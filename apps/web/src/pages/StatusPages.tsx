import { Compass, ShieldX } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState, PageHeader } from "../components/primitives";
import { useI18n } from "../lib/i18n";

export function ForbiddenPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("auth.accessDenied")} />
      <div className="panel">
        <EmptyState
          icon={<ShieldX size={22} aria-hidden="true" />}
          title={t("auth.accessDenied")}
          hint={t("auth.accessDeniedBody")}
          action={
            <Link className="btn btn-primary" to="/">
              {t("auth.backHome")}
            </Link>
          }
        />
      </div>
    </>
  );
}

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("auth.notFoundTitle")} />
      <div className="panel">
        <EmptyState
          icon={<Compass size={22} aria-hidden="true" />}
          title={t("auth.notFoundTitle")}
          hint={t("auth.notFoundBody")}
          action={
            <Link className="btn btn-primary" to="/">
              {t("auth.backHome")}
            </Link>
          }
        />
      </div>
    </>
  );
}
