// Side drawer that shows a document's metadata and the extracted text of a page,
// with the cited quote highlighted. This is how a user *verifies* a citation.
import { useEffect, useMemo, useState } from "react";
import { api, describeError, formatBytes, formatDate, type DocumentDetail, type Page } from "../api";
import { IconChevron, IconChevronLeft, IconX } from "./Icons";
import { StatusBadge } from "./StatusBadge";

export interface ViewerTarget {
  documentId: string;
  page?: number;
  pageEnd?: number;
  quote?: string;
  marker?: string;
}

/** Find the quote in the page text, tolerant to whitespace and case differences. */
function findQuote(text: string, quote: string): [number, number] | null {
  const q = quote.trim();
  if (q.length < 3) return null;
  const pattern = q
    .split(/\s+/)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("\\s+");
  const m = new RegExp(pattern, "i").exec(text);
  return m ? [m.index, m.index + m[0].length] : null;
}

export function DocumentViewer({ target, onClose }: { target: ViewerTarget; onClose: () => void }) {
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [pageNo, setPageNo] = useState(target.page ?? 1);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getDocument(target.documentId).then(setDoc).catch((e) => setError(describeError(e)));
  }, [target.documentId]);

  useEffect(() => {
    setPage(null);
    api.getPage(target.documentId, pageNo).then(setPage).catch((e) => setError(describeError(e)));
  }, [target.documentId, pageNo]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const highlighted = useMemo(() => {
    if (!page) return null;
    const span = target.quote ? findQuote(page.text, target.quote) : null;
    if (!span) return { parts: [page.text], found: false };
    return { parts: [page.text.slice(0, span[0]), page.text.slice(span[0], span[1]), page.text.slice(span[1])], found: true };
  }, [page, target.quote]);

  useEffect(() => {
    if (highlighted?.found) document.querySelector(".page-text mark")?.scrollIntoView({ block: "center" });
  }, [highlighted]);

  const total = doc?.page_count ?? 1;
  const inCitedRange = target.page !== undefined && pageNo >= target.page && pageNo <= (target.pageEnd ?? target.page);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Visionneuse de document">
        <div className="drawer-head">
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="faint" style={{ fontSize: 12, marginBottom: 2 }}>
              {target.marker ? `Source ${target.marker}` : "Document"}
            </div>
            <h2>{doc?.filename ?? "…"}</h2>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Fermer"><IconX /></button>
        </div>
        <div className="drawer-body">
          {error && <div className="card error-card" style={{ padding: 12, marginBottom: 12 }}>{error}</div>}
          {doc && (
            <div className="meta-grid">
              <div className="meta"><div className="k">Statut</div><div className="v"><StatusBadge status={doc.status} /></div></div>
              <div className="meta"><div className="k">Pages</div><div className="v">{doc.page_count ?? "–"}</div></div>
              <div className="meta"><div className="k">Chunks</div><div className="v">{doc.chunk_count}</div></div>
              <div className="meta"><div className="k">Taille</div><div className="v">{formatBytes(doc.size_bytes)}</div></div>
              <div className="meta"><div className="k">Langue</div><div className="v">{doc.language.toUpperCase()}</div></div>
              <div className="meta"><div className="k">Importé</div><div className="v" style={{ fontSize: 12.5 }}>{formatDate(doc.created_at)}</div></div>
            </div>
          )}

          {target.quote && (
            <div className="quote-box">
              « {target.quote} »
              {highlighted && !highlighted.found && inCitedRange && (
                <div className="faint" style={{ fontStyle: "normal", fontSize: 12, marginTop: 6 }}>
                  Citation non retrouvée mot pour mot sur cette page (la vérification stricte des citations arrive en phase 3).
                </div>
              )}
            </div>
          )}

          <div className="pager">
            <button className="icon-btn" disabled={pageNo <= 1} onClick={() => setPageNo((n) => n - 1)} aria-label="Page précédente"><IconChevronLeft /></button>
            <span>Page <strong>{pageNo}</strong> / {total}</span>
            <button className="icon-btn" disabled={pageNo >= total} onClick={() => setPageNo((n) => n + 1)} aria-label="Page suivante"><IconChevron /></button>
            {page && <span className="badge neutral" style={{ marginLeft: "auto" }}>{page.extraction_method}</span>}
          </div>

          <div className="page-text">
            {!page && !error && <span className="muted">Chargement…</span>}
            {highlighted && (highlighted.parts.length === 1 ? highlighted.parts[0] : (
              <>{highlighted.parts[0]}<mark>{highlighted.parts[1]}</mark>{highlighted.parts[2]}</>
            ))}
          </div>
        </div>
      </aside>
    </>
  );
}
