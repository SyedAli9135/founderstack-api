import pytest
import asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.models.base import Base
from app.core.database import get_db
from app.main import app
from httpx import AsyncClient, ASGITransport
from app.config import settings

# Dedicated test database (Ensure it is created first)
TEST_DB_URL = "postgresql+asyncpg://postgres:password@localhost:5440/founderstack_test"

# Note: With newer pytest-asyncio, we should usually avoid overriding event_loop fixture
# and instead use the built-in ones with proper scope.
# The pytest.ini asyncio_default_fixture_loop_scope = session handles this.

@pytest.fixture
async def test_engine():
    """Create a database engine and synchronize the schema for each test."""
    engine = create_async_engine(TEST_DB_URL)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    yield engine
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session wrapped in a transaction that auto-rolls back."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with Session() as session:
        yield session
        # Always rollback after each test to ensure isolation
        await session.rollback()

@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP client that communicates with the app using the test DB."""
    # Override get_db dependency to use the isolated test session
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    # Clear overrides after the test is complete
    app.dependency_overrides.clear()
