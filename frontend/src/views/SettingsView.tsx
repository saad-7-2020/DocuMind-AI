import { useState } from "react";
import { API_BASE, api, describeError, getApiKey, setApiKey, type Health } from "../api";
import type { Theme } from "../App";
import { IconKey, IconMoon, IconSun } from "../components/Icons";
import { useToast } from "../components/Toasts";

export function SettingsView({
  health, theme, setTheme, onLogout,
}: {
  health: Health | null;
  theme: Theme;
  setTheme: (t: Theme) => void;
  onLogout: () => void;
}) {
  const [newKey, setNewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const current = getApiKey();
  const masked = current ? `${current.slice(0, 8)}${"•".repeat(12)}` : "–";

  async function replaceKey() {
    setBusy(true);
    try {
      await api.checkKey(newKey.trim());
      setApiKey(newKey.trim());
      setNewKey("");
      toast("success", "Clé API mise à jour.");
      window.location.reload();
    } catch (e) {
      toast("error", describeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Paramètres</h1>
          <p className="page-subtitle">Connexion à l'API, apparence et état du système.</p>
        </div>
      </div>

      <div className="settings-grid">
        <section className="card settings-section">
          <h2>Clé API</h2>
          <p>Stockée uniquement dans ce navigateur. Elle identifie votre compte : vous ne voyez que vos documents.</p>
          <dl className="kv" style={{ marginBottom: 14 }}>
            <dt>Clé actuelle</dt><dd className="mono">{masked}</dd>
          </dl>
          <div className="row">
            <input className="input mono" style={{ flex: "1 1 260px" }} placeholder="Nouvelle clé dm_…" value={newKey}
              onChange={(e) => setNewKey(e.target.value)} autoComplete="off" spellCheck={false} />
            <button className="btn" disabled={!newKey.trim() || busy} onClick={replaceKey}><IconKey size={15} /> Remplacer</button>
            <button className="btn btn-danger" onClick={onLogout}>Se déconnecter</button>
          </div>
        </section>

        <section className="card settings-section">
          <h2>Apparence</h2>
          <p>Le thème est mémorisé sur cet appareil.</p>
          <div className="segmented" role="group" aria-label="Thème">
            <button className={theme === "dark" ? "on" : ""} onClick={() => setTheme("dark")}><IconMoon size={14} /> Sombre</button>
            <button className={theme === "light" ? "on" : ""} onClick={() => setTheme("light")}><IconSun size={14} /> Clair</button>
          </div>
        </section>

        <section className="card settings-section">
          <h2>État du système</h2>
          <p>Vérifié automatiquement toutes les 15 secondes.</p>
          <dl className="kv">
            <dt>Adresse de l'API</dt><dd className="mono">{API_BASE || "même origine (proxy de développement)"}</dd>
            <dt>État de l'API</dt>
            <dd><span className={`status-dot ${health?.status === "ok" ? "up" : "down"}`} />{health?.status === "ok" ? "Opérationnelle" : "Injoignable"}</dd>
            <dt>Base de données</dt><dd>{health?.database ?? "–"}</dd>
            <dt>Modèle d'embedding</dt><dd className="mono">{health?.embedder ?? "–"}</dd>
            <dt>Recherche</dt><dd>Dense (pgvector HNSW) · hybride + reranking en phase 3</dd>
          </dl>
        </section>
      </div>
    </div>
  );
}
