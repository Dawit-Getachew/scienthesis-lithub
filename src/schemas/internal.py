"""Schemas for the internal (service-to-service) API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from src.schemas.library import LibraryArticle, PaperDetail, SavePaperRequest


class BulkImportRequest(BaseModel):
    """Body for ``POST /api/v1/internal/library/bulk-import``.

    Used by BFFs to backfill a user's pre-existing library on first contact.
    The receiver dedupes against ``(user_id, paper_id)`` so multiple imports
    of the same paper are idempotent.
    """

    user_id: UUID
    items: list[SavePaperRequest]


class BulkImportResponse(BaseModel):
    user_id: UUID
    imported: int
    skipped_duplicate: int
    skipped_invalid: int
    articles: list[LibraryArticle]


class InternalSaveRequest(BaseModel):
    """Body for ``POST /api/v1/internal/library/save``.

    Service-to-service single-paper save on behalf of ``user_id`` (the user's
    Identity ``sub``). Used by the LitPulse and LitPortal BFFs to mirror a save
    into the central library without needing the user's bearer token.
    """

    user_id: UUID
    item: SavePaperRequest


class InternalPapersBulkRequest(BaseModel):
    """Body for ``POST /api/v1/internal/papers/bulk`` — papers by id (global, not user-scoped)."""

    paper_ids: list[UUID]


class InternalPapersBulkResponse(BaseModel):
    papers: list[PaperDetail]
