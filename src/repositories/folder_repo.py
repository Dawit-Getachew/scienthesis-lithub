"""Folder repository — per-user CRUD."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.folder import Folder
from src.models.library_entry import LibraryEntry


class FolderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: UUID, folder_id: UUID) -> Folder | None:
        stmt = select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_name(
        self, user_id: UUID, name: str, parent_id: UUID | None = None,
    ) -> Folder | None:
        normalized = name.strip()
        stmt = select(Folder).where(
            Folder.user_id == user_id,
            Folder.name == normalized,
            Folder.parent_id.is_(parent_id) if parent_id is None else Folder.parent_id == parent_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[Folder]:
        stmt = select(Folder).where(Folder.user_id == user_id).order_by(
            Folder.position, Folder.name,
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def create(
        self, user_id: UUID, name: str, parent_id: UUID | None = None,
    ) -> Folder:
        folder = Folder(user_id=user_id, name=name.strip(), parent_id=parent_id)
        self.db.add(folder)
        await self.db.commit()
        await self.db.refresh(folder)
        return folder

    async def get_or_create(
        self, user_id: UUID, name: str, parent_id: UUID | None = None,
    ) -> Folder:
        existing = await self.get_by_name(user_id, name, parent_id=parent_id)
        if existing is not None:
            return existing
        return await self.create(user_id, name, parent_id=parent_id)

    async def entry_counts(self, user_id: UUID) -> dict[UUID, int]:
        stmt = (
            select(LibraryEntry.folder_id, func.count())
            .where(LibraryEntry.user_id == user_id)
            .group_by(LibraryEntry.folder_id)
        )
        result = await self.db.execute(stmt)
        return {row[0]: row[1] for row in result.all() if row[0] is not None}
