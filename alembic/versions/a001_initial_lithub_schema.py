"""initial lithub schema

Revision ID: a001_initial
Revises:
Create Date: 2026-06-01 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pmid", sa.String(length=64), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("journal", sa.String(length=512), nullable=True),
        sa.Column("pub_date", sa.String(length=64), nullable=True),
        sa.Column("authors", postgresql.JSONB(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("design", sa.String(length=128), nullable=True),
        sa.Column("design_tags", postgresql.ARRAY(sa.String(length=64)), nullable=True),
        sa.Column("study_design", sa.String(length=64), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pmid IS NOT NULL OR doi IS NOT NULL", name="papers_at_least_one_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_papers_pmid",
        "papers",
        ["pmid"],
        unique=True,
        postgresql_where=sa.text("pmid IS NOT NULL"),
    )
    op.create_index(
        "ux_papers_doi",
        "papers",
        ["doi"],
        unique=True,
        postgresql_where=sa.text("doi IS NOT NULL"),
    )

    op.create_table(
        "folders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "parent_id", "name", name="uq_folders_user_parent_name"),
    )
    op.create_index("ix_folders_user_id", "folders", ["user_id"])

    op.create_table(
        "library_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.UUID(), nullable=True),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="'search'"),
        sa.Column("recommended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("full_text_status", sa.String(length=32), nullable=True),
        sa.Column("best_full_text_url", sa.Text(), nullable=True),
        sa.Column("answer_context_id", sa.String(length=128), nullable=True),
        sa.Column("portal_engine_record_id", sa.String(length=128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "paper_id", name="uq_library_user_paper"),
    )
    op.create_index("ix_library_user_saved", "library_entries", ["user_id", "saved_at"])
    op.create_index("ix_library_user_folder", "library_entries", ["user_id", "folder_id"])


def downgrade() -> None:
    op.drop_index("ix_library_user_folder", table_name="library_entries")
    op.drop_index("ix_library_user_saved", table_name="library_entries")
    op.drop_table("library_entries")

    op.drop_index("ix_folders_user_id", table_name="folders")
    op.drop_table("folders")

    op.drop_index("ux_papers_doi", table_name="papers")
    op.drop_index("ux_papers_pmid", table_name="papers")
    op.drop_table("papers")
