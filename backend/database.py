# =============================================================================
# AttendTrax Enterprise – Database Connection & Session Lifecycle
# database.py  –  Async SQLAlchemy Engine & Session Factory (Supabase & SQLite)
# =============================================================================
import os
import sys
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from config import get_settings

Base = declarative_base()

_engine = None
_session_factory = None
_using_sqlite_fallback = False


def _build_sqlite_engine():
    global _using_sqlite_fallback
    _using_sqlite_fallback = True
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, "attendtrax.db").replace("\\", "/")
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


def get_engine():
    global _engine, _using_sqlite_fallback
    if _engine is None:
        db_url = get_settings().get_database_url()
        connect_args = {}
        if db_url.startswith("sqlite"):
            _engine = _build_sqlite_engine()
        else:
            # PostgreSQL / Supabase pool settings
            if ":6543" in db_url or "pooler.supabase.com" in db_url:
                connect_args["statement_cache_size"] = 0
            _engine = create_async_engine(
                db_url,
                echo=False,
                pool_size=10,
                max_overflow=5,
                pool_recycle=300,
                pool_pre_ping=True,
                connect_args=connect_args,
            )
    return _engine


def switch_to_sqlite():
    """Dynamically switch to SQLite fallback if remote PostgreSQL is unreachable."""
    global _engine, _session_factory
    print("[Database Warning] Remote PostgreSQL pooler unreachable. Switching to local SQLite fallback.")
    _engine = _build_sqlite_engine()
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency for database session injection."""
    session_factory = get_session_factory()
    try:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as exc:
        # If remote PostgreSQL fails, automatically switch and retry
        global _using_sqlite_fallback
        if not _using_sqlite_fallback:
            factory = switch_to_sqlite()
            async with factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
        else:
            raise exc


async def init_db() -> None:
    """Create all database tables if they do not exist."""
    global _using_sqlite_fallback
    engine = get_engine()
    import models  # noqa: F401
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        print(f"[Database Notice] Primary engine init failed: {exc}")
        if not _using_sqlite_fallback:
            switch_to_sqlite()
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            raise exc
