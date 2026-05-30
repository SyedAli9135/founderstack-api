import uuid
import jwt
import pytest
import asyncpg
from typing import AsyncGenerator

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.base import Base
from app.core.database import get_db
from app.main import app

TEST_DB_URL = "postgresql+asyncpg://postgres:password@localhost:5440/founderstack_test"
_ADMIN_DSN = "postgresql://postgres:password@localhost:5440/postgres"


# ---------------------------------------------------------------------------
# Session-level infrastructure
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
async def ensure_test_db():
    """Creates founderstack_test if it doesn't exist. Runs once per pytest session."""
    conn = await asyncpg.connect(_ADMIN_DSN)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'founderstack_test'"
        )
        if not exists:
            await conn.execute("CREATE DATABASE founderstack_test")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def test_engine(ensure_test_db):
    """Session-scoped engine. Schema is created once and dropped after all tests."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    """Truncates all tables after every test. Fast alternative to drop/create per test."""
    yield
    async with test_engine.begin() as conn:
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        if table_names:
            await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def setup_user_org(db_session: AsyncSession):
    """Inserts a standard test org + user. Tables are clean at the start of every test."""
    from app.models.identity import User, Organization
    from sqlalchemy import insert

    org_id = uuid.uuid4()
    await db_session.execute(
        insert(Organization).values(
            id=org_id,
            name="Testing HQ",
            slug="testing-hq",
            clerk_org_id="org_auth_123",
        )
    )

    user_id = uuid.uuid4()
    await db_session.execute(
        insert(User).values(
            id=user_id,
            org_id=org_id,
            clerk_user_id="user_auth_123",
            email="tester@founderstack.ai",
            full_name="Tester McTest",
            role="admin",
        )
    )
    await db_session.commit()
    return {"user_id": user_id, "org_id": org_id, "clerk_user_id": "user_auth_123"}


@pytest.fixture
def auth_headers(setup_user_org):
    token = jwt.encode(
        {"sub": setup_user_org["clerk_user_id"]}, "dummy_secret", algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}
