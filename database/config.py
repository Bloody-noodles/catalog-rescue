import os

from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import Engine, make_url


def get_database_url() -> str:
    """Return a normalized DATABASE_URL without exposing it in errors."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in the process environment "
            "before using database functionality."
        )
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise RuntimeError(
            "DATABASE_URL is invalid. Configure a valid PostgreSQL connection URL."
        ) from None

    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def create_database_engine() -> Engine:
    """Create a synchronous SQLAlchemy engine when explicitly requested."""
    from sqlalchemy import create_engine

    return create_engine(get_database_url(), pool_pre_ping=True)
