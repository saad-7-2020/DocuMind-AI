import { API_BASE, formatBytes, formatDate, getApiKey, type Health, type Me } from "../api";
import type { Theme } from "../App";
import { CopyButton } from "../components/CopyButton";
import { IconLogout, IconMoon, IconSun } from "../components/Icons";
import { LangSwitch } from "../components/LangSwitch";
import { useI18n } from "../i18n";
import { magicLink } from "./Login";

function Meter({ label, used, max, format }: { label: string; used: number; max: number; format?: (n: number) => string }) {
  const f = format ?? String;
  return (
    <div className="meter">
      <div className="meter-head"><span>{label}</span><span className="muted">{f(used)} / {f(max)}</span></div>
      <div className="progress"><span style={{ width: `${Math.min(100, (used / Math.max(1, max)) * 100)}%` }} /></div>
    </div>
  );
}

export function SettingsView({
  health, theme, setTheme, me, onLogout,
}: {
  health: Health | null;
  theme: Theme;
  setTheme: (t: Theme) => void;
  me: Me | null;
  onLogout: () => void;
}) {
  const { t } = useI18n();
  const code = getApiKey();
  const isDemo = me?.kind === "demo";
  const shown = isDemo ? code : code ? `${code.slice(0, 8)}${"•".repeat(12)}` : "–";

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("settings.title")}</h1>
          <p className="page-subtitle">{t("settings.subtitle")}</p>
        </div>
      </div>

      <div className="settings-grid">
        <section className="card settings-section">
          <h2>{t("settings.account")}</h2>
          <p>{t("settings.account_text")}</p>
          <dl className="kv" style={{ marginBottom: 14 }}>
            <dt>{t("settings.kind")}</dt>
            <dd>{me ? (isDemo ? t("settings.kind_demo") : t("settings.kind_owner")) : "–"}</dd>
            <dt>{t("settings.code")}</dt>
            <dd className="code-line"><span className="mono">{shown}</span>{isDemo && <CopyButton text={code} />}</dd>
            {isDemo && (
              <>
                <dt>{t("settings.link")}</dt>
                <dd className="code-line"><span className="mono ellipsis">{magicLink(code)}</span><CopyButton text={magicLink(code)} /></dd>
              </>
            )}
            {me?.expires_at && <><dt>{t("settings.expires")}</dt><dd>{formatDate(me.expires_at)}</dd></>}
          </dl>

          {me?.limits && (
            <div className="meters">
              <div className="label">{t("settings.usage")}</div>
              <Meter label={t("settings.u_docs")} used={me.usage.documents} max={me.limits.max_documents} />
              <Meter label={t("settings.u_storage")} used={me.usage.total_bytes} max={me.limits.max_total_bytes} format={formatBytes} />
              <Meter label={t("settings.u_questions")} used={me.usage.questions_today} max={me.limits.max_questions_per_day} />
              <Meter label={t("settings.u_chats")} used={me.usage.conversations} max={me.limits.max_conversations} />
            </div>
          )}

          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn btn-danger" onClick={onLogout}><IconLogout size={15} /> {t("settings.logout")}</button>
          </div>
          {isDemo && <p className="faint" style={{ fontSize: 12.5, margin: "10px 0 0" }}>{t("settings.logout_hint")}</p>}
        </section>

        <section className="card settings-section">
          <h2>{t("settings.appearance")}</h2>
          <p>{t("settings.appearance_text")}</p>
          <div className="row">
            <div className="segmented" role="group" aria-label="Theme">
              <button className={theme === "dark" ? "on" : ""} onClick={() => setTheme("dark")}><IconMoon size={14} /> {t("settings.dark")}</button>
              <button className={theme === "light" ? "on" : ""} onClick={() => setTheme("light")}><IconSun size={14} /> {t("settings.light")}</button>
            </div>
            <LangSwitch />
          </div>
        </section>

        <section className="card settings-section">
          <h2>{t("settings.system")}</h2>
          <p>{t("settings.system_text")}</p>
          <dl className="kv">
            <dt>{t("settings.api_url")}</dt><dd className="mono">{API_BASE || t("settings.same_origin")}</dd>
            <dt>{t("settings.api_state")}</dt>
            <dd><span className={`status-dot ${health?.status === "ok" ? "up" : "down"}`} />{health?.status === "ok" ? t("settings.ok") : t("settings.unreachable")}</dd>
            <dt>{t("settings.db")}</dt><dd>{health?.database ?? "–"}</dd>
            <dt>{t("settings.embedder")}</dt><dd className="mono">{health?.embedder ?? "–"}</dd>
            <dt>{t("settings.search")}</dt><dd>{t("settings.search_value")}</dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
