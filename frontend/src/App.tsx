import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, ApiError, describeError, getApiKey, setApiKey,
  type Conversation, type DocumentSummary, type Health, type Me,
} from "./api";
import { ChatList } from "./components/ChatList";
import { DocumentViewer, type ViewerTarget } from "./components/DocumentViewer";
import { IconChat, IconFiles, IconLogo, IconLogout, IconMenu, IconMoon, IconSettings, IconSun, IconX } from "./components/Icons";
import { LangSwitch } from "./components/LangSwitch";
import { useToast } from "./components/Toasts";
import { useI18n } from "./i18n";
import { ChatView } from "./views/ChatView";
import { DocumentsView } from "./views/DocumentsView";
import { Login } from "./views/Login";
import { SettingsView } from "./views/SettingsView";

type Route = "chat" | "documents" | "settings";
export type Theme = "dark" | "light";

const routeFromHash = (): Route => {
  const h = window.location.hash.replace("#/", "");
  return h === "documents" || h === "settings" ? h : "chat";
};

/** A magic link looks like  https://site/#/u/docu-mindk43trs8q2m  */
const codeFromHash = (): string | null => {
  const m = /^#\/u\/(.+)$/.exec(window.location.hash);
  return m ? decodeURIComponent(m[1]).trim() : null;
};

function loadTheme(): Theme {
  try {
    return localStorage.getItem("documind.theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function App() {
  const { t } = useI18n();
  const toast = useToast();
  const [apiKey, setKey] = useState(getApiKey());
  const [magicError, setMagicError] = useState<string | undefined>();
  const [magicBusy, setMagicBusy] = useState(() => codeFromHash() !== null);
  const [route, setRoute] = useState<Route>(routeFromHash());
  const [me, setMe] = useState<Me | null>(null);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [chats, setChats] = useState<Conversation[]>([]);
  const [activeChat, setActiveChat] = useState<string | null>(null); // null = a new, empty chat
  const [health, setHealth] = useState<Health | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [menuOpen, setMenuOpen] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [chatKey, setChatKey] = useState(0); // bumping it starts the chat view afresh

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("documind.theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    const onHash = () => { if (!codeFromHash()) setRoute(routeFromHash()); };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const logout = useCallback(() => {
    setApiKey("");
    setKey("");
    setMe(null);
    setDocs([]);
    setChats([]);
    setActiveChat(null);
    setDocsLoaded(false);
    window.location.hash = "";
  }, []);

  const signIn = useCallback((code: string) => {
    setApiKey(code);
    setKey(code);
    window.location.hash = "#/chat";
    setRoute("chat");
  }, []);

  // Magic link: validate the code in the URL, store it, and clean the address bar.
  // It runs on first load and also when a link is pasted into an already open tab.
  useEffect(() => {
    const tryMagic = () => {
      const code = codeFromHash();
      if (!code) return;
      setMagicBusy(true);
      setMagicError(undefined);
      api.me(code)
        .then(() => signIn(code))
        .catch((e) => { setMagicError(describeError(e)); window.location.hash = ""; })
        .finally(() => setMagicBusy(false));
    };
    tryMagic();
    window.addEventListener("hashchange", tryMagic);
    return () => window.removeEventListener("hashchange", tryMagic);
  }, [signIn]);

  const onAuthError = useCallback((e: unknown): boolean => {
    if (e instanceof ApiError && e.status === 401) {
      logout();
      toast("error", describeError(e));
      return true;
    }
    return false;
  }, [logout, toast]);

  const refreshMe = useCallback(async () => {
    if (!getApiKey()) return;
    try { setMe(await api.me()); } catch (e) { onAuthError(e); }
  }, [onAuthError]);

  const refreshDocs = useCallback(async () => {
    if (!getApiKey()) return;
    try {
      setDocs(await api.listAllDocuments());
      setDocsLoaded(true);
    } catch (e) {
      onAuthError(e);
    }
  }, [onAuthError]);

  const refreshChats = useCallback(async () => {
    if (!getApiKey()) return;
    try { setChats(await api.listConversations()); } catch (e) { onAuthError(e); }
  }, [onAuthError]);

  // Health check every 15 s (sidebar indicator).
  useEffect(() => {
    const check = () => api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
    check();
    const timer = setInterval(check, 15000);
    return () => clearInterval(timer);
  }, []);

  // Load the account and its chats once signed in.
  useEffect(() => {
    if (!apiKey) return;
    refreshMe();
    refreshChats();
  }, [apiKey, refreshMe, refreshChats]);

  // Document list: load once, then poll quickly while something is being processed.
  const busy = docs.some((d) => d.status === "pending" || d.status === "processing" || d.status === "deleting");
  const wasBusy = useRef(false);
  useEffect(() => {
    if (!apiKey) return;
    refreshDocs();
    const timer = setInterval(refreshDocs, busy ? 2000 : 15000);
    return () => clearInterval(timer);
  }, [apiKey, busy, refreshDocs]);
  useEffect(() => {
    if (wasBusy.current && !busy) refreshMe(); // usage changed after indexing finished
    wasBusy.current = busy;
  }, [busy, refreshMe]);

  if (magicBusy) return <div className="center-screen"><span className="spinner" style={{ color: "var(--accent)" }} /></div>;
  if (!apiKey) return <Login onKey={signIn} initialError={magicError} />;

  const go = (r: Route) => { window.location.hash = `#/${r}`; setRoute(r); setMenuOpen(false); };
  const ready = docs.filter((d) => d.status === "ready");
  const up = health?.status === "ok";
  const isDemo = me?.kind === "demo";
  const daysLeft = me?.expires_at ? Math.max(0, Math.ceil((new Date(me.expires_at).getTime() - Date.now()) / 86400000)) : null;

  const newChat = (question?: string) => {
    setActiveChat(null);
    setPendingQuestion(question ?? null);
    setChatKey((k) => k + 1);
    go("chat");
  };
  const openChat = (id: string) => { setActiveChat(id); setPendingQuestion(null); setChatKey((k) => k + 1); go("chat"); };

  async function renameChat(id: string, title: string) {
    try {
      const updated = await api.updateConversation(id, { title });
      setChats((all) => all.map((c) => (c.id === id ? updated : c)));
    } catch (e) {
      if (!onAuthError(e)) toast("error", describeError(e));
    }
  }

  async function deleteChat(c: Conversation) {
    if (!confirm(t("chat.delete_confirm", { title: c.title || t("chat.untitled") }))) return;
    try {
      await api.deleteConversation(c.id);
      setChats((all) => all.filter((x) => x.id !== c.id));
      if (activeChat === c.id) { setActiveChat(null); setChatKey((k) => k + 1); }
      refreshMe();
    } catch (e) {
      if (!onAuthError(e)) toast("error", describeError(e));
    }
  }

  return (
    <div className={`app ${menuOpen ? "menu-open" : ""}`}>
      <nav className="sidebar" aria-label={t("nav.main")}>
        <div className="brand">
          <div className="brand-mark"><IconLogo size={20} color="#fff" /></div>
          <div>
            <div className="brand-name">DocuMind AI</div>
            <div className="brand-sub">{t("brand.tagline")}</div>
          </div>
          <button className="icon-btn menu-close" aria-label={t("common.close")} onClick={() => setMenuOpen(false)}><IconX /></button>
        </div>

        <button className={`nav-item ${route === "chat" ? "active" : ""}`} onClick={() => go("chat")}>
          <IconChat /> {t("nav.assistant")}
        </button>
        {route === "chat" && (
          <ChatList conversations={chats} activeId={activeChat} onSelect={openChat} onNew={() => newChat()}
            onRename={renameChat} onDelete={deleteChat} />
        )}
        <button className={`nav-item ${route === "documents" ? "active" : ""}`} onClick={() => go("documents")}>
          <IconFiles /> {t("nav.documents")} <span className="count">{docs.length || ""}</span>
        </button>
        <button className={`nav-item ${route === "settings" ? "active" : ""}`} onClick={() => go("settings")}>
          <IconSettings /> {t("nav.settings")}
        </button>

        <div className="sidebar-footer">
          <div title={health?.embedder ?? ""}>
            <span className={`status-dot ${health ? (up ? "up" : "down") : ""}`} />
            {health ? (up ? t("status.up") : t("status.down")) : t("status.checking")}
          </div>
          <div className="faint">{t(ready.length === 1 ? "status.ready_one" : "status.ready_many", { n: ready.length })}</div>
        </div>
      </nav>
      {menuOpen && <div className="menu-scrim" onClick={() => setMenuOpen(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label={t("nav.main")} onClick={() => setMenuOpen(true)}><IconMenu /></button>
          <div className="topbar-account">
            {me && <span className={`badge ${isDemo ? "processing" : "ready"}`}>{isDemo ? t("top.demo") : t("top.owner")}</span>}
            {isDemo && daysLeft !== null && <span className="faint hide-sm">{t("top.expires", { n: daysLeft })}</span>}
          </div>
          <div className="spacer" />
          <LangSwitch />
          <button className="icon-btn" aria-label={t("top.theme")} title={t("top.theme")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <IconSun size={17} /> : <IconMoon size={17} />}
          </button>
          <button className="btn btn-sm logout-btn" onClick={logout} aria-label={t("top.logout")}>
            <IconLogout size={15} /> <span>{t("top.logout")}</span>
          </button>
        </header>

        {route === "chat" && (
          <ChatView
            key={chatKey}
            conversationId={activeChat}
            docs={ready}
            docsLoaded={docsLoaded}
            initialQuestion={pendingQuestion}
            onConsumedInitial={() => setPendingQuestion(null)}
            onOpenSource={setViewer}
            onGoDocuments={() => go("documents")}
            onConversation={(c) => {
              setChats((all) => [c, ...all.filter((x) => x.id !== c.id)]);
              setActiveChat(c.id);
            }}
            onUsage={refreshMe}
            onAuthError={onAuthError}
          />
        )}
        {route === "documents" && (
          <DocumentsView docs={docs} loaded={docsLoaded} refresh={refreshDocs} onOpen={setViewer}
            maxUploadBytes={health?.max_upload_bytes} me={me} onAsk={(q) => newChat(q)} onChanged={refreshMe} />
        )}
        {route === "settings" && <SettingsView health={health} theme={theme} setTheme={setTheme} me={me} onLogout={logout} />}
      </main>

      {viewer && <DocumentViewer target={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}
