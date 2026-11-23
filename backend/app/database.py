"""Synchronous SQLAlchemy engine and per-request session dependency."""

from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the process-wide engine on first database use."""
    return create_engine(get_database_url(), hide_parameters=True, connect_args={"connect_timeout": 3},
                         pool_timeout=3, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    """Return a factory that creates a separate session for each request."""
    return sessionmaker(bind=get_engine(), class_=Session)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session and always close it afterward."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def dispose_engine() -> None:
    """Dispose the engine during application shutdown, if it was initialized."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_sessionmaker.cache_clear()
        get_engine.cache_clear()
