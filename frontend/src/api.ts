// Typed client for the DocuMind API (docs/architecture.md §9).
// Types mirror backend/src/documind/api/schemas.py.
import { locale, translate, type Key } from "./i18n";

export type DocStatus = "pending" | "processing" | "ready" | "failed" | "deleting";

export interface DocumentSummary {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  status: DocStatus;
  page_count: number | null;
  created_at: string;
  summary: string | null;
  keywords: string[];
  suggested_questions: string[];
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

export type AnswerType = "document" | "assistant" | "smalltalk" | "insufficient";

export interface QueryResponse {
  query_id: string;
  answer: string | null;
  answer_type: AnswerType;
  abstained: boolean;
  abstention_reason: string | null;
  abstention_message: string | null;
  standalone_question: string | null;
  citations: Citation[];
  usage: { input_tokens: number; output_tokens: number; cost_usd: number | null };
  latency_ms: Record<string, number>;
  model: { embedder: string; llm: string | null; prompt_version: string };
  diagnostics: { dense: RetrievedChunk[]; citations_dropped: number; llm_calls: number } | null;
}

export interface Conversation {
  id: string;
  title: string;
  document_ids: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  response: QueryResponse | null;
}

export interface Exchange {
  conversation: Conversation;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
}

export interface Limits {
  max_documents: number;
  max_total_bytes: number;
  max_questions_per_day: number;
  max_conversations: number;
}

export interface Me {
  kind: "owner" | "demo";
  label: string;
  created_at: string;
  expires_at: string | null;
  limits: Limits | null;
  usage: { documents: number; total_bytes: number; questions_today: number; conversations: number };
}

export interface DemoCreated {
  access_code: string;
  expires_in_days: number;
  limits: Limits;
}

export interface Health {
  status: string;
  database?: string;
  embedder?: string;
  max_upload_bytes?: number;
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

/**
 * Where the API lives. Empty in development (the Vite dev server proxies /v1 to FastAPI, so the
 * browser sees one origin). In production set VITE_API_URL at build time, and the API must allow
 * this site's origin (CORS_ORIGINS).
 */
export const API_BASE: string = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/+$/, "");

const KEY_STORAGE = "documind.apiKey";

/** The access code (demo) or API key (owner). Same header, same storage: the server tells them apart. */
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
    res = await fetch(API_BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", translate("err.network_error"));
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/health/ready"),

  // accounts
  me: (key?: string) => request<Me>("/v1/me", {}, key),
  createDemo: () => request<DemoCreated>("/v1/demo", { method: "POST" }, ""),

  // documents
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
  describeDocument: (id: string) => request<DocumentSummary>(`/v1/documents/${id}/describe`, { method: "POST" }),
  getJob: (id: string) => request<Job>(`/v1/jobs/${id}`),

  // chats
  listConversations: () => request<Conversation[]>("/v1/conversations"),
  createConversation: (body: { title?: string; document_ids?: string[] | null } = {}) =>
    request<Conversation>("/v1/conversations", { method: "POST", ...json(body) }),
  getConversation: (id: string) =>
    request<{ conversation: Conversation; messages: ChatMessage[] }>(`/v1/conversations/${id}`),
  updateConversation: (id: string, body: { title?: string; document_ids?: string[]; clear_scope?: boolean }) =>
    request<Conversation>(`/v1/conversations/${id}`, { method: "PATCH", ...json(body) }),
  deleteConversation: (id: string) => request<void>(`/v1/conversations/${id}`, { method: "DELETE" }),
  sendMessage: (id: string, question: string, debug = false) =>
    request<Exchange>(`/v1/conversations/${id}/messages`, { method: "POST", ...json({ question, debug }) }),

  /** Upload with byte-level progress (fetch can't report upload progress; XHR can). */
  uploadDocument(
    file: File,
    onProgress: (fraction: number) => void,
  ): Promise<{ document_id: string; job_id: string; status: string }> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API_BASE}/v1/documents`);
      const key = getApiKey();
      if (key) xhr.setRequestHeader("Authorization", `Bearer ${key}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onerror = () => reject(new ApiError(0, "network_error", translate("err.network_error")));
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
  const fr = locale().startsWith("fr");
  if (n < 1024) return `${n} ${fr ? "o" : "B"}`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} ${fr ? "Ko" : "KB"}`;
  return `${(n / 1024 / 1024).toFixed(1)} ${fr ? "Mo" : "MB"}`;
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function pageLabel(start: number, end: number): string {
  return start === end ? `p. ${start}` : `pp. ${start}–${end}`;
}

/** A friendly, translated message for any error. Server details are kept for codes we don't know. */
export function describeError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "quota_exceeded" && typeof e.extra.limit === "string") {
      const quotaKey = `err.quota_${e.extra.limit}` as Key;
      if (translate(quotaKey) !== quotaKey) return translate(quotaKey);
    }
    const key = `err.${e.code}` as Key;
    const known = translate(key);
    return known !== key ? known : e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}
