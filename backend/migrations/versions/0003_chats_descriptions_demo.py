"""Chats, document descriptions, demo accounts, failed-login log.

- conversations / messages: chats saved server-side, per owner.
- documents.summary / keywords / suggested_questions: the AI-written description shown on document cards.
- users.kind / last_active_at / created_ip_hash: 'demo' accounts (self-service, limited, expiring).
- auth_failures: failed access-code attempts per (hashed) client address, used to throttle guessing.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NEW_TABLES = ("conversations", "messages", "auth_failures")

UPGRADE = r"""
ALTER TABLE users
    ADD COLUMN kind            text NOT NULL DEFAULT 'owner' CHECK (kind IN ('owner', 'demo')),
    ADD COLUMN last_active_at  timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN created_ip_hash text;
CREATE INDEX users_demo_activity ON users (last_active_at) WHERE kind = 'demo';
CREATE INDEX users_demo_signups  ON users (created_ip_hash, created_at) WHERE kind = 'demo';

ALTER TABLE documents
    ADD COLUMN summary             text,
    ADD COLUMN keywords            jsonb NOT NULL DEFAULT '[]',
    ADD COLUMN suggested_questions jsonb NOT NULL DEFAULT '[]';

CREATE TABLE conversations (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title        text NOT NULL DEFAULT '',
    document_ids jsonb,                                   -- search scope; NULL = all of the owner's documents
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_owner_updated ON conversations (owner_id, updated_at DESC);

CREATE TABLE messages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    owner_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            text NOT NULL CHECK (role IN ('user', 'assistant')),
    content         text NOT NULL,
    payload         jsonb NOT NULL DEFAULT '{}',          -- assistant: citations, usage, latency, model, ...
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation ON messages (conversation_id, created_at);
CREATE INDEX messages_owner_created ON messages (owner_id, created_at);

CREATE TABLE auth_failures (
    id         bigserial PRIMARY KEY,
    ip_hash    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_failures_ip ON auth_failures (ip_hash, created_at);
"""

DOWNGRADE = r"""
DROP TABLE IF EXISTS auth_failures, messages, conversations;
ALTER TABLE documents DROP COLUMN IF EXISTS suggested_questions, DROP COLUMN IF EXISTS keywords,
    DROP COLUMN IF EXISTS summary;
DROP INDEX IF EXISTS users_demo_signups;
DROP INDEX IF EXISTS users_demo_activity;
ALTER TABLE users DROP COLUMN IF EXISTS created_ip_hash, DROP COLUMN IF EXISTS last_active_at,
    DROP COLUMN IF EXISTS kind;
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    for table in NEW_TABLES:  # same rule as migration 0002: RLS on, no policies, API roles lose access
        op.execute("ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY")  # noqa: S608
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(DOWNGRADE)
