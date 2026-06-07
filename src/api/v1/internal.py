"""Service-to-service internal API.

Used by BFFs for cross-app membership lookups and bulk migration of legacy
library data. All endpoints require a valid ``X-Service-Token``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.core.deps import (
    get_folder_repo,
    get_library_service,
    get_paper_repo,
    require_service_token,
)
from src.core.exceptions import InvalidPaperIdentifiersError, LibraryEntryNotFoundError
from src.repositories.folder_repo import FolderRepository
from src.repositories.paper_repo import PaperRepository
from src.schemas.internal import (
    BulkImportRequest,
    BulkImportResponse,
    InternalPapersBulkRequest,
    InternalPapersBulkResponse,
    InternalSaveRequest,
)
from src.schemas.library import (
    LibraryArticle,
    LibraryListResponse,
    MembershipResponse,
    PaperDetail,
    SavePaperResponse,
)
from src.services.library_service import LibraryService

InternalSortBy = Literal["saved_at", "title", "journal"]
InternalSortDir = Literal["asc", "desc"]

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/library/membership", response_model=MembershipResponse)
async def membership_lookup(
    user_id: UUID = Query(...),
    pmid: str | None = Query(default=None),
    doi: str | None = Query(default=None),
    service: LibraryService = Depends(get_library_service),
) -> MembershipResponse:
    """Is paper(pmid|doi) in user_id's library?"""
    if not pmid and not doi:
        raise InvalidPaperIdentifiersError("Provide pmid and/or doi.")
    return await service.membership(user_id, pmid=pmid, doi=doi)


@router.post("/library/save", response_model=SavePaperResponse)
async def internal_save(
    body: InternalSaveRequest,
    service: LibraryService = Depends(get_library_service),
) -> SavePaperResponse:
    """Service-to-service single-paper save on behalf of ``user_id``.

    Used by the LitPulse and LitPortal BFFs to mirror a save into the central
    library keyed by the user's Identity ``sub`` — no user bearer token needed.
    Idempotent: re-saving the same paper upserts the existing entry.
    """
    return await service.save(body.user_id, body.item)


@router.get("/library", response_model=LibraryListResponse)
async def internal_list(
    user_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
    search: str | None = Query(default=None),
    design_type: str | None = Query(default=None),
    saved_after: datetime | None = Query(default=None),
    sort_by: InternalSortBy = Query(default="saved_at"),
    sort_dir: InternalSortDir = Query(default="desc"),
    service: LibraryService = Depends(get_library_service),
) -> LibraryListResponse:
    """Service-to-service paginated library list for ``user_id`` (Identity sub).

    Lets a BFF (e.g. LitPulse) read the canonical central library for a user
    regardless of the inbound user token type during the Identity cutover.
    """
    return await service.list(
        user_id,
        limit=limit,
        cursor=cursor,
        search=search,
        design_type=design_type,
        saved_after=saved_after,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.delete("/library")
async def internal_delete(
    user_id: UUID = Query(...),
    pmid: str | None = Query(default=None),
    doi: str | None = Query(default=None),
    service: LibraryService = Depends(get_library_service),
) -> dict:
    """Service-to-service delete of a paper from ``user_id``'s library by pmid|doi.

    Used by the LitPortal BFF so a user can remove a paper from the unified
    central library (the read-through "Saved from LitPulse" collection).
    Idempotent: a paper that is already absent still returns success.
    """
    if not pmid and not doi:
        raise InvalidPaperIdentifiersError("Provide pmid and/or doi.")
    try:
        await service.delete_by_identifier(user_id, pmid=pmid, doi=doi)
    except LibraryEntryNotFoundError:
        pass  # idempotent — already removed
    return {"message": "Library entry removed."}


@router.post("/papers/bulk", response_model=InternalPapersBulkResponse)
async def internal_papers_bulk(
    body: InternalPapersBulkRequest,
    repo: PaperRepository = Depends(get_paper_repo),
) -> InternalPapersBulkResponse:
    """Service-to-service bulk paper-metadata fetch by id (papers are global).

    Used by the LitPortal BFF to enrich collection-item responses with the
    canonical LitHub paper metadata.
    """
    papers = await repo.get_many(body.paper_ids)
    return InternalPapersBulkResponse(
        papers=[
            PaperDetail(
                paper_id=p.id,
                pmid=p.pmid,
                doi=p.doi,
                title=p.title,
                abstract=p.abstract,
                journal=p.journal,
                pub_date=p.pub_date,
                authors=p.authors,
                url=p.url,
                ai_summary=p.ai_summary,
                design=p.design,
                design_tags=p.design_tags,
                study_design=p.study_design,
                raw_metadata=p.raw_metadata,
            )
            for p in papers
        ],
    )


@router.post("/library/bulk-import", response_model=BulkImportResponse)
async def bulk_import(
    body: BulkImportRequest,
    service: LibraryService = Depends(get_library_service),
    folder_repo: FolderRepository = Depends(get_folder_repo),
) -> BulkImportResponse:
    """Idempotent bulk-import of a user's pre-existing library.

    Used by BFFs to backfill legacy data on first contact. Skips items missing
    both PMID and DOI; existing entries are upgraded with richer metadata
    rather than duplicated. Returns the resulting articles so callers can
    confirm the import.
    """
    imported = 0
    skipped_dup = 0
    skipped_invalid = 0
    articles: list[LibraryArticle] = []

    for item in body.items:
        if not item.pmid and not item.doi:
            skipped_invalid += 1
            continue
        try:
            before = await service.membership(
                body.user_id, pmid=item.pmid, doi=item.doi,
            )
        except InvalidPaperIdentifiersError:
            skipped_invalid += 1
            continue
        was_present = before.in_library

        response = await service.save(body.user_id, item)
        # Refetch via membership to reuse the response builder paths.
        membership = await service.membership(
            body.user_id, pmid=item.pmid, doi=item.doi,
        )
        folder_name = membership.folder or "Inbox"
        # Build a LibraryArticle for the response.
        articles.append(
            LibraryArticle(
                pmid=item.pmid,
                doi=item.doi,
                title=item.title or "Untitled paper",
                journal=item.journal,
                pub_date=item.pub_date,
                authors=item.authors,
                abstract=item.abstract,
                ai_summary=item.ai_summary,
                design_tags=item.design_tags,
                url=item.url,
                saved_at=response.saved_at,
                folder=folder_name,
                paper_id=response.paper_id,
                library_entry_id=response.library_entry_id,
                source=item.source,
                full_text_status=item.full_text_status,
                best_full_text_url=item.best_full_text_url,
                recommended=item.recommended,
                selected=item.selected,
                answer_context_id=item.answer_context_id,
                portal_engine_record_id=item.portal_engine_record_id,
                notes=item.notes,
            ),
        )
        if was_present:
            skipped_dup += 1
        else:
            imported += 1

    return BulkImportResponse(
        user_id=body.user_id,
        imported=imported,
        skipped_duplicate=skipped_dup,
        skipped_invalid=skipped_invalid,
        articles=articles,
    )
