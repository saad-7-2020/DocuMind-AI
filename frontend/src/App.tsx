import { useCallback, useEffect, useState } from "react";
import { api, ApiError, describeError, getApiKey, setApiKey, type DocumentSummary, type Health } from "./api";
import { DocumentViewer, type ViewerTarget } from "./components/DocumentViewer";
import { IconChat, IconFiles, IconKey, IconLogo, IconSettings } from "./components/Icons";
import { useToast } from "./components/Toasts";
import { ChatView } from "./views/ChatView";
import { DocumentsView } from "./views/DocumentsView";
import { SettingsView } from "./views/SettingsView";

type Route = "chat" | "documents" | "settings";
export type Theme = "dark" | "light";

const routeFromHash = (): Route => {
  const h = window.location.hash.replace("#/", "");
  return h === "documents" || h === "settings" ? h : "chat";
};

function loadTheme(): Theme {
  try {
    return localStorage.getItem("documind.theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function App() {
  const [apiKey, setKey] = useState(getApiKey());
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const toast = useToast();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("documind.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const refreshDocs = useCallback(async () => {
    if (!getApiKey()) return;
    try {
      setDocs(await api.listAllDocuments());
      setDocsLoaded(true);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setApiKey("");
        setKey("");
        toast("error", "Clé API refusée. Saisissez une nouvelle clé.");
      }
    }
  }, [toast]);

  // Health check every 15 s (sidebar indicator).
  useEffect(() => {
    const check = () => api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
    check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);

  // Document list: load once, then poll quickly while something is being processed.
  const busy = docs.some((d) => d.status === "pending" || d.status === "processing" || d.status === "deleting");
  useEffect(() => {
    if (!apiKey) return;
    refreshDocs();
    const t = setInterval(refreshDocs, busy ? 2000 : 15000);
    return () => clearInterval(t);
  }, [apiKey, busy, refreshDocs]);

  if (!apiKey) return <Onboarding onKey={(k) => { setApiKey(k); setKey(k); }} />;

  const go = (r: Route) => { window.location.hash = `#/${r}`; };
  const ready = docs.filter((d) => d.status === "ready");
  const up = health?.status === "ok";

  return (
    <div className="app">
      <nav className="sidebar" aria-label="Navigation principale">
        <div className="brand">
          <div className="brand-mark"><IconLogo size={20} color="#fff" /></div>
          <div>
            <div className="brand-name">DocuMind AI</div>
            <div className="brand-sub">Questions sur vos documents</div>
          </div>
        </div>
        <button className={`nav-item ${route === "chat" ? "active" : ""}`} onClick={() => go("chat")}>
          <IconChat /> Assistant
        </button>
        <button className={`nav-item ${route === "documents" ? "active" : ""}`} onClick={() => go("documents")}>
          <IconFiles /> Documents <span className="count">{docs.length || ""}</span>
        </button>
        <button className={`nav-item ${route === "settings" ? "active" : ""}`} onClick={() => go("settings")}>
          <IconSettings /> Paramètres
        </button>
        <div className="sidebar-footer">
          <div title={health?.embedder ?? ""}>
            <span className={`status-dot ${health ? (up ? "up" : "down") : ""}`} />
            {health ? (up ? "API connectée" : "API injoignable") : "Vérification…"}
          </div>
          <div className="faint">{ready.length} document{ready.length > 1 ? "s" : ""} prêt{ready.length > 1 ? "s" : ""}</div>
        </div>
      </nav>

      <main className="main">
        {route === "chat" && (
          <ChatView docs={ready} docsLoaded={docsLoaded} onOpenSource={setViewer} onGoDocuments={() => go("documents")} />
        )}
        {route === "documents" && (
          <DocumentsView docs={docs} loaded={docsLoaded} refresh={refreshDocs} onOpen={setViewer}
            maxUploadBytes={health?.max_upload_bytes} />
        )}
        {route === "settings" && (
          <SettingsView health={health} theme={theme} setTheme={setTheme}
            onLogout={() => { setApiKey(""); setKey(""); }} />
        )}
      </main>

      {viewer && <DocumentViewer target={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}

function Onboarding({ onKey }: { onKey: (k: string) => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const key = value.trim();
    if (!key) return;
    setBusy(true);
    setError(null);
    try {
      await api.checkKey(key);
      onKey(key);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center-screen">
      <form className="card onboard" onSubmit={submit}>
        <div className="brand-mark" style={{ width: 48, height: 48, borderRadius: 14 }}><IconLogo size={26} color="#fff" /></div>
        <h1>Bienvenue sur DocuMind AI</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Importez vos documents, posez vos questions, et obtenez des réponses sourcées, page par page.
        </p>
        <label className="label" htmlFor="key">Clé API</label>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input id="key" className="input mono" placeholder="dm_…" value={value} autoFocus
            onChange={(e) => setValue(e.target.value)} autoComplete="off" spellCheck={false} />
          <button className="btn btn-primary" disabled={busy || !value.trim()}>
            <IconKey size={16} /> {busy ? "Vérification…" : "Se connecter"}
          </button>
        </div>
        {error && <p style={{ color: "var(--danger)", marginBottom: 0 }}>{error}</p>}
        <p className="faint" style={{ fontSize: 12.5, marginTop: 18, marginBottom: 6 }}>Pas encore de clé ? Dans <span className="mono">backend/</span> :</p>
        <div className="code-block">py -m uv run documind create-user vous@exemple.com</div>
      </form>
    </div>
  );
}
