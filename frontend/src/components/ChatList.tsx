import { useEffect, useRef, useState } from "react";
import type { Conversation } from "../api";
import { useI18n } from "../i18n";
import { IconCheck, IconChat, IconPencil, IconPlus, IconTrash, IconX } from "./Icons";

/** The list of chats: open one, start a new one, rename or delete. */
export function ChatList({
  conversations, activeId, onSelect, onNew, onRename, onDelete,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (c: Conversation) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);

  const start = (c: Conversation) => { setEditing(c.id); setDraft(c.title); };
  async function commit(c: Conversation) {
    const title = draft.trim();
    setEditing(null);
    if (title && title !== c.title) await onRename(c.id, title);
  }

  return (
    <div className="chat-list" aria-label={t("chat.list")}>
      <button className="btn btn-primary btn-block" onClick={onNew}>
        <IconPlus size={16} /> {t("chat.new")}
      </button>
      <div className="chat-list-items">
        {conversations.length === 0 && <div className="faint chat-list-empty">{t("chat.none")}</div>}
        {conversations.map((c) => (
          <div key={c.id} className={`chat-item ${c.id === activeId ? "active" : ""}`}>
            {editing === c.id ? (
              <form className="chat-edit" onSubmit={(e) => { e.preventDefault(); commit(c); }}>
                <input ref={inputRef} className="input" value={draft} maxLength={120} aria-label={t("chat.rename")}
                  onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setEditing(null)} />
                <button type="submit" className="icon-btn" aria-label={t("common.save")}><IconCheck size={15} /></button>
                <button type="button" className="icon-btn" aria-label={t("common.cancel")} onClick={() => setEditing(null)}>
                  <IconX size={15} />
                </button>
              </form>
            ) : (
              <>
                <button className="chat-open" onClick={() => onSelect(c.id)} title={c.title || t("chat.untitled")}>
                  <IconChat size={15} />
                  <span>{c.title || t("chat.untitled")}</span>
                </button>
                <div className="chat-actions">
                  <button className="icon-btn" aria-label={t("chat.rename")} title={t("chat.rename")} onClick={() => start(c)}>
                    <IconPencil size={14} />
                  </button>
                  <button className="icon-btn btn-danger" aria-label={t("chat.delete")} title={t("chat.delete")} onClick={() => onDelete(c)}>
                    <IconTrash size={14} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
