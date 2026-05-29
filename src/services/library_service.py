"""Library service — orchestrates paper upsert + library-entry upsert + folder mapping."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from src.core.exceptions import (
    FolderNotFoundError,
    InvalidPaperIdentifiersError,
    LibraryEntryNotFoundError,
)
from src.models.folder import Folder
from src.models.library_entry import LibraryEntry
from src.models.paper import Paper
from src.repositories.folder_repo import FolderRepository
from src.repositories.library_repo import LibraryRepository, SortBy, SortDir
from src.repositories.paper_repo import PaperRepository
from src.schemas.library import (
    LibraryArticle,
    LibraryListResponse,
    MembershipResponse,
    SavePaperRequest,
    SavePaperResponse,
)

logger = structlog.get_logger(__name__)


class LibraryService:
    """Top-level orchestrator for save/list/move/delete."""

    def __init__(
        self,
        *,
        papers: PaperRepository,
        library: LibraryRepository,
        folders: FolderRepository,
    ) -> None:
        self._papers = papers
        self._library = library
        self._folders = folders

    # ── Save ─────────────────────────────────────────────────────────

    async def save(self, user_id: UUID, body: SavePaperRequest) -> SavePaperResponse:
        if not body.pmid and not body.doi:
            raise InvalidPaperIdentifiersError(
                "At least one of 'pmid' or 'doi' is required.",
            )

        paper = await self._papers.upsert(
            pmid=body.pmid,
            doi=body.doi,
            attrs={
                "title": body.title,
                "abstract": body.abstract,
                "journal": body.journal,
                "pub_date": _pub_date_from_body(body),
                "authors": body.authors,
                "url": body.url,
                "ai_summary": body.ai_summary,
                "design": body.design,
                "design_tags": body.design_tags,
                "study_design": body.study_design,
                "raw_metadata": _raw_metadata_from_body(body),
            },
        )

        folder = await self._folders.get_or_create(user_id, body.folder or "Inbox")
        entry, _ = await self._library.upsert(
            user_id=user_id,
            paper_id=paper.id,
            folder_id=folder.id,
            attrs={
                "source": body.source,
                "recommended": body.recommended,
                "selected": body.selected,
                "full_text_status": body.full_text_status,
                "best_full_text_url": body.best_full_text_url,
                "answer_context_id": body.answer_context_id,
                "portal_engine_record_id": body.portal_engine_record_id,
                "notes": body.notes,
            },
        )

        dedup_key = _dedup_key(paper.pmid, paper.doi)
        return SavePaperResponse(
            message="Article saved to library",
            article_id=str(paper.id),
            paper_id=paper.id,
            library_entry_id=entry.id,
            dedup_key=dedup_key,
            saved_at=entry.saved_at,
        )

    # ── List ─────────────────────────────────────────────────────────

    async def list(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        search: str | None,
        design_type: str | None,
        saved_after: datetime | None,
        sort_by: SortBy,
        sort_dir: SortDir,
    ) -> LibraryListResponse:
        cursor_entry_id = _decode_cursor(cursor) if cursor else None

        rows, total = await self._library.list_with_papers(
            user_id=user_id,
            limit=limit,
            cursor_entry_id=cursor_entry_id,
            search=search,
            design_type=design_type,
            saved_after=saved_after,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

        has_more = len(rows) > limit
        rows = rows[:limit]

        folder_ids = {entry.folder_id for entry, _ in rows if entry.folder_id is not None}
        folder_name_by_id: dict[UUID, str] = {}
        if folder_ids:
            for fid in folder_ids:
                folder = await self._folders.get(user_id, fid)
                if folder is not None:
                    folder_name_by_id[fid] = folder.name

        articles = [
            _to_article(entry, paper, folder_name_by_id) for entry, paper in rows
        ]

        next_cursor: str | None = None
        if has_more and rows:
            last_entry, _ = rows[-1]
            next_cursor = _encode_cursor(last_entry)

        return LibraryListResponse(articles=articles, total=total, next_cursor=next_cursor)

    # ── Membership ───────────────────────────────────────────────────

    async def membership(
        self,
        user_id: UUID,
        *,
        pmid: str | None,
        doi: str | None,
    ) -> MembershipResponse:
        if not pmid and not doi:
            raise InvalidPaperIdentifiersError(
                "Membership lookup requires at least one of pmid or doi.",
            )
        paper: Paper | None = None
        if pmid:
            paper = await self._papers.get_by_pmid(pmid)
        if paper is None and doi:
            paper = await self._papers.get_by_doi(doi)
        if paper is None:
            return MembershipResponse(paper_id=None, in_library=False)
        entry = await self._library.membership(user_id, paper.id)
        if entry is None:
            return MembershipResponse(paper_id=paper.id, in_library=False)
        folder_name = None
        if entry.folder_id is not None:
            folder = await self._folders.get(user_id, entry.folder_id)
            if folder is not None:
                folder_name = folder.name
        return MembershipResponse(
            paper_id=paper.id,
            in_library=True,
            library_entry_id=entry.id,
            folder=folder_name,
            saved_at=entry.saved_at,
            source=entry.source,
        )

    # ── Delete / move ────────────────────────────────────────────────

    async def delete_by_entry_id(self, user_id: UUID, entry_id: UUID) -> None:
        ok = await self._library.delete(user_id, entry_id)
        if not ok:
            raise LibraryEntryNotFoundError(f"Library entry {entry_id} not found.")

    async def delete_by_identifier(
        self, user_id: UUID, *, pmid: str | None, doi: str | None,
    ) -> None:
        if not pmid and not doi:
            raise InvalidPaperIdentifiersError("Delete requires pmid or doi.")
        paper: Paper | None = None
        if pmid:
            paper = await self._papers.get_by_pmid(pmid)
        if paper is None and doi:
            paper = await self._papers.get_by_doi(doi)
        if paper is None:
            raise LibraryEntryNotFoundError("No paper matches the supplied identifier.")
        entry = await self._library.membership(user_id, paper.id)
        if entry is None:
            raise LibraryEntryNotFoundError("Paper is not in this user's library.")
        await self._library.delete(user_id, entry.id)

    async def move_to_folder(
        self,
        user_id: UUID,
        *,
        entry_id: UUID | None,
        pmid: str | None,
        doi: str | None,
        target_folder: str,
    ) -> LibraryArticle:
        target = await self._folders.get_or_create(user_id, target_folder)
        if entry_id is not None:
            updated = await self._library.move(user_id, entry_id, target.id)
            if updated is None:
                raise LibraryEntryNotFoundError(f"Library entry {entry_id} not found.")
            paper = await self._papers.get_by_id(updated.paper_id)
        else:
            if not pmid and not doi:
                raise InvalidPaperIdentifiersError("Move requires entry_id, pmid, or doi.")
            paper = None
            if pmid:
                paper = await self._papers.get_by_pmid(pmid)
            if paper is None and doi:
                paper = await self._papers.get_by_doi(doi)
            if paper is None:
                raise LibraryEntryNotFoundError("No paper matches the supplied identifier.")
            entry = await self._library.membership(user_id, paper.id)
            if entry is None:
                raise LibraryEntryNotFoundError("Paper is not in this user's library.")
            updated = await self._library.move(user_id, entry.id, target.id)
        assert updated is not None and paper is not None
        return _to_article(updated, paper, {target.id: target.name})


# ── Helpers ─────────────────────────────────────────────────────────


def _dedup_key(pmid: str | None, doi: str | None) -> str:
    if pmid:
        return f"pmid:{pmid}"
    if doi:
        return f"doi:{doi}"
    return ""


def _pub_date_from_body(body: SavePaperRequest) -> str | None:
    if body.pub_date:
        return body.pub_date
    if body.year:
        return str(body.year)
    return None


def _raw_metadata_from_body(body: SavePaperRequest) -> dict | None:
    extras: dict[str, Any] = {}
    if body.publication_type:
        extras["publication_type"] = body.publication_type
    if body.year:
        extras["year"] = body.year
    return extras or None


def _to_article(
    entry: LibraryEntry,
    paper: Paper,
    folder_name_by_id: dict[UUID, str],
) -> LibraryArticle:
    folder_name = "Inbox"
    if entry.folder_id is not None:
        folder_name = folder_name_by_id.get(entry.folder_id, "Inbox")
    return LibraryArticle(
        pmid=paper.pmid,
        doi=paper.doi,
        title=paper.title,
        journal=paper.journal,
        pub_date=paper.pub_date,
        authors=paper.authors,
        abstract=paper.abstract,
        ai_summary=paper.ai_summary,
        design_tags=paper.design_tags,
        url=paper.url,
        saved_at=entry.saved_at,
        folder=folder_name,
        paper_id=paper.id,
        library_entry_id=entry.id,
        source=entry.source,  # type: ignore[arg-type]
        full_text_status=entry.full_text_status,  # type: ignore[arg-type]
        best_full_text_url=entry.best_full_text_url,
        recommended=entry.recommended,
        selected=entry.selected,
        answer_context_id=entry.answer_context_id,
        portal_engine_record_id=entry.portal_engine_record_id,
        notes=entry.notes,
    )


def _encode_cursor(entry: LibraryEntry) -> str:
    """Encode the last-entry-id only.

    The next page does a server-side lookup of this entry to obtain the pivot
    sort value, so we never round-trip column values through string formats —
    that's what kept SQLite vs. Postgres semantics consistent for tz-aware
    timestamps.
    """
    return str(entry.id)


def _decode_cursor(cursor: str) -> UUID | None:
    try:
        return UUID(cursor.strip())
    except (TypeError, ValueError):
        return None
