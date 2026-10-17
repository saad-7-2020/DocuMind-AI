"""Enable row-level security on every table.

On Supabase, tables in the `public` schema are reachable through its auto-generated REST API
by the `anon` and `authenticated` roles. This application never uses that API: it connects as
the table owner, which bypasses RLS. Enabling RLS with no policies therefore means "no access
for anyone but the backend", the safe default. Locally (plain Postgres) it changes nothing.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = (
    "users", "api_keys", "documents", "document_pages", "chunks", "jobs",
    "query_logs", "query_retrievals", "eval_runs", "eval_items", "alembic_version",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute("ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY")  # noqa: S608
    # Defense in depth where Supabase's API roles exist: also drop their table privileges.
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
    for table in TABLES:
        op.execute("ALTER TABLE " + table + " DISABLE ROW LEVEL SECURITY")  # noqa: S608
