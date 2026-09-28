"""Database engine and session plumbing."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        # check_same_thread=False so the dev SQLite file works under uvicorn.
        #
        # timeout is the one that matters in practice. The ordinary day
        # here is a browser pass writing a check row every couple of
        # seconds for an hour while the phone uploads a batch of
        # captures into the same file. On the default five seconds a
        # collision gives up and the upload fails, which on the phone
        # looks like a button that does nothing.
        return {"connect_args": {"check_same_thread": False, "timeout": 60.0}}
    return {"pool_pre_ping": True}


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, record) -> None:
    """WAL, so a long write pass does not block every read.

    Without it a writer holds the whole file, so the dashboard hangs
    while a takedown pass is running and an upload waits behind it.
    WAL lets readers carry on against the last committed state, which
    is exactly what a dashboard wants. It is a property of the
    database file, set once and persisting, but setting it on every
    connect costs nothing and survives a file restored from backup.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        # Durable enough: a crash can lose the last transaction, never
        # the file. The alternative is an fsync per check row.
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers mappers)

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Add columns the models gained since a database was created.

    create_all() only creates missing tables, so a new column would
    otherwise break every query against an existing file. A running
    collection is worth more than schema purity here: this adds what is
    missing and touches nothing else. It cannot rename, drop, backfill,
    or change a type -- anything beyond an additive column needs a real
    migration tool.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present or not column.nullable:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                connection.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}')
                )


#: Where `daily.sh` keeps its copies, and now where a hand-run pass
#: keeps one too.
BACKUP_DIR = Path("backups")
KEEP_BACKUPS = 30


def snapshot(directory: Path | None = None, keep: int = KEEP_BACKUPS) -> Path | None:
    """Copy the database before a long pass writes to it.

    `daily.sh` has always done this and a pass run by hand did not --
    which is the wrong way round, because the hand-run pass is the
    hour-long one, and the day it mattered the newest copy was from
    the afternoon before.

    Uses SQLite's own backup API rather than copying the file: a file
    copy taken while something is mid-write gives a copy that is
    mid-write, and a backup nobody can open is worse than none,
    because it is only discovered in the moment it is needed.

    Returns the path written, or None when there is no file database
    to copy.
    """
    import sqlite3
    from datetime import datetime, timezone

    url = settings.database_url
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    source = Path(url[len(prefix):])
    if not source.is_file():
        return None

    folder = directory or BACKUP_DIR
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    destination = folder / f"scraper-{stamp}.db"

    with sqlite3.connect(source) as live, sqlite3.connect(destination) as copy:
        live.backup(copy)

    # Keep a month of them. Old copies are what make a bad day undoable.
    copies = sorted(folder.glob("scraper-*.db"), key=lambda f: f.stat().st_mtime)
    for old in copies[:-keep]:
        old.unlink(missing_ok=True)
    return destination
