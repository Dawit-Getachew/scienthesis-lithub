"""Library-entry repository — per-user library operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.library_entry import LibraryEntry
from src.models.paper import Paper

SortBy = Literal["saved_at", "title", "journal"]
SortDir = Literal["asc", "desc"]


class LibraryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Single-entry operations ───────────────────────────────────────

    async def get_by_user_and_paper(
        self, user_id: UUID, paper_id: UUID,
    ) -> LibraryEntry | None:
        stmt = select(LibraryEntry).where(
            LibraryEntry.user_id == user_id, LibraryEntry.paper_id == paper_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_id(
        self, user_id: UUID, entry_id: UUID,
    ) -> LibraryEntry | None:
        stmt = select(LibraryEntry).where(
            LibraryEntry.id == entry_id, LibraryEntry.user_id == user_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        user_id: UUID,
        paper_id: UUID,
        folder_id: UUID | None,
        attrs: dict[str, Any],
    ) -> tuple[LibraryEntry, bool]:
        """Insert or update the (user_id, paper_id) entry.

        Returns ``(entry, created)``. On update, only non-empty attrs replace
        existing values — this lets a later "rich" save (with full metadata)
        upgrade an earlier "sparse" save without callers needing to merge.
        """
        existing = await self.get_by_user_and_paper(user_id, paper_id)
        if existing is None:
            entry = LibraryEntry(
                user_id=user_id,
                paper_id=paper_id,
                folder_id=folder_id,
                source=attrs.get("source", "search"),
                recommended=bool(attrs.get("recommended", False)),
                selected=bool(attrs.get("selected", False)),
                full_text_status=attrs.get("full_text_status"),
                best_full_text_url=attrs.get("best_full_text_url"),
                answer_context_id=attrs.get("answer_context_id"),
                portal_engine_record_id=attrs.get("portal_engine_record_id"),
                notes=attrs.get("notes"),
            )
            self.db.add(entry)
            await self.db.commit()
            await self.db.refresh(entry)
            return entry, True

        changed = False
        if folder_id is not None and folder_id != existing.folder_id:
            existing.folder_id = folder_id
            changed = True
        for col in (
            "full_text_status",
            "best_full_text_url",
            "answer_context_id",
            "portal_engine_record_id",
            "notes",
        ):
            value = attrs.get(col)
            if value and not getattr(existing, col, None):
                setattr(existing, col, value)
                changed = True
        # source: always refresh to the most recent surface, since this is
        # informational provenance, not identity.
        new_source = attrs.get("source")
        if new_source and new_source != existing.source:
            existing.source = new_source
            changed = True
        # recommended/selected only flip True, never back to False, because a
        # paper that was once selected stays selected unless explicitly cleared.
        for col in ("recommended", "selected"):
            if attrs.get(col) and not getattr(existing, col):
                setattr(existing, col, True)
                changed = True
        if changed:
            await self.db.commit()
            await self.db.refresh(existing)
        return existing, False

    async def delete(self, user_id: UUID, entry_id: UUID) -> bool:
        entry = await self.get_by_id(user_id, entry_id)
        if entry is None:
            return False
        await self.db.delete(entry)
        await self.db.commit()
        return True

    async def move(
        self, user_id: UUID, entry_id: UUID, target_folder_id: UUID | None,
    ) -> LibraryEntry | None:
        entry = await self.get_by_id(user_id, entry_id)
        if entry is None:
            return None
        entry.folder_id = target_folder_id
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    # ── Listing / pagination ──────────────────────────────────────────

    async def list_with_papers(
        self,
        *,
        user_id: UUID,
        limit: int = 50,
        cursor_entry_id: UUID | None = None,
        search: str | None = None,
        design_type: str | None = None,
        saved_after: datetime | None = None,
        sort_by: SortBy = "saved_at",
        sort_dir: SortDir = "desc",
    ) -> tuple[list[tuple[LibraryEntry, Paper]], int]:
        """Paginate the user's library.

        ``cursor_entry_id`` is the id of the last entry from the previous page.
        We look up that pivot inside the query so the saved_at / title / journal
        comparison uses the column's native type (no string round-tripping
        across SQLite/Postgres differences).
        """
        stmt = (
            select(LibraryEntry, Paper)
            .join(Paper, Paper.id == LibraryEntry.paper_id)
            .where(LibraryEntry.user_id == user_id)
        )

        if search:
            like = f"%{search.strip()}%"
            stmt = stmt.where(or_(Paper.title.ilike(like), Paper.journal.ilike(like)))
        if design_type:
            stmt = stmt.where(Paper.design == design_type)
        if saved_after is not None:
            stmt = stmt.where(LibraryEntry.saved_at >= saved_after)

        sort_column: Any
        if sort_by == "title":
            sort_column = Paper.title
        elif sort_by == "journal":
            sort_column = Paper.journal
        else:
            sort_column = LibraryEntry.saved_at

        if cursor_entry_id is not None:
            # Resolve the pivot by id; reuse its sort column value + id so the
            # comparison is on native column types (correct on both Postgres
            # timestamptz and SQLite datetime-as-text).
            pivot_row = await self.db.execute(
                select(LibraryEntry, Paper)
                .join(Paper, Paper.id == LibraryEntry.paper_id)
                .where(LibraryEntry.id == cursor_entry_id, LibraryEntry.user_id == user_id),
            )
            pivot = pivot_row.first()
            if pivot is not None:
                pivot_entry, pivot_paper = pivot
                if sort_by == "title":
                    pivot_value: Any = pivot_paper.title
                elif sort_by == "journal":
                    pivot_value = pivot_paper.journal
                else:
                    pivot_value = pivot_entry.saved_at
                if sort_dir == "desc":
                    stmt = stmt.where(
                        or_(
                            sort_column < pivot_value,
                            and_(
                                sort_column == pivot_value,
                                LibraryEntry.id < pivot_entry.id,
                            ),
                        ),
                    )
                else:
                    stmt = stmt.where(
                        or_(
                            sort_column > pivot_value,
                            and_(
                                sort_column == pivot_value,
                                LibraryEntry.id > pivot_entry.id,
                            ),
                        ),
                    )

        if sort_dir == "desc":
            stmt = stmt.order_by(sort_column.desc(), LibraryEntry.id.desc())
        else:
            stmt = stmt.order_by(sort_column.asc(), LibraryEntry.id.asc())
        stmt = stmt.limit(limit + 1)

        result = await self.db.execute(stmt)
        rows = [(row[0], row[1]) for row in result.all()]

        count_stmt = select(func.count()).select_from(
            select(LibraryEntry.id)
            .where(LibraryEntry.user_id == user_id)
            .subquery(),
        )
        total = (await self.db.execute(count_stmt)).scalar_one()

        return rows, total

    async def membership(
        self,
        user_id: UUID,
        paper_id: UUID,
    ) -> LibraryEntry | None:
        return await self.get_by_user_and_paper(user_id, paper_id)
