"""User-owned folder for organizing library entries."""

from __future__ import annotations

from uuid import UUID as PyUUID

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Folder(Base):
    """A per-user folder. ``Inbox`` is auto-created on first save for each user.

    Folders are organizational only — they do not affect dedup or membership.
    A library entry's ``folder_id`` is nullable so an entry can exist outside
    any folder (the Inbox treatment); when set, the folder name is shown to
    the user and is what the LitPulse frontend renders.
    """

    __tablename__ = "folders"
    __table_args__ = (
        UniqueConstraint("user_id", "parent_id", "name", name="uq_folders_user_parent_name"),
        Index("ix_folders_user_id", "user_id"),
    )

    user_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[PyUUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
