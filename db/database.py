"""Database engine and session factory for Invoice Chaser."""

import os
from contextlib import contextmanager
from typing import Any, Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///invoice_chaser.db",
)


def _create_engine(url: str):
    """Internal helper to construct SQLAlchemy engine for a given URL."""
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        url,
        connect_args=connect_args,
        echo=os.getenv("SQL_ECHO", "0").lower() in ("1", "true", "yes"),
    )


engine = _create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables from models."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Session:
    """Return a new session (caller must close or use as context)."""
    return SessionLocal()


def configure_engine(database_url: str | None = None) -> None:
    """
    Reconfigure the global engine and session factory.
    Intended primarily for tests that need isolated SQLite files.
    """
    global engine, SessionLocal, DATABASE_URL

    if database_url is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "sqlite:///invoice_chaser.db",
        )
    DATABASE_URL = database_url
    engine = _create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
