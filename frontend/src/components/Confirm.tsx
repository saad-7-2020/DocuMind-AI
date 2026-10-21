// A centered confirmation dialog, replacing the browser's plain confirm() box.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import { IconAlert } from "./Icons";

interface Options {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
}

type Ask = (options: Options) => Promise<boolean>;
const ConfirmContext = createContext<Ask>(() => Promise.resolve(false));

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState<(Options & { resolve: (ok: boolean) => void }) | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const ask = useCallback<Ask>((options) => new Promise((resolve) => setOpen({ ...options, resolve })), []);
  const close = useCallback((ok: boolean) => {
    setOpen((current) => {
      current?.resolve(ok);
      return null;
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus(); // the safe choice has the focus
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      {open && (
        <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && close(false)}>
          <div className="card modal rise" role="alertdialog" aria-modal="true" aria-labelledby="modal-title">
            <div className={`modal-icon ${open.danger ? "danger" : ""}`}><IconAlert size={22} /></div>
            <h2 id="modal-title">{open.title}</h2>
            <p>{open.message}</p>
            <div className="modal-actions">
              <button ref={cancelRef} className="btn" onClick={() => close(false)}>{t("common.cancel")}</button>
              <button className={`btn ${open.danger ? "btn-danger-solid" : "btn-primary"}`} onClick={() => close(true)}>
                {open.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}

export const useConfirm = () => useContext(ConfirmContext);
