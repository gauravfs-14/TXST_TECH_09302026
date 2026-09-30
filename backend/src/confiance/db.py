import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _pragmas(conn, _):
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (tests switch databases between cases)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def _ddl_default(col) -> str:
    """A constant DEFAULT for an ALTER TABLE ADD COLUMN, taken from the model's Python-side default."""
    d = col.default.arg if col.default is not None and col.default.is_scalar else None
    if d is None and col.default is not None and callable(getattr(col.default, "arg", None)):
        name = getattr(col.default.arg, "__name__", "")
        return " DEFAULT '{}'" if name == "dict" else " DEFAULT '[]'" if name == "list" else ""
    if isinstance(d, bool):
        return f" DEFAULT {int(d)}"
    if isinstance(d, (int, float)):
        return f" DEFAULT {d}"
    if isinstance(d, str):
        return " DEFAULT '" + d.replace("'", "''") + "'"
    return ""


def migrate() -> list[str]:
    """Additive upgrades for existing databases: add columns the models have and the tables lack.
    Never drops, renames or rewrites anything, so an older database keeps all of its data."""
    from sqlalchemy import inspect, text

    engine = get_engine()
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{_ddl_default(col)}'))
                    added.append(f"{table.name}.{col.name}")
    return added


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(get_engine())  # creates missing tables
    migrate()  # adds missing columns to tables that already exist


_active: contextvars.ContextVar[tuple[Session, int] | None] = contextvars.ContextVar("db_session", default=None)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Nested calls in the same thread join the outer transaction, so audit and
    usage records commit atomically with the change they describe (and never fight it for the SQLite
    write lock). A scope opened in another thread always gets its own session."""
    cur = _active.get()
    if cur is not None and cur[1] == threading.get_ident():
        yield cur[0]
        return
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    token = _active.set((session, threading.get_ident()))
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        _active.reset(token)
        session.close()
