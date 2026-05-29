"""Library API — save, list, delete, move."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.core.deps import AuthenticatedUser, get_current_user, get_library_service
from src.schemas.library import (
    LibraryListResponse,
    MessageResponse,
    MoveLibraryEntryRequest,
    SavePaperRequest,
    SavePaperResponse,
)
from src.services.library_service import LibraryService

SortByQ = Literal["saved_at", "title", "journal"]
SortDirQ = Literal["asc", "desc"]

router = APIRouter(prefix="/library", tags=["library"])


@router.post("/save", response_model=SavePaperResponse)
async def save_paper(
    body: SavePaperRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> SavePaperResponse:
    """Save a paper to the authenticated user's library."""
    return await service.save(user.id, body)


@router.get("", response_model=LibraryListResponse)
async def list_library(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    search: str | None = None,
    design_type: str | None = None,
    saved_after: datetime | None = None,
    sort_by: SortByQ = "saved_at",
    sort_dir: SortDirQ = "desc",
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> LibraryListResponse:
    """Paginated list of the user's saved papers."""
    return await service.list(
        user.id,
        limit=limit,
        cursor=cursor,
        search=search,
        design_type=design_type,
        saved_after=saved_after,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.delete("/{entry_id}", response_model=MessageResponse)
async def delete_entry(
    entry_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> MessageResponse:
    await service.delete_by_entry_id(user.id, entry_id)
    return MessageResponse(message="Library entry removed.")


@router.delete("/by-pmid/{pmid}", response_model=MessageResponse)
async def delete_by_pmid(
    pmid: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> MessageResponse:
    await service.delete_by_identifier(user.id, pmid=pmid, doi=None)
    return MessageResponse(message="Library entry removed.")


@router.delete("/by-doi/{doi:path}", response_model=MessageResponse)
async def delete_by_doi(
    doi: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> MessageResponse:
    await service.delete_by_identifier(user.id, pmid=None, doi=doi)
    return MessageResponse(message="Library entry removed.")


@router.post("/move", response_model=MessageResponse)
async def move_entry(
    body: MoveLibraryEntryRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: LibraryService = Depends(get_library_service),
) -> MessageResponse:
    await service.move_to_folder(
        user.id,
        entry_id=body.paper_id,  # body.paper_id is actually a library_entry_id alias
        pmid=body.pmid,
        doi=body.doi,
        target_folder=body.target_folder,
    )
    return MessageResponse(message="Library entry moved.")
