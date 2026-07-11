from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.community_hub.config import get_hub_config


class HubBase(DeclarativeBase):
    """Metadata dedicated to the community hub."""


class HubDatabase:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.engine = create_engine(
            f"sqlite:///{self.database_path.as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(self.engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    @classmethod
    def from_environment(cls) -> "HubDatabase":
        return cls(get_hub_config().database_path)

    def initialize(self) -> None:
        # Deliberately delayed until the runner's Winamax preflight succeeds.
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        import app.community_hub.models  # noqa: F401

        HubBase.metadata.create_all(bind=self.engine)

    def session(self) -> Session:
        return self.SessionLocal()

    def dependency(self) -> Generator[Session, None, None]:
        db = self.session()
        try:
            yield db
        finally:
            db.close()

    def dispose(self) -> None:
        self.engine.dispose()
