"""State transitions for AnalysisRun.

Callers must reload and lock the row in a short database transaction before
applying a transition. Lease tokens and expiry checks prevent stale workers
from renewing or finalizing a lease that has expired or been reassigned.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from database.job_constants import MAX_ATTEMPTS
from database.models import AnalysisRun


DEFAULT_LEASE_DURATION = timedelta(minutes=5)
LEASE_EXPIRED_MESSAGE = "Processing lease expired."


class JobTransitionError(ValueError):
    """Raised when a requested analysis-job transition is not permitted."""


def start_processing(
    run: AnalysisRun,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = DEFAULT_LEASE_DURATION,
) -> UUID:
    now = _aware_now(now)
    _validate_lease_duration(lease_duration)
    if run.status != "queued":
        raise JobTransitionError("Only queued analysis runs can start processing.")
    if run.attempt_count >= MAX_ATTEMPTS:
        raise JobTransitionError("The maximum number of analysis attempts was reached.")

    token = uuid4()
    run.status = "processing"
    run.attempt_count += 1
    run.started_at = now
    run.completed_at = None
    run.updated_at = now
    run.error_message = None
    run.lease_expires_at = now + lease_duration
    run.lease_token = token
    run.retryable = False
    _clear_result_values(run)
    return token


def renew_lease(
    run: AnalysisRun,
    lease_token: UUID,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = DEFAULT_LEASE_DURATION,
) -> datetime:
    now = _aware_now(now)
    _validate_lease_duration(lease_duration)
    _require_lease_owner(run, lease_token, now)
    run.lease_expires_at = now + lease_duration
    run.updated_at = now
    return run.lease_expires_at


def complete_run(
    run: AnalysisRun,
    lease_token: UUID,
    *,
    now: datetime | None = None,
) -> None:
    now = _aware_now(now)
    _require_lease_owner(run, lease_token, now)
    run.status = "completed"
    run.completed_at = now
    run.updated_at = now
    run.error_message = None
    run.retryable = False
    _clear_lease(run)


def fail_run(
    run: AnalysisRun,
    lease_token: UUID,
    error_message: str,
    *,
    retryable: bool,
    now: datetime | None = None,
) -> None:
    now = _aware_now(now)
    _require_lease_owner(run, lease_token, now)
    if not isinstance(error_message, str) or not error_message.strip():
        raise ValueError("A non-empty error message is required for a failed run.")

    run.status = "failed"
    run.completed_at = None
    run.updated_at = now
    run.error_message = error_message
    run.retryable = bool(retryable and run.attempt_count < MAX_ATTEMPTS)
    _clear_result_values(run)
    _clear_lease(run)


def retry_failed_run(run: AnalysisRun, *, now: datetime | None = None) -> None:
    now = _aware_now(now)
    if run.status != "failed":
        raise JobTransitionError("Only failed analysis runs can be retried.")
    if not run.retryable:
        raise JobTransitionError("This analysis failure is not retryable.")
    if run.attempt_count >= MAX_ATTEMPTS:
        raise JobTransitionError("The maximum number of analysis attempts was reached.")

    run.status = "queued"
    run.retryable = False
    run.updated_at = now
    run.completed_at = None
    _clear_result_values(run)


def recover_expired_lease(
    run: AnalysisRun,
    *,
    now: datetime | None = None,
) -> str:
    now = _aware_now(now)
    if run.status != "processing" or run.lease_expires_at is None:
        raise JobTransitionError("Only processing runs with a lease can be recovered.")
    if run.lease_expires_at > now:
        raise JobTransitionError("The processing lease has not expired.")

    run.updated_at = now
    run.completed_at = None
    run.error_message = LEASE_EXPIRED_MESSAGE
    retry_allowed = run.attempt_count < MAX_ATTEMPTS
    _clear_result_values(run)
    _clear_lease(run)
    run.status = "queued" if retry_allowed else "failed"
    run.retryable = False
    return run.status


def _require_lease_owner(run: AnalysisRun, lease_token: UUID, now: datetime) -> None:
    if run.status != "processing" or run.lease_token != lease_token:
        raise JobTransitionError("The analysis run is no longer owned by this worker.")
    if run.lease_expires_at is None or run.lease_expires_at <= now:
        raise JobTransitionError("The worker lease has expired.")


def _clear_lease(run: AnalysisRun) -> None:
    run.lease_expires_at = None
    run.lease_token = None


def _clear_result_values(run: AnalysisRun) -> None:
    run.health_score = 0
    run.issue_count = 0
    run.cleaned_record_count = 0
    run.affected_record_count = 0
    run.quality_metrics = {}
    run.analysis_summary = {}
    run.cleaned_rows = None
    run.analysis_report = None


def _aware_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Lifecycle timestamps must be timezone-aware.")
    return value


def _validate_lease_duration(lease_duration: timedelta) -> None:
    if lease_duration <= timedelta(0):
        raise ValueError("Lease duration must be greater than zero.")
