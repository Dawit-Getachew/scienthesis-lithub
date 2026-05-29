"""Paper metadata lookups — by id, PMID, DOI, or bulk."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.core.deps import get_current_user, get_paper_repo
from src.core.exceptions import PaperNotFoundError
from src.repositories.paper_repo import PaperRepository
from src.schemas.library import PaperDetail, PaperLookupResponse

router = APIRouter(prefix="/papers", tags=["papers"], dependencies=[Depends(get_current_user)])


def _to_detail(paper) -> PaperDetail:  # noqa: ANN001
    return PaperDetail(
        paper_id=paper.id,
        pmid=paper.pmid,
        doi=paper.doi,
        title=paper.title,
        abstract=paper.abstract,
        journal=paper.journal,
        pub_date=paper.pub_date,
        authors=paper.authors,
        url=paper.url,
        ai_summary=paper.ai_summary,
        design=paper.design,
        design_tags=paper.design_tags,
        study_design=paper.study_design,
        raw_metadata=paper.raw_metadata,
    )


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: UUID,
    repo: PaperRepository = Depends(get_paper_repo),
) -> PaperDetail:
    paper = await repo.get_by_id(paper_id)
    if paper is None:
        raise PaperNotFoundError(f"No paper with id {paper_id}.")
    return _to_detail(paper)


@router.get("/by-pmid/{pmid}", response_model=PaperLookupResponse)
async def get_paper_by_pmid(
    pmid: str,
    repo: PaperRepository = Depends(get_paper_repo),
) -> PaperLookupResponse:
    paper = await repo.get_by_pmid(pmid)
    if paper is None:
        return PaperLookupResponse(paper=None, exists=False)
    return PaperLookupResponse(paper=_to_detail(paper), exists=True)


@router.get("/by-doi/{doi:path}", response_model=PaperLookupResponse)
async def get_paper_by_doi(
    doi: str,
    repo: PaperRepository = Depends(get_paper_repo),
) -> PaperLookupResponse:
    paper = await repo.get_by_doi(doi)
    if paper is None:
        return PaperLookupResponse(paper=None, exists=False)
    return PaperLookupResponse(paper=_to_detail(paper), exists=True)


class BulkPapersRequest(BaseModel):
    paper_ids: list[UUID]


class BulkPapersResponse(BaseModel):
    papers: list[PaperDetail]


@router.post("/bulk", response_model=BulkPapersResponse)
async def bulk_get_papers(
    body: BulkPapersRequest,
    repo: PaperRepository = Depends(get_paper_repo),
) -> BulkPapersResponse:
    papers = await repo.get_many(body.paper_ids)
    return BulkPapersResponse(papers=[_to_detail(p) for p in papers])
