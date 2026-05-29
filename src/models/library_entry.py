"""Per-user library entry — links a user to a paper they have saved."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LibraryEntry(Base):
    """A user's reference to a :class:`Paper`.

    Unique on ``(user_id, paper_id)`` so the same paper saved twice from
    different surfaces (LitPulse search, LitPortal collection, …) collapses
    into a single entry whose ``source`` reflects whichever surface most
    recently touched it. The original surface remains recoverable from
    ``portal_engine_record_id`` / ``answer_context_id`` when those are set.
    """

    __tablename__ = "library_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "paper_id", name="uq_library_user_paper"),
        Index("ix_library_user_saved", "user_id", "saved_at"),
        Index("ix_library_user_folder", "user_id", "folder_id"),
    )

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paper_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False,
    )
    folder_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True,
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="search", server_default="'search'",
    )
    recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    full_text_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    best_full_text_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_context_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    portal_engine_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
