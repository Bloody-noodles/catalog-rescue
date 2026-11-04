from collections.abc import Iterator
from threading import RLock

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.config import create_database_engine


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_engine_lock = RLock()


def get_database_engine() -> Engine:
    global _engine

    with _engine_lock:
        if _engine is None:
            _engine = create_database_engine()
        return _engine


def create_session_factory(
    engine: Engine | None = None,
) -> sessionmaker[Session]:
    global _session_factory

    if engine is not None:
        return sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

    with _engine_lock:
        if _session_factory is None:
            _session_factory = sessionmaker(
                bind=get_database_engine(),
                autoflush=False,
                expire_on_commit=False,
            )

        return _session_factory


def dispose_database_engine(engine: Engine | None = None) -> None:
    global _engine, _session_factory

    with _engine_lock:
        target = engine if engine is not None else _engine

        if target is None:
            return

        target.dispose()

        if target is _engine:
            _engine = None
            _session_factory = None


def get_db_session(
    session_factory: sessionmaker[Session] | None = None,
) -> Iterator[Session]:
    """Create a session, optionally using an injected session factory."""
    factory = session_factory or create_session_factory()

    with factory() as session:
        yield session


def get_api_db_session() -> Iterator[Session]:
    """Parameterless dependency for FastAPI."""
    yield from get_db_session()