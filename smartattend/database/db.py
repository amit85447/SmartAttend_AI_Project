"""Engine/session helpers. Use `engine()` everywhere; call `init_db()` once."""
from functools import lru_cache
from sqlalchemy import create_engine, event
import config
from database.tables import metadata


@lru_cache(maxsize=4)
def _make_engine(url: str):
    kwargs = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):          # SQLite ignores foreign keys unless enabled
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


def engine(url: str | None = None):
    return _make_engine(url or config.DB_URL)


def init_db(url: str | None = None):
    """Create all tables if they do not exist (MySQL users can run sql/01_schema_mysql.sql instead)."""
    metadata.create_all(engine(url))
