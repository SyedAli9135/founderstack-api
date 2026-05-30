# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FounderStack API is a **multi-tenant "Headless COO"** backend built with FastAPI. It orchestrates AI agents via LangGraph, supporting BYOK (Bring Your Own Key) Anthropic API keys, Clerk-based auth, Pinecone RAG, and MCP tool integrations via Nango. The platform is strictly org-isolated — every resource is scoped to an `org_id`.

## Commands

```bash
# Install dependencies (uses uv)
uv sync

# Run dev server
uvicorn app.main:app --reload

# Run all tests (must use uv run — system pytest lacks the venv deps)
uv run pytest

# Run a single test file
uv run pytest tests/path/to/test_file.py

# Run a single test by name
uv run pytest tests/path/to/test_file.py::test_function_name -v

# Run tests with coverage
uv run pytest --cov=app

# Database migrations
alembic upgrade head                                    # apply all pending migrations
alembic revision --autogenerate -m "describe_change"   # generate new migration from model changes
alembic downgrade -1                                    # roll back one migration
```

## Architecture

### Multi-Tenancy

Every meaningful model has an `org_id` column enforcing tenant isolation. The `Organization` model is the root tenant entity, linked to Clerk via `clerk_org_id`. Users are synced from Clerk via webhooks, not created directly.

### Authentication Flow

1. Clerk issues JWTs to the frontend.
2. The frontend sends the JWT as a Bearer token.
3. `app/core/auth.py::get_current_user` decodes the JWT **without signature verification** (relies on Clerk's upstream validation), extracts `sub` (the Clerk user ID), and looks up the synced `User` in the local DB.
4. `get_current_org` builds on top of `get_current_user` to also resolve the `Organization`.

**Important**: User/org records only exist locally after Clerk fires a webhook. If a user authenticates before the webhook is processed, `get_current_user` returns 401 "User profile not synchronized".

### Clerk Webhook Sync (`app/api/webhooks/clerk.py`)

Clerk events create/update/delete `Organization` and `User` rows via upsert (`on_conflict_do_update`). Membership events (`organizationMembership.created`) require the org to already exist — if not, they return 422 so Clerk retries. Webhook signatures are verified via Svix.

### LLM Client Resolution (`app/core/llm.py`)

Agents don't use an API key directly. Instead:
1. `resolve_llm_client(org_id, db, model)` fetches the org's encrypted Anthropic key from `ApiKeyRegistry`.
2. Decrypts it with Fernet (`app/core/security.py`).
3. Wraps it as a `partial(litellm.acompletion, api_key=..., model=...)` — a fully-bound async callable.
4. The result is cached in-process for 5 minutes (`_key_cache`).
5. Cache is invalidated immediately on key rotation/deletion via `invalidate_llm_cache(org_id)`.

Use `GetLLMClient("anthropic/claude-sonnet-4-6")` as a FastAPI dependency when the model is known at route definition time. Call `resolve_llm_client()` directly inside a handler when the model comes from request state (e.g. LangGraph workflow runs).

LiteLLM model strings follow the pattern `"anthropic/<model-id>"`.

### API Key Storage (`app/api/v1/endpoints/settings.py`)

BYOK flow: submit key → validate via Anthropic SDK (or mock path if prefix matches `sk-ant-test-`) → encrypt with Fernet → store in `ApiKeyRegistry` → update `Organization.active_api_key_id`. One Anthropic key per org (upsert pattern). Stored keys are never returned to the client — only the `key_prefix` (first 7 chars + `...`).

### Response Envelope Pattern

**All** API responses use one of two Pydantic schemas from `app/api/v1/schemas/base.py`:

- `SuccessEnvelope[T]` — `{ "status": "success", "message": "...", "data": T }`
- `ErrorEnvelope` — `{ "status": "error", "error": { "code": "...", "message": "...", "request_id": "..." } }`

Never return raw dicts or plain strings from route handlers.

### Error Handling

Three global handlers registered in `app/main.py`:
- `validation_exception_handler` → 422 with code `VALIDATION_ERROR`
- `http_exception_handler` → passes through status code, code `HTTP_EXCEPTION` (or `INTERNAL_SERVER_ERROR` for 5xx)
- `global_exception_handler` → 500 catch-all; masks details in production, exposes `str(exc)` in development

All handlers attach `request_id` from `request.state.request_id` (injected by `RequestIDMiddleware`).

### Data Models

All models inherit from `app/models/base.py::Base`, which provides `id` (UUID PK), `created_at`, and `updated_at` automatically.

Model files by domain:
- `identity.py` — `Organization`, `User`, `Session`
- `integration.py` — `MCPConnection`, `ApiKeyRegistry`
- `ai.py` — `Agent`, `AgentTeam`, `AgentTeamMember`, `Workflow`, `WorkflowRun`, `WorkflowStep`, `Approval`, `ApprovalDecision`
- `knowledge.py` — `Document`, `DocumentChunk`, `VectorNamespace`
- `observability.py` — `AuditLog`, `CostLedger`

### Router Layout

| Prefix | File | Purpose |
|--------|------|---------|
| `/api/v1/health` | `app/api/v1/health.py` | DB + Redis + Pinecone liveness |
| `/api/v1/auth` | `app/api/v1/endpoints/identity.py` | `/me`, `/dev-token` |
| `/api/v1/settings` | `app/api/v1/endpoints/settings.py` | API key CRUD |
| `/api/webhooks/clerk` | `app/api/webhooks/clerk.py` | Clerk event sync |

### Dev Token

`POST /api/v1/auth/dev-token` generates an unsigned JWT (HS256 with dummy secret) that works because `get_current_user` skips signature verification. **Disabled in production** via `APP_ENV` check.

## Environment Variables

Required in `.env` (see `app/config.py`):

```
APP_ENV=development
DATABASE_URL=postgresql+asyncpg://...
CLERK_SECRET_KEY=...
CLERK_PUBLISHABLE_KEY=...
CLERK_WEBHOOK_SECRET=...
ENCRYPTION_KEY=...          # Fernet key (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
PINECONE_API_KEY=...
```

Optional: `UPSTASH_REDIS_URL`, `UPSTASH_REDIS_TOKEN`, `NANGO_SECRET_KEY`, `COHERE_API_KEY`, `AWS_REGION`.

## Adding a New Feature

1. **New endpoint**: Create a router in `app/api/v1/endpoints/`, register it in `app/main.py` with `app.include_router(...)`.
2. **New model**: Add to the appropriate domain model file, then run `alembic revision --autogenerate -m "..."` and `alembic upgrade head`.
3. **Auth protection**: Use `current_user: User = Depends(get_current_user)` and/or `org: Organization = Depends(get_current_org)` as dependencies.
4. **LLM access in a route**: Use `llm: LLMCallable = Depends(GetLLMClient("anthropic/claude-sonnet-4-6"))`.
5. **LLM access in a LangGraph node**: Call `await resolve_llm_client(org_id, db, model)` directly.
