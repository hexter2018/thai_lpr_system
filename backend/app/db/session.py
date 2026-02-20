"""Database session management - Support both sync and async"""
import os
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://lpr:lpr2024@postgres:5432/lpr_v2")
DATABASE_URL_SYNC = DATABASE_URL.replace("+asyncpg", "").replace("postgresql://", "postgresql+psycopg2://")

# Sync engine and session (for FastAPI/Alembic)
engine = create_engine(
    DATABASE_URL_SYNC,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Async engine and session (for stream manager and async operations)
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# Sync database dependency (for FastAPI)
def get_db():
    """Get sync database session for FastAPI dependency injection"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Async database dependency (for async endpoints)
async def get_async_db():
    """Get async database session for FastAPI async dependency injection"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
