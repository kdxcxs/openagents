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
