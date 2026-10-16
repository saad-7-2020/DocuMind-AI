import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, describeError, pageLabel, type Citation, type DocumentSummary, type QueryResponse } from "../api";
import type { ViewerTarget } from "../components/DocumentViewer";
import { IconAlert, IconClock, IconCpu, IconFiles, IconLogo, IconSend, IconSliders, IconSparkles, IconTrash } from "../components/Icons";

interface Turn {
  id: string;
  question: string;
  scopeLabel: string;
  response?: QueryResponse;
  error?: { code: string; message: string };
  pending?: boolean;
}

const STORAGE = "documind.chat";
const SUGGESTIONS = [
  "Quel est le préavis de résiliation du contrat ?",
  "Résume les obligations principales du prestataire.",
  "Quel est le prix annuel et comment est-il révisé ?",
  "Quelle est la durée du contrat ?",
];
const ABSTAIN_REASONS: Record<string, string> = {
  no_relevant_evidence: "Aucun passage pertinent n'a été trouvé dans vos documents.",
  model_insufficient_evidence: "Les passages trouvés ne suffisent pas pour répondre avec certitude.",
  no_valid_citations: "La réponse ne s'appuyait sur aucune source vérifiable.",
};

function loadTurns(): Turn[] {
  try {
    const raw = localStorage.getItem(STORAGE);
    return raw ? (JSON.parse(raw) as Turn[]).filter((t) => !t.pending) : [];
  } catch {
    return [];
  }
}

export function ChatView({
  docs, docsLoaded, onOpenSource, onGoDocuments,
}: {
  docs: DocumentSummary[];
  docsLoaded: boolean;
  onOpenSource: (t: ViewerTarget) => void;
  onGoDocuments: () => void;
}) {
  const [turns, setTurns] = useState<Turn[]>(loadTurns);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(6);
  const [debug, setDebug] = useState(false);
  const [scope, setScope] = useState<string[]>([]); // empty = all documents
  const [showOptions, setShowOptions] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const sending = turns.some((t) => t.pending);

  useEffect(() => {
    try { localStorage.setItem(STORAGE, JSON.stringify(turns.slice(-50))); } catch { /* ignore */ }
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);

  // Drop scoped documents that no longer exist / aren't ready.
  useEffect(() => {
    setScope((s) => s.filter((id) => docs.some((d) => d.id === id)));
  }, [docs]);

  const scopeLabel = scope.length === 0 ? "Tous les documents" : `${scope.length} document${scope.length > 1 ? "s" : ""}`;

  async function ask(text: string) {
    const question = text.trim();
    if (!question || sending) return;
    const id = `${Date.now()}`;
    setInput("");
    setTurns((t) => [...t, { id, question, scopeLabel, pending: true }]);
    try {
      const response = await api.query({
        question,
        filters: { document_ids: scope.length ? scope : null },
        retrieval: { mode: "dense", top_k: topK },
        debug,
      });
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, pending: false, response } : x)));
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "error";
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, pending: false, error: { code, message: describeError(e) } } : x)));
    }
    textRef.current?.focus();
  }

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {turns.length === 0 && (
            <div className="empty" style={{ paddingTop: "8vh" }}>
              <div className="empty-icon" style={{ background: "var(--grad)", color: "#fff" }}><IconSparkles size={26} /></div>
              <h3 style={{ fontSize: 22 }}>Que voulez-vous savoir ?</h3>
              <p>Chaque réponse s'appuie uniquement sur vos documents, avec les pages citées.</p>
              {docsLoaded && docs.length === 0 ? (
                <button className="btn btn-primary" style={{ marginTop: 10 }} onClick={onGoDocuments}>
                  <IconFiles size={16} /> Importer un premier document
                </button>
              ) : (
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="suggestion" onClick={() => ask(s)}>{s}</button>
                  ))}
                </div>
              )}
            </div>
          )}

          {turns.map((t) => (
            <div key={t.id} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="msg-user">{t.question}</div>
              <div className="msg-ai">
                <div className="avatar"><IconLogo size={18} /></div>
                <div style={{ minWidth: 0 }}>
                  {t.pending && (
                    <div className="card thinking">
                      <span className="dots"><span /><span /><span /></span>
                      Recherche dans {t.scopeLabel.toLowerCase()} puis rédaction…
                    </div>
                  )}
                  {t.error && <ErrorCard code={t.error.code} message={t.error.message} />}
                  {t.response && <AnswerCard r={t.response} onOpen={onOpenSource} />}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="composer-wrap">
        <form className="card composer" onSubmit={(e) => { e.preventDefault(); ask(input); }}>
          <textarea
            ref={textRef}
            rows={1}
            placeholder={docs.length ? "Posez une question sur vos documents…" : "Importez d'abord un document…"}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); }
            }}
            aria-label="Question"
            maxLength={2000}
          />
          <div className="composer-bar">
            <div style={{ position: "relative" }}>
              <button type="button" className={`chip ${showOptions ? "on" : ""}`} onClick={() => setShowOptions((v) => !v)}>
                <IconSliders size={14} /> {scopeLabel} · top {topK}{debug ? " · debug" : ""}
              </button>
              {showOptions && (
                <OptionsPopover docs={docs} scope={scope} setScope={setScope} topK={topK} setTopK={setTopK}
                  debug={debug} setDebug={setDebug} onClose={() => setShowOptions(false)} />
              )}
            </div>
            <div className="spacer" />
            {turns.length > 0 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTurns([])} disabled={sending}>
                <IconTrash size={14} /> Effacer
              </button>
            )}
            <button className="btn btn-primary" disabled={!input.trim() || sending} aria-label="Envoyer">
              <IconSend size={16} /> Envoyer
            </button>
          </div>
        </form>
        <div className="composer-hint">
          Entrée pour envoyer · Maj+Entrée pour un saut de ligne · chaque question est traitée indépendamment
        </div>
      </div>
    </div>
  );
}

function OptionsPopover(props: {
  docs: DocumentSummary[]; scope: string[]; setScope: (s: string[]) => void;
  topK: number; setTopK: (n: number) => void; debug: boolean; setDebug: (b: boolean) => void; onClose: () => void;
}) {
  const { docs, scope, setScope, topK, setTopK, debug, setDebug, onClose } = props;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest(".chip")) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);
  const toggle = (id: string) => setScope(scope.includes(id) ? scope.filter((x) => x !== id) : [...scope, id]);

  return (
    <div className="card popover" ref={ref}>
      <div>
        <div className="label">Périmètre de recherche</div>
        <div className="scope-list">
          <label className="check">
            <input type="checkbox" checked={scope.length === 0} onChange={() => setScope([])} /> Tous les documents
          </label>
          {docs.map((d) => (
            <label key={d.id} className="check" title={d.filename}>
              <input type="checkbox" checked={scope.includes(d.id)} onChange={() => toggle(d.id)} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.filename}</span>
            </label>
          ))}
          {docs.length === 0 && <span className="faint" style={{ fontSize: 12.5 }}>Aucun document prêt.</span>}
        </div>
      </div>
      <div>
        <div className="label">Passages envoyés au modèle (top-k) : {topK}</div>
        <div className="range-row">
          <span className="faint">1</span>
          <input type="range" min={1} max={20} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
          <span className="faint">20</span>
        </div>
      </div>
      <div className="toggle">
        <span>Mode debug <span className="faint">(classement des passages)</span></span>
        <button type="button" className={`switch ${debug ? "on" : ""}`} aria-pressed={debug} aria-label="Mode debug"
          onClick={() => setDebug(!debug)} />
      </div>
    </div>
  );
}

/** Render the answer text, turning [S1] markers into clickable citation chips. */
function renderAnswer(text: string, byMarker: Map<string, Citation>, open: (c: Citation) => void): ReactNode[] {
  return text.split(/(\[S\d+\])/g).map((part, i) => {
    const m = /^\[(S\d+)\]$/.exec(part);
    if (!m) return part;
    const c = byMarker.get(m[1]);
    if (!c) {
      return <span key={i} className="cite dropped" title="Citation rejetée : source absente du contexte">{m[1].slice(1)}</span>;
    }
    return (
      <button key={i} className="cite" onClick={() => open(c)} title={`${c.filename} · ${pageLabel(c.page_start, c.page_end)}`}>
        {m[1].slice(1)}
      </button>
    );
  });
}

function AnswerCard({ r, onOpen }: { r: QueryResponse; onOpen: (t: ViewerTarget) => void }) {
  const byMarker = useMemo(() => new Map(r.citations.map((c) => [c.marker, c])), [r.citations]);
  const open = (c: Citation) =>
    onOpen({ documentId: c.document_id, page: c.page_start, pageEnd: c.page_end, quote: c.quote, marker: c.marker });
  // Deduplicate source cards by marker; scale relevance against the best score in this answer.
  const sources = [...byMarker.values()];
  const best = Math.max(...sources.map((c) => c.score), 0.0001);

  if (r.abstained) {
    return (
      <div className="card answer-card abstain">
        <div className="abstain-head"><IconAlert size={18} /> Je ne peux pas répondre avec certitude</div>
        <div className="muted">{ABSTAIN_REASONS[r.abstention_reason ?? ""] ?? r.abstention_reason}</div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>
          Plutôt que d'inventer, DocuMind préfère s'abstenir. Essayez de reformuler, ou vérifiez que le bon document est importé.
        </div>
        <Meta r={r} />
        {r.diagnostics && <Debug r={r} />}
      </div>
    );
  }

  return (
    <div className="card answer-card">
      <div className="answer-text">{renderAnswer(r.answer ?? "", byMarker, open)}</div>
      {sources.length > 0 && (
        <div className="sources">
          {sources.map((c) => (
            <button key={c.marker} className="source" onClick={() => open(c)}>
              <div className="source-head">
                <span className="cite" style={{ margin: 0 }}>{c.marker.slice(1)}</span>
                <span className="file">{c.filename}</span>
                <span className="faint" style={{ marginLeft: "auto", whiteSpace: "nowrap" }}>{pageLabel(c.page_start, c.page_end)}</span>
              </div>
              <div className="source-quote">« {c.quote} »</div>
              <div className="relevance" title={`similarité ${c.score.toFixed(3)}`}>
                <span style={{ width: `${Math.max(8, (c.score / best) * 100)}%` }} />
              </div>
            </button>
          ))}
        </div>
      )}
      {sources.length === 0 && (
        <div className="faint" style={{ fontSize: 12.5, marginTop: 10 }}>⚠ Réponse sans source citée : à vérifier.</div>
      )}
      <Meta r={r} />
      {r.diagnostics && <Debug r={r} />}
    </div>
  );
}

function Meta({ r }: { r: QueryResponse }) {
  return (
    <div className="answer-meta">
      <span title="Temps total"><IconClock size={13} /> {(r.latency_ms.total / 1000).toFixed(2)} s</span>
      <span title="Recherche / génération">recherche {r.latency_ms.retrieval} ms · LLM {r.latency_ms.llm} ms</span>
      {r.usage.input_tokens + r.usage.output_tokens > 0 && (
        <span title="Jetons entrée / sortie">{r.usage.input_tokens} → {r.usage.output_tokens} jetons</span>
      )}
      <span title={`Embeddings : ${r.model.embedder} · prompt ${r.model.prompt_version}`}>
        <IconCpu size={13} /> {r.model.llm ?? "aucun appel LLM"}
      </span>
    </div>
  );
}

function Debug({ r }: { r: QueryResponse }) {
  const d = r.diagnostics!;
  return (
    <details className="debug">
      <summary>
        Diagnostic de recherche · {d.dense.length} passages classés · {d.llm_calls} appel(s) LLM
        {d.citations_dropped > 0 && ` · ${d.citations_dropped} citation(s) rejetée(s)`}
      </summary>
      <table className="debug-table">
        <thead>
          <tr><th>#</th><th>Document</th><th>Pages</th><th>Similarité</th><th>Dans le contexte</th></tr>
        </thead>
        <tbody>
          {d.dense.map((c) => (
            <tr key={c.chunk_id} className={c.in_context ? "in-context" : ""}>
              <td>{c.rank}</td>
              <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.filename}</td>
              <td>{pageLabel(c.page_start, c.page_end)}</td>
              <td className="mono">{c.score.toFixed(3)}</td>
              <td>{c.in_context ? "✓" : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function ErrorCard({ code, message }: { code: string; message: string }) {
  return (
    <div className="card answer-card error-card">
      <div className="abstain-head"><IconAlert size={18} /> La requête a échoué</div>
      <div>{message}</div>
      <div className="faint mono" style={{ fontSize: 12, marginTop: 6 }}>{code}</div>
    </div>
  );
}
