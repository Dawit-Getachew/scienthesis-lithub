"""Canonical paper metadata."""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    JSON,
    CheckConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base

# Postgres-native types fall back to JSON on SQLite for fast in-memory tests.
_AUTHORS_TYPE = JSONB().with_variant(JSON(), "sqlite")
_DESIGN_TAGS_TYPE = ARRAY(String(64)).with_variant(JSON(), "sqlite")
_RAW_METADATA_TYPE = JSONB().with_variant(JSON(), "sqlite")


class Paper(Base):
    """Canonical paper metadata, deduped by PMID or DOI.

    A paper exists once globally — users save references to it via
    :class:`LibraryEntry`. ``pmid`` and ``doi`` are both nullable but at least
    one must be present (enforced by a CHECK constraint).
    """

    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint("pmid IS NOT NULL OR doi IS NOT NULL", name="papers_at_least_one_id"),
        Index(
            "ux_papers_pmid",
            "pmid",
            unique=True,
            postgresql_where=text("pmid IS NOT NULL"),
            sqlite_where=text("pmid IS NOT NULL"),
        ),
        Index(
            "ux_papers_doi",
            "doi",
            unique=True,
            postgresql_where=text("doi IS NOT NULL"),
            sqlite_where=text("doi IS NOT NULL"),
        ),
    )

    pmid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pub_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    authors: Mapped[list | None] = mapped_column(_AUTHORS_TYPE, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    design: Mapped[str | None] = mapped_column(String(128), nullable=True)
    design_tags: Mapped[list[str] | None] = mapped_column(_DESIGN_TAGS_TYPE, nullable=True)
    study_design: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(_RAW_METADATA_TYPE, nullable=True)
