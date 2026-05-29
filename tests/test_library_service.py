"""Service-level tests for LibraryService against an in-memory SQLite DB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.core.exceptions import (
    InvalidPaperIdentifiersError,
    LibraryEntryNotFoundError,
)
from src.repositories.folder_repo import FolderRepository
from src.repositories.library_repo import LibraryRepository
from src.repositories.paper_repo import PaperRepository
from src.schemas.library import SavePaperRequest
from src.services.library_service import LibraryService


@pytest.fixture
def service(db_session):
    return LibraryService(
        papers=PaperRepository(db_session),
        library=LibraryRepository(db_session),
        folders=FolderRepository(db_session),
    )


def _sample(**overrides) -> SavePaperRequest:
    base = dict(
        pmid="12345678",
        title="Sample Paper",
        journal="Sample Journal",
        pub_date="2024-01-15",
        authors=["A Author", "B Author"],
        abstract="An abstract.",
        ai_summary="A short summary.",
        design_tags=["RCT"],
        url="https://example.com/p/12345678",
        full_text_status="available",
        source="search",
    )
    base.update(overrides)
    return SavePaperRequest(**base)


# ── Save ───────────────────────────────────────────────────────────


async def test_save_creates_paper_and_library_entry(service, test_user_id):
    response = await service.save(test_user_id, _sample())
    assert response.article_id
    assert response.dedup_key == "pmid:12345678"
    assert response.message == "Article saved to library"


async def test_save_without_identifiers_raises(service, test_user_id):
    with pytest.raises(InvalidPaperIdentifiersError):
        await service.save(test_user_id, SavePaperRequest(title="No id"))


async def test_save_dedupes_on_pmid(service, test_user_id):
    first = await service.save(test_user_id, _sample())
    second = await service.save(test_user_id, _sample(folder="Cardio"))
    assert second.paper_id == first.paper_id
    assert second.library_entry_id == first.library_entry_id


async def test_save_dedupes_on_doi(service, test_user_id):
    first = await service.save(test_user_id, _sample(pmid=None, doi="10.1234/abc.001"))
    second = await service.save(
        test_user_id, _sample(pmid=None, doi="https://doi.org/10.1234/abc.001"),
    )
    assert second.paper_id == first.paper_id


async def test_save_pmid_dedup_takes_precedence_over_doi(service, test_user_id):
    a = await service.save(test_user_id, _sample(pmid="111", doi="10.x/aa"))
    b = await service.save(test_user_id, _sample(pmid="111", doi="10.x/bb"))
    assert a.paper_id == b.paper_id


async def test_save_separate_users_have_separate_libraries(service):
    u1, u2 = uuid4(), uuid4()
    r1 = await service.save(u1, _sample())
    r2 = await service.save(u2, _sample())
    assert r1.paper_id == r2.paper_id  # Same canonical paper.
    assert r1.library_entry_id != r2.library_entry_id  # Different library rows.


async def test_save_updates_source_on_re_save(service, test_user_id):
    await service.save(test_user_id, _sample(source="search"))
    response = await service.save(test_user_id, _sample(source="litportal"))
    listing = await service.list(
        test_user_id, limit=50, cursor=None, search=None,
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    assert listing.articles[0].source == "litportal"
    assert listing.articles[0].library_entry_id == response.library_entry_id


# ── Listing ────────────────────────────────────────────────────────


async def test_list_returns_saved_entries(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="1"))
    await service.save(test_user_id, _sample(pmid="2"))
    response = await service.list(
        test_user_id, limit=50, cursor=None, search=None,
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    assert response.total == 2
    pmids = {a.pmid for a in response.articles}
    assert pmids == {"1", "2"}
    assert response.next_cursor is None


async def test_list_cursor_pagination(service, test_user_id):
    import asyncio

    for i in range(5):
        await service.save(test_user_id, _sample(pmid=f"p{i}"))
        # Force distinct saved_at timestamps so cursor comparison is unambiguous.
        # Production saves are spread across real time; this sleep just mirrors
        # that for the in-memory test.
        await asyncio.sleep(0.01)
    page = await service.list(
        test_user_id, limit=2, cursor=None, search=None,
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    assert len(page.articles) == 2
    assert page.next_cursor is not None
    next_page = await service.list(
        test_user_id, limit=2, cursor=page.next_cursor, search=None,
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    assert len(next_page.articles) == 2
    seen = {a.pmid for a in page.articles} | {a.pmid for a in next_page.articles}
    assert len(seen) == 4


async def test_list_search_filter(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="1", title="Renal failure outcomes"))
    await service.save(test_user_id, _sample(pmid="2", title="Pediatric asthma"))
    response = await service.list(
        test_user_id, limit=50, cursor=None, search="renal",
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    titles = [a.title for a in response.articles]
    assert any("Renal" in t for t in titles)
    assert not any("Pediatric" in t for t in titles)


async def test_list_saved_after_filter(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="1"))
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    response = await service.list(
        test_user_id, limit=50, cursor=None, search=None,
        design_type=None, saved_after=cutoff, sort_by="saved_at", sort_dir="desc",
    )
    assert response.articles == []


async def test_list_isolated_per_user(service):
    u1, u2 = uuid4(), uuid4()
    await service.save(u1, _sample(pmid="1"))
    await service.save(u2, _sample(pmid="2"))
    r1 = await service.list(
        u1, limit=50, cursor=None, search=None,
        design_type=None, saved_after=None, sort_by="saved_at", sort_dir="desc",
    )
    assert {a.pmid for a in r1.articles} == {"1"}


# ── Membership / cross-app ─────────────────────────────────────────


async def test_membership_finds_user_paper(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="123"))
    membership = await service.membership(test_user_id, pmid="123", doi=None)
    assert membership.in_library is True
    assert membership.folder == "Inbox"


async def test_membership_unknown_paper_returns_in_library_false(service, test_user_id):
    membership = await service.membership(test_user_id, pmid="999", doi=None)
    assert membership.in_library is False
    assert membership.paper_id is None


async def test_membership_same_paper_different_user_returns_false(service):
    u1, u2 = uuid4(), uuid4()
    await service.save(u1, _sample(pmid="x"))
    membership = await service.membership(u2, pmid="x", doi=None)
    assert membership.in_library is False


async def test_membership_doi_lookup(service, test_user_id):
    await service.save(test_user_id, _sample(pmid=None, doi="10.1234/zzz"))
    membership = await service.membership(test_user_id, pmid=None, doi="10.1234/ZZZ")
    assert membership.in_library is True


# ── Delete / move ──────────────────────────────────────────────────


async def test_delete_by_pmid(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="42"))
    await service.delete_by_identifier(test_user_id, pmid="42", doi=None)
    membership = await service.membership(test_user_id, pmid="42", doi=None)
    assert membership.in_library is False


async def test_delete_unknown_raises(service, test_user_id):
    with pytest.raises(LibraryEntryNotFoundError):
        await service.delete_by_identifier(test_user_id, pmid="ghost", doi=None)


async def test_move_creates_folder_when_missing(service, test_user_id):
    await service.save(test_user_id, _sample(pmid="moveme"))
    article = await service.move_to_folder(
        test_user_id,
        entry_id=None,
        pmid="moveme",
        doi=None,
        target_folder="Cardiology",
    )
    assert article.folder == "Cardiology"
