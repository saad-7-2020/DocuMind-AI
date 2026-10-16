// Typed client for the DocuMind API (docs/architecture.md §9).
// Types mirror backend/src/documind/api/schemas.py.

export type DocStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface DocumentSummary {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocStatus;
  page_count: number | null;
  created_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  title: string | null;
  language: string;
  ocr_page_count: number;
  chunk_count: number;
  error_code: string | null;
  updated_at: string;
}

export interface Page {
  page_number: number;
  text: string;
  extraction_method: string;
}

export interface Job {
  id: string;
  kind: "ingest" | "reindex" | "delete";
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string | null;
  progress: number;
  attempts: number;
  document_id: string | null;
  error_code: string | null;
}

export interface Citation {
  marker: string;
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  quote: string;
  score: number;
}

export interface RetrievedChunk {
  rank: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page_start: number;
  page_end: number;
  score: number;
  in_context: boolean;
}

export interface QueryResponse {
  query_id: string;
  answer: string | null;
  abstained: boolean;
  abstention_reason: string | null;
  citations: Citation[];
  usage: { input_tokens: number; output_tokens: number; cost_usd: number | null };
  latency_ms: Record<string, number>;
  model: { embedder: string; llm: string | null; prompt_version: string };
  diagnostics: { dense: RetrievedChunk[]; citations_dropped: number; llm_calls: number } | null;
}

export interface QueryRequest {
  question: string;
  filters?: { document_ids?: string[] | null };
  retrieval?: { mode?: "dense"; top_k?: number; rerank?: boolean };
  debug?: boolean;
}

export interface Health {
  status: string;
  database?: string;
  embedder?: string;
}

/** An RFC 9457 problem+json error from the API, or a network failure (status 0). */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public detail: string,
    public extra: Record<string, unknown> = {},
  ) {
    super(detail);
  }
}

const KEY_STORAGE = "documind.apiKey";

export function getApiKey(): string {
  try {
    return localStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(KEY_STORAGE, key);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable: the key lives for this tab only */
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const { status, code, title, detail, type: _t, request_id: _r, ...extra } = body ?? {};
    return new ApiError(status ?? res.status, code ?? "http_error", detail ?? title ?? res.statusText, extra);
  } catch {
    return new ApiError(res.status, "http_error", res.statusText || `HTTP ${res.status}`);
  }
}

async function request<T>(path: string, init: RequestInit = {}, key = getApiKey()): Promise<T> {
  const headers = new Headers(init.headers);
  if (key) headers.set("Authorization", `Bearer ${key}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "Impossible de joindre l'API. Est-elle démarrée ?");
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/health/ready"),

  /** Validate a key without storing it. */
  checkKey: (key: string) => request<{ items: DocumentSummary[] }>("/v1/documents?limit=1", {}, key),

  async listAllDocuments(max = 500): Promise<DocumentSummary[]> {
    const all: DocumentSummary[] = [];
    let cursor: string | null = null;
    do {
      const qs: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
      const page: { items: DocumentSummary[]; next_cursor: string | null } = await request(
        `/v1/documents?limit=100${qs}`,
      );
      all.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor && all.length < max);
    return all;
  },

  getDocument: (id: string) => request<DocumentDetail>(`/v1/documents/${id}`),
  getPage: (id: string, n: number) => request<Page>(`/v1/documents/${id}/pages/${n}`),
  deleteDocument: (id: string) => request<{ job_id: string }>(`/v1/documents/${id}`, { method: "DELETE" }),
  reindexDocument: (id: string) => request<{ job_id: string }>(`/v1/documents/${id}/reindex`, { method: "POST" }),
  getJob: (id: string) => request<Job>(`/v1/jobs/${id}`),
  query: (body: QueryRequest) => request<QueryResponse>("/v1/query", { method: "POST", body: JSON.stringify(body) }),

  /** Upload with byte-level progress (fetch can't report upload progress; XHR can). */
  uploadDocument(
    file: File,
    onProgress: (fraction: number) => void,
  ): Promise<{ document_id: string; job_id: string; status: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/v1/documents");
      const key = getApiKey();
      if (key) xhr.setRequestHeader("Authorization", `Bearer ${key}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError(0, "network_error", "Échec réseau pendant l'envoi."));
      xhr.onload = () => {
        let body: any = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* non-JSON error page */
        }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body);
        const { status, code, title, detail, type: _t, request_id: _r, ...extra } = body ?? {};
        reject(new ApiError(status ?? xhr.status, code ?? "http_error", detail ?? title ?? `HTTP ${xhr.status}`, extra));
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
};

// ── Formatting helpers ──────────────────────────────────

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  return `${(n / 1024 / 1024).toFixed(1)} Mo`;
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function pageLabel(start: number, end: number): string {
  return start === end ? `p. ${start}` : `pp. ${start}–${end}`;
}

export const ERROR_MESSAGES: Record<string, string> = {
  duplicate: "Ce document a déjà été importé.",
  unsupported_file_type: "Type de fichier non pris en charge (PDF ou TXT).",
  file_too_large: "Fichier trop volumineux.",
  empty_file: "Le fichier est vide.",
  pdf_encrypted: "PDF protégé par mot de passe.",
  too_many_pages: "Trop de pages.",
  no_text_found: "Aucun texte extractible (PDF scanné : l'OCR arrive en phase 3).",
  extraction_failed: "Le texte n'a pas pu être extrait.",
  unauthorized: "Clé API manquante ou invalide.",
  network_error: "Impossible de joindre l'API.",
  llm_timeout: "Le modèle de langage n'a pas répondu à temps.",
  llm_rate_limited: "Limite de requêtes Groq atteinte. Réessayez dans un instant.",
  llm_bad_output: "Le modèle a renvoyé une réponse mal formée.",
  llm_error: "Erreur du fournisseur LLM (vérifiez GROQ_API_KEY).",
};

export function describeError(e: unknown): string {
  if (e instanceof ApiError) return ERROR_MESSAGES[e.code] ?? e.detail;
  return e instanceof Error ? e.message : String(e);
}
