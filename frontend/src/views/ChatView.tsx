import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api, ApiError, describeError, pageLabel,
  type ChatMessage, type Citation, type Conversation, type DocumentSummary, type QueryResponse,
} from "../api";
import type { ViewerTarget } from "../components/DocumentViewer";
import { IconAlert, IconClock, IconCpu, IconFiles, IconLogo, IconSend, IconSliders } from "../components/Icons";
import { useI18n } from "../i18n";

/** One line in the thread: a saved message, or one still being answered. */
interface Turn {
  id: string;
  question: string;
  response?: QueryResponse;
  content?: string;
  error?: { code: string; message: string };
  pending?: boolean;
  fresh?: boolean; // just answered: reveal it progressively instead of dropping it in at once
  scopeLabel: string;
}

function turnsFromMessages(messages: ChatMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === "user") turns.push({ id: m.id, question: m.content, scopeLabel: "" });
    else if (turns.length) Object.assign(turns[turns.length - 1], { id: m.id, response: m.response ?? undefined, content: m.content });
  }
  return turns;
}

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

export function ChatView({
  conversationId, docs, docsLoaded, initialQuestion, onConsumedInitial, onOpenSource, onGoDocuments,
  onConversation, onUsage, onAuthError,
}: {
  conversationId: string | null;
  docs: DocumentSummary[];
  docsLoaded: boolean;
  initialQuestion: string | null;
  onConsumedInitial: () => void;
  onOpenSource: (t: ViewerTarget) => void;
  onGoDocuments: () => void;
  onConversation: (c: Conversation) => void;
  onUsage: () => void;
  onAuthError: (e: unknown) => boolean;
}) {
  const { t } = useI18n();
  const [convId, setConvId] = useState(conversationId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(conversationId !== null);
  const [input, setInput] = useState("");
  const [debug, setDebug] = useState(false);
  const [scope, setScope] = useState<string[]>([]); // empty = all documents
  const [showOptions, setShowOptions] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const sending = turns.some((x) => x.pending);

  // Open an existing chat: load its messages and remembered scope.
  // Only on mount: the parent restarts this view (new key) to switch chats, and a chat created here
  // must not be reloaded over the answer we are still showing.
  const openedId = useRef(conversationId);
  useEffect(() => {
    const id = openedId.current;
    if (!id) return;
    let cancelled = false;
    api.getConversation(id)
      .then(({ conversation, messages }) => {
        if (cancelled) return;
        setTurns(turnsFromMessages(messages));
        setScope(conversation.document_ids ?? []);
      })
      .catch((e) => { if (!cancelled) onAuthError(e); })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: reducedMotion() ? "auto" : "smooth" });
  }, [turns]);

  // Drop scoped documents that no longer exist / aren't ready.
  useEffect(() => {
    setScope((s) => (docsLoaded ? s.filter((id) => docs.some((d) => d.id === id)) : s));
  }, [docs, docsLoaded]);

  const scopeLabel = scope.length === 0 ? t("chat.scope_all")
    : t(scope.length === 1 ? "chat.scope_n_one" : "chat.scope_n_many", { n: scope.length });

  async function ask(text: string) {
    const question = text.trim();
    if (!question || sending) return;
    const id = `tmp-${Date.now()}`;
    setInput("");
    if (textRef.current) textRef.current.style.height = "auto";
    setTurns((all) => [...all, { id, question, pending: true, scopeLabel }]);
    try {
      let cid = convId;
      if (!cid) {
        const created = await api.createConversation({ document_ids: scope.length ? scope : null });
        cid = created.id;
        setConvId(cid);
        onConversation(created);
      } else {
        await api.updateConversation(cid, scope.length ? { document_ids: scope } : { clear_scope: true });
      }
      const exchange = await api.sendMessage(cid, question, debug);
      onConversation(exchange.conversation); // the title appears after the first question
      setTurns((all) => all.map((x) => x.id === id
        ? { ...x, id: exchange.assistant_message.id, pending: false, fresh: true,
            response: exchange.assistant_message.response ?? undefined, content: exchange.assistant_message.content }
        : x));
      onUsage();
    } catch (e) {
      if (onAuthError(e)) return;
      const code = e instanceof ApiError ? e.code : "error";
      setTurns((all) => all.map((x) => (x.id === id ? { ...x, pending: false, error: { code, message: describeError(e) } } : x)));
      onUsage();
    }
    textRef.current?.focus();
  }

  // A question handed over from the Documents page ("ask this question").
  const askedInitial = useRef(false);
  useEffect(() => {
    if (initialQuestion && !askedInitial.current && !loading) {
      askedInitial.current = true;
      onConsumedInitial();
      ask(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion, loading]);

  const suggestions = useMemo(() => {
    const fromDocs = [...new Set(docs.flatMap((d) => d.suggested_questions.slice(0, 2)))].slice(0, 4);
    return fromDocs.length ? fromDocs : [t("chat.sugg_1"), t("chat.sugg_2"), t("chat.sugg_3")];
  }, [docs, t]);

  const isNew = turns.length === 0 && !loading;

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {isNew && (
            <div className="greeting rise">
              <div className="msg-ai">
                <div className="avatar"><IconLogo size={18} /></div>
                <div className="card answer-card greeting-card">
                  <div className="greeting-title">{t("chat.greeting_title")}</div>
                  <div className="answer-text">{t("chat.greeting_text")}</div>
                </div>
              </div>
              {docsLoaded && docs.length === 0 ? (
                <button className="btn btn-primary" style={{ marginTop: 14 }} onClick={onGoDocuments}>
                  <IconFiles size={16} /> {t("chat.import_first")}
                </button>
              ) : (
                <>
                  <div className="faint try-asking">{t("chat.try_asking")}</div>
                  <div className="suggestions">
                    {suggestions.map((s) => (
                      <button key={s} className="suggestion" onClick={() => ask(s)}>{s}</button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          {loading && <div className="thinking"><span className="spinner" /> {t("common.loading")}</div>}

          {turns.map((turn) => (
            <div key={turn.id} className="turn">
              <div className="msg-user">{turn.question}</div>
              <div className="msg-ai">
                <div className="avatar"><IconLogo size={18} /></div>
                <div style={{ minWidth: 0 }}>
                  {turn.pending && <Thinking scopeLabel={turn.scopeLabel || scopeLabel} />}
                  {turn.error && <ErrorCard code={turn.error.code} message={turn.error.message} />}
                  {turn.response && <AnswerCard r={turn.response} fallback={turn.content} animate={!!turn.fresh} onOpen={onOpenSource} />}
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
            placeholder={docs.length ? t("chat.placeholder") : t("chat.placeholder_empty")}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(input); }
            }}
            aria-label={t("chat.placeholder")}
            maxLength={2000}
          />
          <div className="composer-bar">
            <div style={{ position: "relative" }}>
              <button type="button" className={`chip ${showOptions ? "on" : ""}`} onClick={() => setShowOptions((v) => !v)}>
                <IconSliders size={14} /> {scopeLabel}{debug ? " · debug" : ""}
              </button>
              {showOptions && (
                <OptionsPopover docs={docs} scope={scope} setScope={setScope} debug={debug} setDebug={setDebug}
                  onClose={() => setShowOptions(false)} />
              )}
            </div>
            <div className="spacer" />
            <button className="btn btn-primary" disabled={!input.trim() || sending} aria-label={t("chat.send")}>
              <IconSend size={16} /> {t("chat.send")}
            </button>
          </div>
        </form>
        <div className="composer-hint">{t("chat.hint")}</div>
      </div>
    </div>
  );
}

/** Shows what the assistant is doing, so waiting feels like progress. */
function Thinking({ scopeLabel }: { scopeLabel: string }) {
  const { t } = useI18n();
  const [writing, setWriting] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setWriting(true), 1300);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div className="card thinking">
      <span className="dots"><span /><span /><span /></span>
      {writing ? t("chat.step_write") : t("chat.step_search", { scope: scopeLabel.toLowerCase() })}
    </div>
  );
}

function OptionsPopover(props: {
  docs: DocumentSummary[]; scope: string[]; setScope: (s: string[]) => void;
  debug: boolean; setDebug: (b: boolean) => void; onClose: () => void;
}) {
  const { t } = useI18n();
  const { docs, scope, setScope, debug, setDebug, onClose } = props;
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
        <div className="label">{t("chat.scope_title")}</div>
        <div className="scope-list">
          <label className="check">
            <input type="checkbox" checked={scope.length === 0} onChange={() => setScope([])} /> {t("chat.scope_all")}
          </label>
          {docs.map((d) => (
            <label key={d.id} className="check" title={d.filename}>
              <input type="checkbox" checked={scope.includes(d.id)} onChange={() => toggle(d.id)} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.filename}</span>
            </label>
          ))}
          {docs.length === 0 && <span className="faint" style={{ fontSize: 12.5 }}>{t("chat.scope_none")}</span>}
        </div>
      </div>
      <div className="toggle">
        <span>{t("chat.debug")} <span className="faint">{t("chat.debug_hint")}</span></span>
        <button type="button" className={`switch ${debug ? "on" : ""}`} aria-pressed={debug} aria-label={t("chat.debug")}
          onClick={() => setDebug(!debug)} />
      </div>
    </div>
  );
}

/** Split an answer into words and [S1] markers, then turn markers into clickable citation chips. */
function renderAnswer(
  text: string, shown: number, byMarker: Map<string, Citation>, open: (c: Citation) => void, droppedTitle: string,
): ReactNode[] {
  const tokens = text.split(/(\[S\d+\]|\s+)/g).filter((x) => x !== "");
  return tokens.slice(0, shown).map((part, i) => {
    const m = /^\[(S\d+)\]$/.exec(part);
    if (!m) return part;
    const c = byMarker.get(m[1]);
    if (!c) return <span key={i} className="cite dropped" title={droppedTitle}>{m[1].slice(1)}</span>;
    return (
      <button key={i} className="cite" onClick={() => open(c)} title={`${c.filename} · ${pageLabel(c.page_start, c.page_end)}`}>
        {m[1].slice(1)}
      </button>
    );
  });
}

/** Reveals a fresh answer quickly and smoothly (at most ~1.6 s), so it feels alive rather than abrupt. */
function useReveal(total: number, animate: boolean): number {
  const [shown, setShown] = useState(animate && !reducedMotion() ? 0 : total);
  useEffect(() => {
    if (!animate || reducedMotion() || total === 0) { setShown(total); return; }
    const step = Math.max(1, Math.ceil(total / 50)); // ~50 ticks of 30 ms
    const timer = setInterval(() => setShown((n) => {
      if (n + step >= total) { clearInterval(timer); return total; }
      return n + step;
    }), 30);
    return () => clearInterval(timer);
  }, [total, animate]);
  return shown;
}

function AnswerCard({
  r, fallback, animate, onOpen,
}: { r: QueryResponse; fallback?: string; animate: boolean; onOpen: (t: ViewerTarget) => void }) {
  const { t } = useI18n();
  const byMarker = useMemo(() => new Map(r.citations.map((c) => [c.marker, c])), [r.citations]);
  const open = (c: Citation) =>
    onOpen({ documentId: c.document_id, page: c.page_start, pageEnd: c.page_end, quote: c.quote, marker: c.marker });
  const sources = [...byMarker.values()];
  const best = Math.max(...sources.map((c) => c.score), 0.0001);

  const text = r.answer ?? "";
  const tokenCount = useMemo(() => text.split(/(\[S\d+\]|\s+)/g).filter((x) => x !== "").length, [text]);
  const shown = useReveal(tokenCount, animate && !r.abstained);
  const done = shown >= tokenCount;

  if (r.abstained) {
    const friendly = r.abstention_message || fallback;
    return (
      <div className={`card answer-card ${animate ? "rise" : ""} abstain`}>
        <div className="abstain-head"><IconAlert size={18} /> {t("chat.cant_answer")}</div>
        <div>{friendly || t(`abstain.${r.abstention_reason ?? "no_relevant_evidence"}` as never)}</div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>{t("chat.abstain_hint")}</div>
        <Meta r={r} />
        {r.diagnostics && <Debug r={r} />}
      </div>
    );
  }

  const plain = r.answer_type === "assistant" || r.answer_type === "smalltalk";
  return (
    <div className={`card answer-card ${animate ? "rise" : ""}`}>
      <div className="answer-text">{renderAnswer(text, shown, byMarker, open, t("chat.dropped_cite"))}</div>
      {done && (
        <div className={animate ? "fade-in" : ""}>
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
                  <div className="relevance" title={`score ${c.score.toFixed(3)}`}>
                    <span style={{ width: `${Math.max(8, (c.score / best) * 100)}%` }} />
                  </div>
                </button>
              ))}
            </div>
          )}
          {!plain && sources.length === 0 && <div className="faint" style={{ fontSize: 12.5, marginTop: 10 }}>{t("chat.no_source")}</div>}
          {r.standalone_question && <div className="faint rewrite">{t("chat.reformulated", { q: r.standalone_question })}</div>}
          <Meta r={r} />
          {r.diagnostics && <Debug r={r} />}
        </div>
      )}
    </div>
  );
}

function Meta({ r }: { r: QueryResponse }) {
  const { t } = useI18n();
  return (
    <div className="answer-meta">
      <span title={t("chat.total_time")}><IconClock size={13} /> {((r.latency_ms.total ?? 0) / 1000).toFixed(2)} s</span>
      <span>{t("chat.search_gen", { a: r.latency_ms.retrieval ?? 0, b: r.latency_ms.llm ?? 0 })}</span>
      {r.usage.input_tokens + r.usage.output_tokens > 0 && (
        <span>{t("chat.tokens", { a: r.usage.input_tokens, b: r.usage.output_tokens })}</span>
      )}
      <span title={`Embeddings: ${r.model.embedder} · prompt ${r.model.prompt_version}`}>
        <IconCpu size={13} /> {r.model.llm ?? t("chat.no_llm")}
      </span>
    </div>
  );
}

function Debug({ r }: { r: QueryResponse }) {
  const { t } = useI18n();
  const d = r.diagnostics!;
  return (
    <details className="debug">
      <summary>
        {t("chat.debug_summary", { n: d.dense.length, calls: d.llm_calls })}
        {d.citations_dropped > 0 && t("chat.debug_dropped", { n: d.citations_dropped })}
      </summary>
      <table className="debug-table">
        <thead>
          <tr><th>#</th><th>Document</th><th>Pages</th><th>Score</th><th>Context</th></tr>
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
  const { t } = useI18n();
  return (
    <div className="card answer-card error-card">
      <div className="abstain-head"><IconAlert size={18} /> {t("chat.request_failed")}</div>
      <div>{message}</div>
      <div className="faint mono" style={{ fontSize: 12, marginTop: 6 }}>{code}</div>
    </div>
  );
}
