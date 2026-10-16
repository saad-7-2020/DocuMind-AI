import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { IconAlert, IconCheck, IconX } from "./Icons";

type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; text: string }

const ToastContext = createContext<(kind: Kind, text: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Kind, text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`card toast ${t.kind}`}>
            <span style={{ color: t.kind === "error" ? "var(--danger)" : t.kind === "success" ? "var(--ok)" : "var(--info)" }}>
              {t.kind === "error" ? <IconAlert /> : <IconCheck />}
            </span>
            <span style={{ flex: 1 }}>{t.text}</span>
            <button className="icon-btn" style={{ width: 24, height: 24 }} aria-label="Fermer"
              onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>
              <IconX size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
