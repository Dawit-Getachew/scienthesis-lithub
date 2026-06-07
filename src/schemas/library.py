"""Pydantic schemas for the LitHub library API.

The shapes here match what the LitPulse `GET /api/library` endpoint returns
to its frontend so the LitPulse BFF can pass through unchanged. The same
shapes carry enough fields to satisfy LitPortal's ``CollectionItemResponse``
when the LitPortal BFF asks for paper metadata in batch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# Accept any surface tag / status string. The backing DB columns are free
# String(32) with no constraint; strict Literals here previously rejected
# legitimate cross-app saves with HTTP 422 — e.g. LitPulse's LitScreen "keep"
# sends source="screening" (not in the old list), so the service-to-service
# mirror silently failed and kept articles never reached the central library.
# Keeping these as plain str also prevents an output-validation 422 on the
# read path when an already-stored entry carries a non-canonical value.
SaveSource = str
FullTextStatus = str


# ── Requests ────────────────────────────────────────────────────────


class SavePaperRequest(BaseModel):
    """Body for ``POST /api/v1/library/save``.

    Mirrors LitPulse's ``LibrarySavePayload`` so the LitPulse BFF can forward
    the inbound body unchanged. PMID or DOI is required (422 otherwise).
    """

    pmid: str | None = Field(default=None, max_length=64)
    doi: str | None = Field(default=None, max_length=255)
    folder: str = Field(default="Inbox", max_length=255)
    title: str | None = Field(default=None, max_length=2048)
    abstract: str | None = None
    journal: str | None = Field(default=None, max_length=512)
    pub_date: str | None = Field(default=None, max_length=64)
    year: int | None = None
    authors: list[str] | str | None = None
    url: str | None = None
    ai_summary: str | None = None
    design: str | None = Field(default=None, max_length=128)
    design_tags: list[str] | None = None
    study_design: str | None = Field(default=None, max_length=64)
    publication_type: list[str] | None = None
    full_text_status: FullTextStatus | None = None
    best_full_text_url: str | None = None
    recommended: bool = False
    selected: bool = False
    source: SaveSource = "search"
    answer_context_id: str | None = Field(default=None, max_length=128)
    portal_engine_record_id: str | None = Field(default=None, max_length=128)
    notes: str | None = None

    @field_validator("pmid", "doi")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip()
        return v or None


class UpdateLibraryEntryRequest(BaseModel):
    folder: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    full_text_status: FullTextStatus | None = None
    best_full_text_url: str | None = None
    recommended: bool | None = None
    selected: bool | None = None


class MoveLibraryEntryRequest(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    paper_id: UUID | None = None
    target_folder: str = Field(..., max_length=255)


# ── Responses ───────────────────────────────────────────────────────


class SavePaperResponse(BaseModel):
    """Returned from ``POST /api/v1/library/save``.

    LitPulse's existing response carries ``message``, ``article_id``,
    ``dedup_key``, ``saved_at``. We mirror that exactly so the LitPulse BFF
    can pass through; ``paper_id`` and ``library_entry_id`` are additive
    fields that LitPortal uses.
    """

    message: str = "Article saved to library"
    article_id: str
    paper_id: UUID
    library_entry_id: UUID
    dedup_key: str
    saved_at: datetime


class LibraryArticle(BaseModel):
    """Single article row in the paginated list. Field set matches LitPulse `/api/library`."""

    pmid: str | None
    doi: str | None
    title: str
    journal: str | None
    pub_date: str | None
    authors: str | list[str] | None
    abstract: str | None
    ai_summary: str | None
    design_tags: list[str] | None
    mesh_terms: list[str] | None = None
    url: str | None
    saved_at: datetime
    folder: str
    # Additive fields preserved for downstream consumers (LitPortal BFF).
    paper_id: UUID
    library_entry_id: UUID
    source: SaveSource
    full_text_status: FullTextStatus | None
    best_full_text_url: str | None
    recommended: bool
    selected: bool
    answer_context_id: str | None
    portal_engine_record_id: str | None
    notes: str | None


class LibraryListResponse(BaseModel):
    """Returned from ``GET /api/v1/library``. Cursor format: ``<sort_value>|<entry_id>``."""

    articles: list[LibraryArticle]
    total: int
    next_cursor: str | None


# ── Paper canonical responses ──────────────────────────────────────


class PaperDetail(BaseModel):
    """Canonical paper detail returned from ``GET /api/v1/papers/{id}``."""

    paper_id: UUID
    pmid: str | None
    doi: str | None
    title: str
    abstract: str | None
    journal: str | None
    pub_date: str | None
    authors: list[str] | str | None
    url: str | None
    ai_summary: str | None
    design: str | None
    design_tags: list[str] | None
    study_design: str | None
    raw_metadata: dict | None


class PaperLookupResponse(BaseModel):
    paper: PaperDetail | None
    exists: bool


# ── Folder responses ───────────────────────────────────────────────


class FolderResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    position: int
    created_at: datetime
    updated_at: datetime
    entry_count: int = 0


class FolderListResponse(BaseModel):
    folders: list[FolderResponse]


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: UUID | None = None


class MessageResponse(BaseModel):
    message: str


# ── Membership lookup (cross-app glue) ─────────────────────────────


class MembershipResponse(BaseModel):
    """Returned from ``GET /api/v1/internal/library/membership``."""

    paper_id: UUID | None
    in_library: bool
    library_entry_id: UUID | None = None
    folder: str | None = None
    saved_at: datetime | None = None
    source: SaveSource | None = None
