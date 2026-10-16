import type { DocStatus } from "../api";

const LABELS: Record<DocStatus, string> = {
  pending: "En attente",
  processing: "Indexation",
  ready: "Prêt",
  failed: "Échec",
  deleting: "Suppression",
};

export function StatusBadge({ status }: { status: DocStatus }) {
  const busy = status === "pending" || status === "processing" || status === "deleting";
  return (
    <span className={`badge ${status}`}>
      {busy ? <span className="spinner" /> : <span className="status-dot" style={{ background: "currentColor", margin: 0, width: 6, height: 6 }} />}
      {LABELS[status]}
    </span>
  );
}
