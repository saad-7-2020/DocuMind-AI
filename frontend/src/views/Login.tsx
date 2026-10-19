import { useState } from "react";
import { api, describeError, type DemoCreated } from "../api";
import { CopyButton } from "../components/CopyButton";
import { IconCheck, IconKey, IconLogo, IconSparkles } from "../components/Icons";
import { LangSwitch } from "../components/LangSwitch";
import { useI18n } from "../i18n";

export const CREATOR = (import.meta.env.VITE_CREATOR_NAME as string | undefined) ?? "Saad";

export function magicLink(code: string): string {
  return `${window.location.origin}${window.location.pathname}#/u/${code}`;
}

/** Sign in with an access code (no password), or create a private demo space in one click. */
export function Login({ onKey, initialError }: { onKey: (code: string) => void; initialError?: string }) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<"" | "login" | "demo">("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [created, setCreated] = useState<DemoCreated | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const code = value.trim();
    if (!code) return;
    setBusy("login");
    setError(null);
    try {
      await api.me(code);
      onKey(code);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy("");
    }
  }

  async function tryDemo() {
    setBusy("demo");
    setError(null);
    try {
      setCreated(await api.createDemo());
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="center-screen">
      <div className="login-lang"><LangSwitch /></div>
      <div className="login-shell">
      <section className="hero rise" aria-hidden={created ? "true" : undefined}>
        <div className="hero-brand"><div className="brand-mark"><IconLogo size={20} color="#fff" /></div> DocuMind AI</div>
        <h2>{t("login.hero_title")}</h2>
        <p>{t("login.hero_text")}</p>
        <ul className="hero-points">
          {(["f1", "f2", "f3"] as const).map((f) => (
            <li key={f}>
              <span className="hero-tick"><IconCheck size={14} /></span>
              <div><strong>{t(`login.${f}_t` as never)}</strong><span>{t(`login.${f}_d` as never)}</span></div>
            </li>
          ))}
        </ul>
      </section>
      <div className="card onboard rise">
        <div className="brand-mark brand-mark-lg"><IconLogo size={26} color="#fff" /></div>

        {created ? (
          <>
            <h1>{t("login.created_title")}</h1>
            <p className="muted" style={{ marginTop: 0 }}>{t("login.created_text")}</p>
            <div className="code-reveal">
              <span className="mono">{created.access_code}</span>
              <CopyButton text={created.access_code} />
            </div>
            <div className="label" style={{ marginTop: 14 }}>{t("login.link")}</div>
            <div className="code-reveal small">
              <span className="mono">{magicLink(created.access_code)}</span>
              <CopyButton text={magicLink(created.access_code)} />
            </div>
            <p className="faint" style={{ fontSize: 12.5 }}>
              {t("login.limits", {
                docs: created.limits.max_documents,
                questions: created.limits.max_questions_per_day,
                chats: created.limits.max_conversations,
              })}
            </p>
            <button className="btn btn-primary btn-lg" onClick={() => onKey(created.access_code)}>
              <IconSparkles size={16} /> {t("login.open")}
            </button>
          </>
        ) : (
          <>
            <h1>{t("login.title")}</h1>
            <p className="muted" style={{ marginTop: 0 }}>{t("login.subtitle")}</p>

            <form onSubmit={submit}>
              <label className="label" htmlFor="code">{t("login.code_label")}</label>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input id="code" className="input mono" placeholder={t("login.code_placeholder")} value={value}
                  autoFocus onChange={(e) => setValue(e.target.value)} autoComplete="off" spellCheck={false} />
                <button className="btn btn-primary" disabled={busy !== "" || !value.trim()}>
                  <IconKey size={16} /> {busy === "login" ? t("login.checking") : t("login.enter")}
                </button>
              </div>
            </form>
            {error && <p className="form-error" role="alert">{error}</p>}

            <div className="divider"><span>{t("login.or")}</span></div>

            <button className="btn btn-lg btn-block" onClick={tryDemo} disabled={busy !== ""}>
              <IconSparkles size={16} /> {busy === "demo" ? t("login.creating") : t("login.try_demo")}
            </button>
            <p className="faint" style={{ fontSize: 12.5, marginBottom: 0 }}>{t("login.demo_hint")}</p>
          </>
        )}
        <p className="faint login-by">{t("login.by", { name: CREATOR })}</p>
      </div>
      </div>
    </div>
  );
}
