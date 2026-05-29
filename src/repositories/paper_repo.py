"""Paper repository — canonical paper-by-PMID/DOI deduplication."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.paper import Paper


def _normalize_pmid(pmid: str | None) -> str | None:
    if pmid is None:
        return None
    v = pmid.strip()
    return v or None


def _normalize_doi(doi: str | None) -> str | None:
    if doi is None:
        return None
    v = doi.strip().lower()
    if not v:
        return None
    if v.startswith("https://doi.org/"):
        v = v[len("https://doi.org/"):]
    elif v.startswith("http://doi.org/"):
        v = v[len("http://doi.org/"):]
    elif v.startswith("doi:"):
        v = v[len("doi:"):]
    return v


class PaperRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, paper_id: UUID) -> Paper | None:
        stmt = select(Paper).where(Paper.id == paper_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_pmid(self, pmid: str) -> Paper | None:
        normalized = _normalize_pmid(pmid)
        if not normalized:
            return None
        stmt = select(Paper).where(Paper.pmid == normalized)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_doi(self, doi: str) -> Paper | None:
        normalized = _normalize_doi(doi)
        if not normalized:
            return None
        stmt = select(Paper).where(Paper.doi == normalized)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_many(self, paper_ids: list[UUID]) -> list[Paper]:
        if not paper_ids:
            return []
        stmt = select(Paper).where(Paper.id.in_(paper_ids))
        return list((await self.db.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        pmid: str | None,
        doi: str | None,
        attrs: dict[str, Any],
    ) -> Paper:
        """Find-or-create by ``(pmid, doi)`` and merge non-empty attrs in.

        Dedup precedence: PMID > DOI. When a row exists, ``attrs`` only fills
        empty columns (never overwrites a non-null value), so once a paper
        has been enriched with rich metadata, a subsequent save with sparser
        metadata does not regress the row.
        """
        normalized_pmid = _normalize_pmid(pmid)
        normalized_doi = _normalize_doi(doi)
        if normalized_pmid is None and normalized_doi is None:
            raise ValueError("upsert requires at least pmid or doi")

        existing: Paper | None = None
        if normalized_pmid:
            existing = await self.get_by_pmid(normalized_pmid)
        if existing is None and normalized_doi:
            existing = await self.get_by_doi(normalized_doi)

        if existing is not None:
            changed = False
            if normalized_pmid and not existing.pmid:
                existing.pmid = normalized_pmid
                changed = True
            if normalized_doi and not existing.doi:
                existing.doi = normalized_doi
                changed = True
            for col, value in attrs.items():
                if value in (None, "", [], {}):
                    continue
                current = getattr(existing, col, None)
                if current in (None, "", [], {}):
                    setattr(existing, col, value)
                    changed = True
            if changed:
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        # Title is required at the model level; default to a placeholder when
        # the caller hasn't provided one yet (LitPortal sometimes saves with
        # only the identifier and lets the resolver enrich later).
        title = (attrs.get("title") or "Untitled paper").strip() or "Untitled paper"
        new = Paper(
            pmid=normalized_pmid,
            doi=normalized_doi,
            title=title,
            abstract=attrs.get("abstract"),
            journal=attrs.get("journal"),
            pub_date=attrs.get("pub_date"),
            authors=attrs.get("authors"),
            url=attrs.get("url"),
            ai_summary=attrs.get("ai_summary"),
            design=attrs.get("design"),
            design_tags=attrs.get("design_tags"),
            study_design=attrs.get("study_design"),
            raw_metadata=attrs.get("raw_metadata"),
        )
        self.db.add(new)
        await self.db.commit()
        await self.db.refresh(new)
        return new
