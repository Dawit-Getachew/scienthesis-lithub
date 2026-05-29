# Scienthesis LitHub

Central library service for the Scienthesis platform. Single source of truth for a user's saved papers across LitPulse, LitPortal, and sibling apps (LitScreen, LitForum, LitScholar, ...).

## Responsibilities

- Canonical paper metadata (`papers` table, deduped by PMID or DOI)
- Per-user library entries (`library_entries` table — `(user_id, paper_id)` unique)
- Per-user folders (`folders` table — including an auto-created "Inbox")
- Cross-app paper-membership lookup (used by LitPulse to show "also in LitPortal collection X" and vice-versa)

## Stack

- FastAPI + async SQLAlchemy + asyncpg + Alembic
- PostgreSQL (dedicated `scienthesis_lithub` database)
- Redis (paper-metadata cache, idempotency keys)
- PyJWT (RS256 verification via Identity's JWKS)

## Local development

```
cp .env.example .env
# Edit .env so IDENTITY_BASE_URL points at a running Identity Service.
uv sync
alembic upgrade head
uvicorn src.main:app --reload --port 8200
```

## Auth

All user-facing endpoints validate the inbound Bearer token against the Identity Service's JWKS (`audience=lithub`). Internal endpoints (`/api/v1/internal/*`) additionally require a valid `X-Service-Token` HS256 token signed with `SERVICE_TOKEN_SECRET`.

## Cross-app guarantee

A paper saved on LitPulse (`POST /api/library/save` → LitPulse BFF → LitHub) becomes immediately visible when LitPortal lists the user's collections (LitPortal BFF augments collection responses with LitHub metadata). The same is true in reverse — a paper added to a LitPortal collection is dual-written to LitHub by the LitPortal BFF, so it appears in LitPulse's `GET /api/library`.
