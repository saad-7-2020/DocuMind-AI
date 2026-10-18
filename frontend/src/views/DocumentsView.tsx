import { useMemo, useRef, useState } from "react";
import { api, ApiError, describeError, formatBytes, formatDate, type DocStatus, type DocumentSummary } from "../api";
import type { ViewerTarget } from "../components/DocumentViewer";
import { IconCheck, IconEye, IconFiles, IconRefresh, IconSearch, IconTrash, IconUpload, IconX } from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toasts";

const ACCEPT = ".pdf,.txt,application/pdf,text/plain";

const STAGES: Record<string, string> = {
  extracting: "Extraction du texte",
  cleaning: "Nettoyage",
  chunking: "Découpage en chunks",
  embedding: "Calcul des embeddings",
  storing: "Enregistrement",
  done: "Terminé",
};

interface UploadTask {
  id: string;
  name: string;
  size: number;
  phase: "uploading" | "processing" | "done" | "failed";
  progress: number; // 0..1 across both phases
  stage?: string;
  error?: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function DocumentsView({
  docs, loaded, refresh, onOpen, maxUploadBytes,
}: {
  docs: DocumentSummary[];
  loaded: boolean;
  refresh: () => Promise<void>;
  onOpen: (t: ViewerTarget) => void;
  maxUploadBytes?: number;
}) {
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [over, setOver] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | DocStatus>("all");
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const update = (id: string, patch: Partial<UploadTask>) =>
    setTasks((all) => all.map((t) => (t.id === id ? { ...t, ...patch } : t)));

  async function uploadOne(file: File) {
    if (maxUploadBytes && file.size > maxUploadBytes) {
      toast("error", `« ${file.name} » fait ${formatBytes(file.size)} : la limite est de ${formatBytes(maxUploadBytes)}.`);
      return;
    }
    const id = `${file.name}-${Date.now()}-${Math.random()}`;
    setTasks((all) => [{ id, name: file.name, size: file.size, phase: "uploading", progress: 0 }, ...all]);
    try {
      // Phase 1: bytes over the wire (0 → 40 %).
      const accepted = await api.uploadDocument(file, (f) => update(id, { progress: f * 0.4 }));
      update(id, { phase: "processing", progress: 0.4, stage: "En file d'attente" });
      refresh();
      // Phase 2: the worker's pipeline, reported through the job (40 → 100 %).
      for (let i = 0; i < 900; i++) {
        await sleep(1000);
        const job = await api.getJob(accepted.job_id);
        update(id, {
          progress: 0.4 + 0.6 * job.progress,
          stage: job.status === "queued" && job.attempts > 0 ? `Nouvelle tentative (${job.attempts})…` : STAGES[job.stage ?? ""] ?? "En file d'attente",
        });
        if (job.status === "succeeded") {
          update(id, { phase: "done", progress: 1, stage: "Indexé" });
          toast("success", `« ${file.name} » est prêt.`);
          break;
        }
        if (job.status === "failed") {
          throw new ApiError(422, job.error_code ?? "extraction_failed", "Échec de l'indexation");
        }
      }
    } catch (e) {
      update(id, { phase: "failed", error: describeError(e) });
      toast("error", `${file.name} : ${describeError(e)}`);
    } finally {
      refresh();
    }
  }

  function handleFiles(list: FileList | null) {
    if (!list) return;
    Array.from(list).forEach(uploadOne);
  }

  async function remove(doc: DocumentSummary) {
    if (!confirm(`Supprimer « ${doc.filename} » ? Ses chunks ne seront plus jamais cités.`)) return;
    try {
      await api.deleteDocument(doc.id);
      toast("success", "Suppression lancée.");
    } catch (e) {
      toast("error", describeError(e));
    }
    refresh();
  }

  async function reindex(doc: DocumentSummary) {
    try {
      await api.reindexDocument(doc.id);
      toast("success", `Réindexation de « ${doc.filename} » lancée.`);
    } catch (e) {
      toast("error", describeError(e));
    }
    refresh();
  }

  const stats = useMemo(() => ({
    total: docs.length,
    ready: docs.filter((d) => d.status === "ready").length,
    busy: docs.filter((d) => d.status === "pending" || d.status === "processing").length,
    pages: docs.reduce((n, d) => n + (d.page_count ?? 0), 0),
  }), [docs]);

  const visible = docs.filter(
    (d) => (filter === "all" || d.status === filter) && d.filename.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Documents</h1>
          <p className="page-subtitle">Importez des PDF ou des fichiers texte. Ils sont découpés, vectorisés puis interrogeables.</p>
        </div>
        <button className="btn btn-primary" onClick={() => inputRef.current?.click()}><IconUpload size={16} /> Importer</button>
      </div>

      <div className="stats">
        <div className="card stat"><div className="stat-value">{stats.total}</div><div className="stat-label">Documents</div></div>
        <div className="card stat"><div className="stat-value" style={{ color: "var(--ok)" }}>{stats.ready}</div><div className="stat-label">Prêts</div></div>
        <div className="card stat"><div className="stat-value" style={{ color: "var(--info)" }}>{stats.busy}</div><div className="stat-label">En cours</div></div>
        <div className="card stat"><div className="stat-value">{stats.pages}</div><div className="stat-label">Pages indexées</div></div>
      </div>

      <div
        className={`dropzone ${over ? "over" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handleFiles(e.dataTransfer.files); }}
        role="button" tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
      >
        <div className="dropzone-icon"><IconUpload size={22} /></div>
        <div>
          <strong>Glissez-déposez vos fichiers ici</strong>
          <div className="muted">ou cliquez pour parcourir · PDF, TXT · {maxUploadBytes ? formatBytes(maxUploadBytes) : "50 Mo"} max · plusieurs fichiers acceptés</div>
        </div>
        <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden
          onChange={(e) => { handleFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {tasks.length > 0 && (
        <div className="uploads">
          {tasks.map((t) => (
            <div key={t.id} className="card upload-row">
              <div style={{ minWidth: 0 }}>
                <div className="name">{t.name}</div>
                <div className="stage">
                  {t.phase === "uploading" && `Envoi… ${Math.round((t.progress / 0.4) * 100)} % · ${formatBytes(t.size)}`}
                  {t.phase === "processing" && t.stage}
                  {t.phase === "done" && <span style={{ color: "var(--ok)" }}>Indexé et prêt à être interrogé</span>}
                  {t.phase === "failed" && <span style={{ color: "var(--danger)" }}>{t.error}</span>}
                </div>
              </div>
              <div className="progress-col">
                {t.phase !== "failed" && <div className="progress"><span style={{ width: `${Math.round(t.progress * 100)}%` }} /></div>}
              </div>
              <div>
                {t.phase === "done" && <span style={{ color: "var(--ok)" }}><IconCheck /></span>}
                {(t.phase === "uploading" || t.phase === "processing") && <span className="spinner" style={{ color: "var(--accent)" }} />}
                {(t.phase === "failed" || t.phase === "done") && (
                  <button className="icon-btn" aria-label="Retirer" onClick={() => setTasks((all) => all.filter((x) => x.id !== t.id))}>
                    <IconX size={14} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="toolbar">
        <div style={{ position: "relative", flex: "1 1 220px", maxWidth: 320 }}>
          <span style={{ position: "absolute", left: 11, top: 11, color: "var(--text-faint)" }}><IconSearch size={16} /></span>
          <input className="input" style={{ paddingLeft: 34 }} placeholder="Rechercher un document…"
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {(["all", "ready", "processing", "failed"] as const).map((f) => (
          <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>
            {{ all: "Tous", ready: "Prêts", processing: "En cours", failed: "Échecs" }[f]}
          </button>
        ))}
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={() => refresh()}>
          <IconRefresh size={15} /> Actualiser
        </button>
      </div>

      <div className="card doc-list">
        {visible.length > 0 && (
          <div className="doc-row head">
            <span />
            <span>Nom</span>
            <span>Statut</span>
            <span className="hide-md">Pages</span>
            <span className="hide-md">Taille</span>
            <span className="hide-md">Importé le</span>
            <span />
          </div>
        )}
        {visible.map((d) => {
          const ext = d.mime_type === "application/pdf" ? "pdf" : "txt";
          return (
            <div key={d.id} className="doc-row">
              <div className={`doc-icon ${ext}`}>{ext.toUpperCase()}</div>
              <div className="doc-name">
                <button onClick={() => onOpen({ documentId: d.id })} title={d.filename}>{d.filename}</button>
              </div>
              <div><StatusBadge status={d.status} /></div>
              <div className="hide-md muted">{d.page_count ?? "–"}</div>
              <div className="hide-md muted">{formatBytes(d.size_bytes)}</div>
              <div className="hide-md muted" style={{ fontSize: 12.5 }}>{formatDate(d.created_at)}</div>
              <div className="doc-actions">
                <button className="icon-btn" title="Ouvrir" aria-label="Ouvrir" disabled={d.status !== "ready"}
                  onClick={() => onOpen({ documentId: d.id })}><IconEye size={16} /></button>
                <button className="icon-btn" title="Réindexer" aria-label="Réindexer"
                  disabled={d.status !== "ready" && d.status !== "failed"} onClick={() => reindex(d)}><IconRefresh size={16} /></button>
                <button className="icon-btn btn-danger" title="Supprimer" aria-label="Supprimer"
                  disabled={d.status === "deleting"} onClick={() => remove(d)}><IconTrash size={16} /></button>
              </div>
            </div>
          );
        })}
        {loaded && visible.length === 0 && (
          <div className="empty">
            <div className="empty-icon"><IconFiles size={26} /></div>
            <h3>{docs.length === 0 ? "Aucun document pour l'instant" : "Aucun résultat"}</h3>
            <p>{docs.length === 0 ? "Importez un premier PDF pour commencer à poser des questions." : "Modifiez la recherche ou le filtre."}</p>
          </div>
        )}
      </div>
    </div>
  );
}
