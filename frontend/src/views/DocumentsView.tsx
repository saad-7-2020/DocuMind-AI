import { useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, describeError, formatBytes, formatDate, type DocStatus, type DocumentSummary, type Me,
} from "../api";
import type { ViewerTarget } from "../components/DocumentViewer";
import {
  IconCheck, IconChat, IconEye, IconFiles, IconRefresh, IconSearch, IconSparkles, IconTrash, IconUpload, IconX,
} from "../components/Icons";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toasts";
import { useI18n } from "../i18n";

const ACCEPT = ".pdf,.txt,application/pdf,text/plain";

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
  docs, loaded, refresh, onOpen, maxUploadBytes, me, onAsk, onChanged,
}: {
  docs: DocumentSummary[];
  loaded: boolean;
  refresh: () => Promise<void>;
  onOpen: (t: ViewerTarget) => void;
  maxUploadBytes?: number;
  me: Me | null;
  onAsk: (question: string) => void;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const [over, setOver] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | DocStatus>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- fresh list on every visit

  const update = (id: string, patch: Partial<UploadTask>) =>
    setTasks((all) => all.map((x) => (x.id === id ? { ...x, ...patch } : x)));

  async function uploadOne(file: File) {
    if (maxUploadBytes && file.size > maxUploadBytes) {
      toast("error", t("docs.too_big", { name: file.name, size: formatBytes(file.size), max: formatBytes(maxUploadBytes) }));
      return;
    }
    const id = `${file.name}-${Date.now()}-${Math.random()}`;
    setTasks((all) => [{ id, name: file.name, size: file.size, phase: "uploading", progress: 0 }, ...all]);
    try {
      // Phase 1: bytes over the wire (0 → 40 %).
      const accepted = await api.uploadDocument(file, (f) => update(id, { progress: f * 0.4 }));
      update(id, { phase: "processing", progress: 0.4, stage: t("upload.queued") });
      refresh();
      // Phase 2: the indexing pipeline, reported through the job (40 → 100 %).
      for (let i = 0; i < 900; i++) {
        await sleep(1000);
        const job = await api.getJob(accepted.job_id);
        const stageKey = `stage.${job.stage ?? ""}` as const;
        update(id, {
          progress: 0.4 + 0.6 * job.progress,
          stage: job.status === "queued" && job.attempts > 0
            ? t("upload.retry", { n: job.attempts })
            : job.stage ? t(stageKey as never) : t("upload.queued"),
        });
        if (job.status === "succeeded") {
          update(id, { phase: "done", progress: 1, stage: t("upload.indexed") });
          toast("success", t("docs.ready_toast", { name: file.name }));
          break;
        }
        if (job.status === "failed") {
          throw new ApiError(422, job.error_code ?? "extraction_failed", t("upload.failed"));
        }
      }
    } catch (e) {
      update(id, { phase: "failed", error: describeError(e) });
      toast("error", `${file.name} : ${describeError(e)}`);
    } finally {
      refresh();
      onChanged();
    }
  }

  function handleFiles(list: FileList | null) {
    if (!list) return;
    Array.from(list).forEach(uploadOne);
  }

  async function remove(doc: DocumentSummary) {
    if (!confirm(t("docs.delete_confirm", { name: doc.filename }))) return;
    try {
      await api.deleteDocument(doc.id);
      toast("success", t("docs.delete_started"));
    } catch (e) {
      toast("error", describeError(e));
    }
    refresh();
    onChanged();
  }

  async function reindex(doc: DocumentSummary) {
    try {
      await api.reindexDocument(doc.id);
      toast("success", t("docs.reindex_started", { name: doc.filename }));
    } catch (e) {
      toast("error", describeError(e));
    }
    refresh();
  }

  async function redescribe(doc: DocumentSummary) {
    try {
      await api.describeDocument(doc.id);
      toast("success", t("docs.described"));
    } catch (e) {
      toast("error", describeError(e));
    }
    refresh();
    onChanged();
  }

  const toggle = (id: string) =>
    setExpanded((s) => { const n = new Set(s); if (!n.delete(id)) n.add(id); return n; });

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
          <h1 className="page-title">{t("docs.title")}</h1>
          <p className="page-subtitle">{t("docs.subtitle")}</p>
        </div>
        <div className="row">
          {me?.limits && <span className="badge neutral">{t("docs.quota", { used: me.usage.documents, max: me.limits.max_documents })}</span>}
          <button className="btn btn-primary" onClick={() => inputRef.current?.click()}><IconUpload size={16} /> {t("docs.import")}</button>
        </div>
      </div>

      <div className="stats">
        <div className="card stat"><div className="stat-value">{stats.total}</div><div className="stat-label">{t("docs.stat_total")}</div></div>
        <div className="card stat"><div className="stat-value" style={{ color: "var(--ok)" }}>{stats.ready}</div><div className="stat-label">{t("docs.stat_ready")}</div></div>
        <div className="card stat"><div className="stat-value" style={{ color: "var(--info)" }}>{stats.busy}</div><div className="stat-label">{t("docs.stat_busy")}</div></div>
        <div className="card stat"><div className="stat-value">{stats.pages}</div><div className="stat-label">{t("docs.stat_pages")}</div></div>
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
          <strong>{t("docs.drop")}</strong>
          <div className="muted">{t("docs.drop_hint", { max: maxUploadBytes ? formatBytes(maxUploadBytes) : "4 MB" })}</div>
        </div>
        <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden
          onChange={(e) => { handleFiles(e.target.files); e.target.value = ""; }} />
      </div>

      {tasks.length > 0 && (
        <div className="uploads">
          {tasks.map((x) => (
            <div key={x.id} className="card upload-row">
              <div style={{ minWidth: 0 }}>
                <div className="name">{x.name}</div>
                <div className="stage">
                  {x.phase === "uploading" && t("upload.sending", { p: Math.round((x.progress / 0.4) * 100), size: formatBytes(x.size) })}
                  {x.phase === "processing" && x.stage}
                  {x.phase === "done" && <span style={{ color: "var(--ok)" }}>{t("upload.done")}</span>}
                  {x.phase === "failed" && <span style={{ color: "var(--danger)" }}>{x.error}</span>}
                </div>
              </div>
              <div className="progress-col">
                {x.phase !== "failed" && <div className="progress"><span style={{ width: `${Math.round(x.progress * 100)}%` }} /></div>}
              </div>
              <div>
                {x.phase === "done" && <span style={{ color: "var(--ok)" }}><IconCheck /></span>}
                {(x.phase === "uploading" || x.phase === "processing") && <span className="spinner" style={{ color: "var(--accent)" }} />}
                {(x.phase === "failed" || x.phase === "done") && (
                  <button className="icon-btn" aria-label={t("upload.remove")} onClick={() => setTasks((all) => all.filter((y) => y.id !== x.id))}>
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
          <input className="input" style={{ paddingLeft: 34 }} placeholder={t("docs.search")}
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {(["all", "ready", "processing", "failed"] as const).map((f) => (
          <button key={f} className={`chip ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>
            {t(`docs.f_${f}` as never)}
          </button>
        ))}
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={() => refresh()}>
          <IconRefresh size={15} /> {t("common.refresh")}
        </button>
      </div>

      <div className="card doc-list">
        {visible.length > 0 && (
          <div className="doc-row head">
            <span />
            <span>{t("docs.col_name")}</span>
            <span>{t("docs.col_status")}</span>
            <span className="hide-md">{t("docs.col_pages")}</span>
            <span className="hide-md">{t("docs.col_size")}</span>
            <span className="hide-md">{t("docs.col_date")}</span>
            <span />
          </div>
        )}
        {visible.map((d) => {
          const ext = d.mime_type === "application/pdf" ? "pdf" : "txt";
          const open = expanded.has(d.id) || (d.status === "ready" && !!d.summary && docs.length <= 3);
          return (
            <div key={d.id} className="doc-item">
              <div className="doc-row">
                <div className={`doc-icon ${ext}`}>{ext.toUpperCase()}</div>
                <div className="doc-name">
                  <button onClick={() => onOpen({ documentId: d.id })} title={d.filename}>{d.filename}</button>
                </div>
                <div><StatusBadge status={d.status} /></div>
                <div className="hide-md muted">{d.page_count ?? "–"}</div>
                <div className="hide-md muted">{formatBytes(d.size_bytes)}</div>
                <div className="hide-md muted" style={{ fontSize: 12.5 }}>{formatDate(d.created_at)}</div>
                <div className="doc-actions">
                  <button className="icon-btn" title={t("docs.open")} aria-label={t("docs.open")} disabled={d.status !== "ready"}
                    onClick={() => onOpen({ documentId: d.id })}><IconEye size={16} /></button>
                  <button className="icon-btn" title={t("docs.reindex")} aria-label={t("docs.reindex")}
                    disabled={d.status !== "ready" && d.status !== "failed"} onClick={() => reindex(d)}><IconRefresh size={16} /></button>
                  <button className="icon-btn btn-danger" title={t("docs.delete")} aria-label={t("docs.delete")}
                    disabled={d.status === "deleting"} onClick={() => remove(d)}><IconTrash size={16} /></button>
                </div>
              </div>

              {d.status === "ready" && (
                <div className="doc-desc">
                  {d.summary ? (
                    <>
                      <button className="link-btn" onClick={() => toggle(d.id)} aria-expanded={open}>
                        <IconSparkles size={13} /> {open ? t("docs.show_less") : t("docs.show_more")}
                      </button>
                      {open && (
                        <div className="doc-desc-body rise">
                          <p className="doc-summary">{d.summary}</p>
                          {d.keywords.length > 0 && (
                            <div className="keywords" aria-label={t("docs.keywords")}>
                              {d.keywords.map((k, i) => <span key={`${k}-${i}`} className="keyword">{k}</span>)}
                            </div>
                          )}
                          {d.suggested_questions.length > 0 && (
                            <div className="asks">
                              {d.suggested_questions.map((q) => (
                                <button key={q} className="ask-btn" onClick={() => onAsk(q)} title={t("docs.ask_this")}>
                                  <IconChat size={13} /> {q}
                                </button>
                              ))}
                            </div>
                          )}
                          <button className="link-btn faint" onClick={() => redescribe(d)}>
                            <IconRefresh size={12} /> {t("docs.describe")}
                          </button>
                        </div>
                      )}
                    </>
                  ) : (
                    <button className="link-btn faint" onClick={() => redescribe(d)}>
                      <IconSparkles size={13} /> {t("docs.no_description")} · {t("docs.describe")}
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {loaded && visible.length === 0 && (
          <div className="empty">
            <div className="empty-icon"><IconFiles size={26} /></div>
            <h3>{docs.length === 0 ? t("docs.empty_title") : t("docs.no_result")}</h3>
            <p>{docs.length === 0 ? t("docs.empty_text") : t("docs.no_result_text")}</p>
          </div>
        )}
      </div>
    </div>
  );
}
