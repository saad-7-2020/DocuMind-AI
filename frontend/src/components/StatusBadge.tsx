import type { DocStatus } from "../api";
import { useI18n } from "../i18n";

export function StatusBadge({ status }: { status: DocStatus }) {
  const { t } = useI18n();
  const busy = status === "pending" || status === "processing" || status === "deleting";
  return (
    <span className={`badge ${status}`}>
      {busy ? <span className="spinner" /> : <span className="status-dot" style={{ background: "currentColor", margin: 0, width: 6, height: 6 }} />}
      {t(`status.${status}`)}
    </span>
  );
}
