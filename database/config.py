import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError


# Load the project's root .env without overriding existing environment variables.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_database_url() -> str:
    """Return a normalized DATABASE_URL without exposing it in errors."""
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in the process environment "
            "or the project's .env file before using database functionality."
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