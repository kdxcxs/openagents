# -*- coding: utf-8 -*-
"""Sync migrations with current ORM models.

Revision ID: 014
Revises: 013
Create Date: 2026-05-22
"""

from alembic import op


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These columns already existed in the InsForge bootstrap SQL, but were
    # missing from the incremental Alembic path used by existing databases.
    op.execute("ALTER TABLE channels ADD COLUMN IF NOT EXISTS title_manually_set boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE channels ADD COLUMN IF NOT EXISTS resume_from text")
    op.execute("ALTER TABLE workspace_members ADD COLUMN IF NOT EXISTS description text")

    # Repair tables that may be missing on databases that were stamped after
    # historical migrations were inserted or edited. Normal databases already
    # have these tables, so every statement is idempotent.
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_collaborators (
            id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            email        text        NOT NULL,
            role         text        DEFAULT 'editor',
            added_by     text,
            added_at     timestamptz DEFAULT now(),
            CONSTRAINT uq_collaborator_workspace_email UNIQUE (workspace_id, email)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_collaborators_workspace ON workspace_collaborators (workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_collaborators_email ON workspace_collaborators (email)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS browser_contexts (
            id            text        PRIMARY KEY,
            workspace_id  uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name          text        NOT NULL,
            bb_context_id text,
            domain        text,
            status        text        NOT NULL DEFAULT 'active',
            created_by    text        NOT NULL,
            shared_with   jsonb       DEFAULT '[]'::jsonb,
            created_at    timestamptz DEFAULT now(),
            last_used_at  timestamptz DEFAULT now(),
            CONSTRAINT uq_browser_context_workspace_name UNIQUE (workspace_id, name)
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_browser_contexts_workspace_status "
        "ON browser_contexts (workspace_id, status)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS browser_tabs (
            id              text        PRIMARY KEY,
            workspace_id    uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            url             text        NOT NULL DEFAULT 'about:blank',
            title           text,
            status          text        NOT NULL DEFAULT 'active',
            created_by      text        NOT NULL,
            shared_with     jsonb       DEFAULT '[]'::jsonb,
            context_id      text        REFERENCES browser_contexts(id) ON DELETE SET NULL,
            session_id      text,
            live_url        text,
            created_at      timestamptz DEFAULT now(),
            last_active_at  timestamptz DEFAULT now()
        );
    """)
    op.execute(
        "ALTER TABLE browser_tabs ADD COLUMN IF NOT EXISTS context_id "
        "text REFERENCES browser_contexts(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_browser_tabs_workspace_status ON browser_tabs (workspace_id, status)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS browser_usage (
            id                text        PRIMARY KEY,
            workspace_id      uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            tab_id            text        NOT NULL,
            session_id        text,
            opened_by         text        NOT NULL,
            started_at        timestamptz NOT NULL DEFAULT now(),
            ended_at          timestamptz,
            duration_seconds  integer
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_browser_usage_workspace ON browser_usage (workspace_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_browser_usage_opened_by ON browser_usage (opened_by)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_browser_usage_started ON browser_usage (started_at)")

    # File metadata is part of the ORM and InsForge bootstrap schema, but the
    # live Alembic chain never created it for normal Postgres deployments.
    op.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id            text        PRIMARY KEY,
            workspace_id  uuid        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            filename      text        NOT NULL,
            content_type  text        NOT NULL DEFAULT 'application/octet-stream',
            size          integer     NOT NULL,
            storage_key   text        NOT NULL,
            uploaded_by   text        NOT NULL,
            channel_name  text,
            status        text        NOT NULL DEFAULT 'active',
            created_at    timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_files_workspace_status ON files (workspace_id, status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_files_workspace_status")
    op.execute("DROP TABLE IF EXISTS files")
    op.execute("ALTER TABLE workspace_members DROP COLUMN IF EXISTS description")
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS resume_from")
    op.execute("ALTER TABLE channels DROP COLUMN IF EXISTS title_manually_set")
