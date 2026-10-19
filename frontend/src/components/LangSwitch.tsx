import { useI18n } from "../i18n";

/** FR | EN toggle, used on the login screen and in the top bar. */
export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div className="segmented lang-switch" role="group" aria-label={t("top.language")}>
      {(["fr", "en"] as const).map((l) => (
        <button key={l} className={lang === l ? "on" : ""} aria-pressed={lang === l} onClick={() => setLang(l)}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
