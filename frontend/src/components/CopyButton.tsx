import { useState } from "react";
import { useI18n } from "../i18n";
import { IconCheck, IconCopy } from "./Icons";

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const { t } = useI18n();
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1800);
    } catch {
      /* clipboard blocked: the text stays selectable on screen */
    }
  }
  return (
    <button type="button" className="btn btn-sm" onClick={copy}>
      {done ? <IconCheck size={14} /> : <IconCopy size={14} />} {done ? t("common.copied") : label ?? t("common.copy")}
    </button>
  );
}
