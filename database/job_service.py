"""Database-backed, conditional operations for analysis-job lifecycle state.

Each operation participates in the caller's SQLAlchemy transaction. Callers
should commit claims promptly before starting work, and commit every successful
transition. A transition error should roll back the surrounding transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Interval,
    and_,
    bindparam,
    case,
    func,
    literal,
    select,
    update,
)
from sqlalchemy.orm import Session

from database.job_constants import MAX_ATTEMPTS
from database.job_lifecycle import (
    DEFAULT_LEASE_DURATION,
    LEASE_EXPIRED_MESSAGE,
    JobTransitionError,
)
from database.models import AnalysisRun
from database.models import Catalog


@dataclass(frozen=True)
class JobClaim:
    analysis_id: UUID
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int


@dataclass(frozen=True)
class CatalogSource:
    filename: str
    file_format: str
    original_file: bytes | None
    original_rows: dict | None


def claim_next_job(
    session: Session,
    *,
    lease_duration: timedelta = DEFAULT_LEASE_DURATION,
) -> JobClaim | None:
    """Atomically claim one queued row; requires a caller-owned transaction."""
    _validate_lease_duration(lease_duration)
    now = _database_clock(session)
    lease_token = uuid4()
    candidate_id = session.scalar(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.status == "queued",
            AnalysisRun.attempt_count < MAX_ATTEMPTS,
        )
        .order_by(AnalysisRun.updated_at, AnalysisRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if candidate_id is None:
        return None

    statement = (
        update(AnalysisRun)
        .where(
            AnalysisRun.id == candidate_id,
            AnalysisRun.status == "queued",
            AnalysisRun.attempt_count < MAX_ATTEMPTS,
        )
        .values(
            status="processing",
            attempt_count=AnalysisRun.attempt_count + 1,
            started_at=now,
            completed_at=None,
            updated_at=now,
            error_message=None,
            lease_expires_at=_lease_expiry(session, now, lease_duration),
            lease_token=lease_token,
            retryable=False,
            health_score=0,
            issue_count=0,
            cleaned_record_count=0,
            affected_record_count=0,
            quality_metrics={},
            analysis_summary={},
            cleaned_rows=None,
            analysis_report=None,
        )
        .returning(
            AnalysisRun.id,
            AnalysisRun.lease_expires_at,
            AnalysisRun.attempt_count,
        )
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    return JobClaim(
        analysis_id=row.id,
        lease_token=lease_token,
        lease_expires_at=row.lease_expires_at,
        attempt_count=row.attempt_count,
    )


def load_claimed_catalog_source(
    session: Session,
    analysis_id: UUID,
    lease_token: UUID,
) -> CatalogSource:
    """Fetch source metadata only while the caller still owns a live lease."""
    now = _database_clock(session)
    row = session.execute(
        select(
            Catalog.original_filename,
            Catalog.file_format,
            Catalog.original_file,
            Catalog.original_rows,
        )
        .join(AnalysisRun, AnalysisRun.catalog_id == Catalog.id)
        .where(
            AnalysisRun.id == analysis_id,
            AnalysisRun.status == "processing",
            AnalysisRun.lease_token == lease_token,
            AnalysisRun.lease_expires_at > now,
        )
    ).one_or_none()
    if row is None:
        raise JobTransitionError("The lease is expired or no longer owned by this worker.")
    return CatalogSource(
        filename=row.original_filename,
        file_format=row.file_format,
        original_file=row.original_file,
        original_rows=row.original_rows,
    )


def complete_job_with_results(
    session: Session,
    analysis_id: UUID,
    lease_token: UUID,
    *,
    health_score: int,
    issue_count: int,
    cleaned_record_count: int,
    affected_record_count: int,
    quality_metrics: dict,
    analysis_summary: dict,
    cleaned_rows: dict,
    analysis_report: dict,
    lease_deadline: datetime | None = None,
) -> None:
    """Persist all analysis results and complete the job with one fenced update."""
    now = _database_clock(session)
    conditions = [
        AnalysisRun.id == analysis_id,
        AnalysisRun.status == "processing",
        AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_expires_at > now,
    ]
    if lease_deadline is not None:
        conditions.append(now < lease_deadline)
    statement = (
        update(AnalysisRun)
        .where(*conditions)
        .values(
            status="completed",
            completed_at=now,
            updated_at=now,
            error_message=None,
            retryable=False,
            lease_expires_at=None,
            lease_token=None,
            health_score=health_score,
            issue_count=issue_count,
            cleaned_record_count=cleaned_record_count,
            affected_record_count=affected_record_count,
            quality_metrics=quality_metrics,
            analysis_summary=analysis_summary,
            cleaned_rows=cleaned_rows,
            analysis_report=analysis_report,
        )
        .returning(AnalysisRun.id)
    )
    _require_updated_row(
        session,
        statement,
        "The lease is expired or no longer owned by this worker.",
    )


def renew_job_lease(
    session: Session,
    analysis_id: UUID,
    lease_token: UUID,
    *,
    lease_duration: timedelta = DEFAULT_LEASE_DURATION,
    lease_deadline: datetime | None = None,
) -> datetime:
    _validate_lease_duration(lease_duration)
    now = _database_clock(session)
    lease_expiry = _lease_expiry(session, now, lease_duration)
    conditions = [
        AnalysisRun.id == analysis_id,
        AnalysisRun.status == "processing",
        AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_expires_at > now,
    ]
    if lease_deadline is not None:
        expiry_function = (
            func.least
            if session.get_bind().dialect.name == "postgresql"
            else func.min
        )
        lease_expiry = expiry_function(lease_expiry, lease_deadline)
        conditions.append(now < lease_deadline)
    statement = (
        update(AnalysisRun)
        .where(*conditions)
        .values(
            lease_expires_at=lease_expiry,
            updated_at=now,
        )
        .returning(AnalysisRun.lease_expires_at)
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        raise JobTransitionError("The lease is expired or no longer owned by this worker.")
    return row.lease_expires_at


def complete_job(
    session: Session,
    analysis_id: UUID,
    lease_token: UUID,
) -> None:
    now = _database_clock(session)
    statement = (
        update(AnalysisRun)
        .where(
            AnalysisRun.id == analysis_id,
            AnalysisRun.status == "processing",
            AnalysisRun.lease_token == lease_token,
            AnalysisRun.lease_expires_at > now,
        )
        .values(
            status="completed",
            completed_at=now,
            updated_at=now,
            error_message=None,
            retryable=False,
            lease_expires_at=None,
            lease_token=None,
        )
        .returning(AnalysisRun.id)
    )
    _require_updated_row(session, statement, "The lease is expired or no longer owned by this worker.")


def fail_job(
    session: Session,
    analysis_id: UUID,
    lease_token: UUID,
    error_message: str,
    *,
    retryable: bool,
    lease_deadline: datetime | None = None,
) -> None:
    if not isinstance(error_message, str) or not error_message.strip():
        raise ValueError("A non-empty error message is required for a failed run.")
    now = _database_clock(session)
    retryable_value = and_(
        literal(bool(retryable)),
        AnalysisRun.attempt_count < MAX_ATTEMPTS,
    )
    conditions = [
        AnalysisRun.id == analysis_id,
        AnalysisRun.status == "processing",
        AnalysisRun.lease_token == lease_token,
        AnalysisRun.lease_expires_at > now,
    ]
    if lease_deadline is not None:
        conditions.append(now < lease_deadline)
    statement = (
        update(AnalysisRun)
        .where(*conditions)
        .values(
            status="failed",
            completed_at=None,
            updated_at=now,
            error_message=error_message,
            retryable=retryable_value,
            lease_expires_at=None,
            lease_token=None,
        )
        .returning(AnalysisRun.id)
    )
    _require_updated_row(session, statement, "The lease is expired or no longer owned by this worker.")


def retry_failed_job(session: Session, analysis_id: UUID) -> None:
    now = _database_clock(session)
    statement = (
        update(AnalysisRun)
        .where(
            AnalysisRun.id == analysis_id,
            AnalysisRun.status == "failed",
            AnalysisRun.retryable.is_(True),
            AnalysisRun.attempt_count < MAX_ATTEMPTS,
        )
        .values(
            status="queued",
            retryable=False,
            completed_at=None,
            updated_at=now,
            health_score=0,
            issue_count=0,
            cleaned_record_count=0,
            affected_record_count=0,
            quality_metrics={},
            analysis_summary={},
            cleaned_rows=None,
            analysis_report=None,
        )
        .returning(AnalysisRun.id)
    )
    _require_updated_row(
        session,
        statement,
        "Only retryable failed jobs below the attempt limit can be requeued.",
    )


def recover_expired_job(session: Session, analysis_id: UUID) -> str:
    now = _database_clock(session)
    next_status = case(
        (AnalysisRun.attempt_count < MAX_ATTEMPTS, "queued"),
        else_="failed",
    )
    statement = (
        update(AnalysisRun)
        .where(
            AnalysisRun.id == analysis_id,
            AnalysisRun.status == "processing",
            AnalysisRun.lease_expires_at <= now,
        )
        .values(
            status=next_status,
            completed_at=None,
            updated_at=now,
            error_message=LEASE_EXPIRED_MESSAGE,
            retryable=False,
            lease_expires_at=None,
            lease_token=None,
            health_score=0,
            issue_count=0,
            cleaned_record_count=0,
            affected_record_count=0,
            quality_metrics={},
            analysis_summary={},
            cleaned_rows=None,
            analysis_report=None,
        )
        .returning(AnalysisRun.status)
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        raise JobTransitionError("The job is not processing with an expired lease.")
    return row.status


def recover_expired_jobs(session: Session, *, limit: int = 100) -> int:
    """Recover a bounded batch of expired leases in the caller's transaction."""
    if limit < 1:
        raise ValueError("Recovery batch limit must be greater than zero.")
    now = _database_clock(session)
    expired_ids = session.scalars(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.status == "processing",
            AnalysisRun.lease_expires_at <= now,
        )
        .order_by(AnalysisRun.lease_expires_at, AnalysisRun.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    recovered = 0
    for analysis_id in expired_ids:
        try:
            recover_expired_job(session, analysis_id)
        except JobTransitionError:
            continue
        recovered += 1
    return recovered


def _database_clock(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return func.clock_timestamp()
    if dialect == "sqlite":
        return func.strftime(
            "%Y-%m-%d %H:%M:%f",
            "now",
            type_=DateTime(timezone=True),
        )
    return func.current_timestamp()


def _lease_expiry(session: Session, now, lease_duration: timedelta):
    if session.get_bind().dialect.name == "postgresql":
        return now + bindparam(
            "lease_duration",
            lease_duration,
            type_=Interval(),
        )
    return func.strftime(
        "%Y-%m-%d %H:%M:%f",
        now,
        f"+{lease_duration.total_seconds()} seconds",
        type_=DateTime(timezone=True),
    )


def _require_updated_row(session: Session, statement, message: str) -> None:
    if session.execute(statement).one_or_none() is None:
        raise JobTransitionError(message)


def _validate_lease_duration(lease_duration: timedelta) -> None:
    if lease_duration <= timedelta(0):
        raise ValueError("Lease duration must be greater than zero.")
