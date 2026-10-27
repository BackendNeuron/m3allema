"""Database connection shared by the stores."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from m3allema.storage.models import Base


class Database:
    """Owns the engine and session factory; creates tables on first use.

    Args:
        url: SQLAlchemy URL, for example ``sqlite:///path/m3allema.db`` or a Postgres URL.

    """

    def __init__(self, url: str) -> None:
        self._engine: Engine = create_engine(url)
        Base.metadata.create_all(self._engine)
        self.sessions: sessionmaker[Session] = sessionmaker(self._engine, expire_on_commit=False)

    def close(self) -> None:
        """Release every connection."""
        self._engine.dispose()
