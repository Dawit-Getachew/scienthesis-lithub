"""Folder management."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.core.deps import AuthenticatedUser, get_current_user, get_folder_repo
from src.repositories.folder_repo import FolderRepository
from src.schemas.library import (
    CreateFolderRequest,
    FolderListResponse,
    FolderResponse,
)

router = APIRouter(prefix="/library/folders", tags=["library"])


@router.get("", response_model=FolderListResponse)
async def list_folders(
    user: AuthenticatedUser = Depends(get_current_user),
    repo: FolderRepository = Depends(get_folder_repo),
) -> FolderListResponse:
    folders = await repo.list_for_user(user.id)
    counts = await repo.entry_counts(user.id)
    return FolderListResponse(
        folders=[
            FolderResponse(
                id=f.id,
                name=f.name,
                parent_id=f.parent_id,
                position=f.position,
                created_at=f.created_at,
                updated_at=f.updated_at,
                entry_count=counts.get(f.id, 0),
            )
            for f in folders
        ],
    )


@router.post("", response_model=FolderResponse, status_code=201)
async def create_folder(
    body: CreateFolderRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: FolderRepository = Depends(get_folder_repo),
) -> FolderResponse:
    folder = await repo.get_or_create(user.id, body.name, parent_id=body.parent_id)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        position=folder.position,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        entry_count=0,
    )
