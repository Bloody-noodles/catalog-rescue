"""Independent polling process for queued catalog analysis runs."""

import argparse
import logging
import math
import os
import signal
import threading
from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
from time import monotonic

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from catalog_engine import analyze_catalog
from catalog_ingestion import load_catalog
from database.job_lifecycle import DEFAULT_LEASE_DURATION, JobTransitionError
from database.job_service import (
    JobClaim,
    claim_next_job,
    complete_job_with_results,
    fail_job,
    load_claimed_catalog_source,
    recover_expired_jobs,
    renew_job_lease,
)
from database.serialization import dataframe_to_payload, to_json_safe
from database.session import create_session_factory, dispose_database_engine


LOGGER = logging.getLogger("catalog_rescue.worker")
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_RENEW_INTERVAL = DEFAULT_LEASE_DURATION.total_seconds() / 3
DEFAULT_MAX_PROCESSING_SECONDS = 30 * 60
DATABASE_OPERATION_TIMEOUT_SECONDS = 5.0
HEARTBEAT_SHUTDOWN_TIMEOUT_SECONDS = 1.0


class JobOutcome(str, Enum):
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"
    LEASE_LOST = "lease_lost"
    MAX_RUNTIME = "max_runtime"
    INTERRUPTED = "interrupted"


class _LeaseHeartbeat:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        claim: JobClaim,
        lease_duration_seconds: float,
        renew_interval_seconds: float,
        max_processing_seconds: float,
        database_operation_timeout_seconds: float,
        shutdown_timeout_seconds: float,
    ):
        self._session_factory = session_factory
        self._claim = claim
        self._lease_duration = timedelta(seconds=lease_duration_seconds)
        self._renew_interval = renew_interval_seconds
        self._deadline = monotonic() + max_processing_seconds
        initial_lease_duration = min(lease_duration_seconds, max_processing_seconds)
        self._lease_deadline = claim.lease_expires_at + timedelta(
            seconds=max_processing_seconds - initial_lease_duration
        )
        self._database_timeout = database_operation_timeout_seconds
        self._shutdown_timeout = shutdown_timeout_seconds
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._deadline_reached = threading.Event()
        self._shutdown_timed_out = threading.Event()
        self._thread = threading.Thread(
            target=self._renew_loop,
            name=f"catalog-lease-{claim.analysis_id}",
            daemon=True,
        )

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def deadline_reached(self) -> bool:
        if monotonic() >= self._deadline:
            self._deadline_reached.set()
        return self._deadline_reached.is_set()

    @property
    def lease_deadline(self) -> datetime:
        return self._lease_deadline

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> bool:
        self._stop.set()
        if self._shutdown_timed_out.is_set():
            return False
        if self._thread.ident is None:
            return True
        self._thread.join(timeout=self._shutdown_timeout)
        if self._thread.is_alive():
            self._shutdown_timed_out.set()
            self._lost.set()
            LOGGER.warning(
                "Heartbeat shutdown timed out for analysis %s; result ownership was relinquished.",
                self._claim.analysis_id,
            )
            return False
        return True

    def renew_now(self) -> bool:
        if self.deadline_reached:
            self._deadline_reached.set()
            return False
        if self._stop.is_set():
            return False
        try:
            with self._session_factory.begin() as session:
                session.connection()
                if self._stop.is_set():
                    return False
                if self.deadline_reached:
                    return False
                if session.get_bind().dialect.name == "postgresql":
                    timeout_ms = max(1, int(self._database_timeout * 1000))
                    session.execute(
                        select(
                            func.set_config(
                                "statement_timeout",
                                f"{timeout_ms}ms",
                                True,
                            )
                        )
                    )
                remaining = self._deadline - monotonic()
                if remaining <= 0 or self._stop.is_set():
                    if remaining <= 0:
                        self._deadline_reached.set()
                    return False
                renew_job_lease(
                    session,
                    self._claim.analysis_id,
                    self._claim.lease_token,
                    lease_duration=min(self._lease_duration, timedelta(seconds=remaining)),
                    lease_deadline=self._lease_deadline,
                )
            return True
        except JobTransitionError:
            self._lost.set()
            return False
        except SQLAlchemyError:
            self._lost.set()
            LOGGER.warning(
                "Could not renew lease for analysis %s; relinquishing result ownership.",
                self._claim.analysis_id,
            )
            return False
        except Exception as exc:
            self._lost.set()
            LOGGER.error(
                "Lease renewal failed for analysis %s (%s).",
                self._claim.analysis_id,
                type(exc).__name__,
            )
            return False

    def _renew_loop(self) -> None:
        try:
            while not self._stop.is_set():
                remaining = self._deadline - monotonic()
                if remaining <= 0:
                    self._deadline_reached.set()
                    return
                if self._stop.wait(min(self._renew_interval, remaining)):
                    return
                if self.deadline_reached:
                    return
                if not self.renew_now():
                    return
        except BaseException as exc:
            self._lost.set()
            LOGGER.error(
                "Heartbeat exited unexpectedly for analysis %s (%s).",
                self._claim.analysis_id,
                type(exc).__name__,
            )


class CatalogAnalysisWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL,
        lease_duration_seconds: float = DEFAULT_LEASE_DURATION.total_seconds(),
        renew_interval_seconds: float = DEFAULT_RENEW_INTERVAL,
        max_processing_seconds: float = DEFAULT_MAX_PROCESSING_SECONDS,
        database_operation_timeout_seconds: float = DATABASE_OPERATION_TIMEOUT_SECONDS,
        heartbeat_shutdown_timeout_seconds: float = HEARTBEAT_SHUTDOWN_TIMEOUT_SECONDS,
        analysis_function=analyze_catalog,
        ingestion_function=load_catalog,
    ):
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("Poll interval must be finite and greater than zero.")
        if not math.isfinite(lease_duration_seconds) or lease_duration_seconds <= 0:
            raise ValueError("Lease duration must be finite and greater than zero.")
        if (
            not math.isfinite(renew_interval_seconds)
            or renew_interval_seconds <= 0
            or renew_interval_seconds >= lease_duration_seconds
        ):
            raise ValueError("Renew interval must be positive and shorter than the lease.")
        if not math.isfinite(max_processing_seconds) or max_processing_seconds <= 0:
            raise ValueError("Maximum processing duration must be finite and greater than zero.")
        if (
            not math.isfinite(database_operation_timeout_seconds)
            or database_operation_timeout_seconds <= 0
            or not math.isfinite(heartbeat_shutdown_timeout_seconds)
            or heartbeat_shutdown_timeout_seconds <= 0
        ):
            raise ValueError("Heartbeat timeouts must be finite and greater than zero.")
        self._session_factory = session_factory or create_session_factory()
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_duration_seconds = lease_duration_seconds
        self.renew_interval_seconds = renew_interval_seconds
        self.max_processing_seconds = max_processing_seconds
        self.database_operation_timeout_seconds = database_operation_timeout_seconds
        self.heartbeat_shutdown_timeout_seconds = heartbeat_shutdown_timeout_seconds
        self._analysis_function = analysis_function
        self._ingestion_function = ingestion_function

    def run_once(self) -> JobOutcome:
        with self._session_factory.begin() as session:
            recover_expired_jobs(session)
        with self._session_factory.begin() as session:
            claim = claim_next_job(
                session,
                lease_duration=timedelta(
                    seconds=min(
                        self.lease_duration_seconds,
                        self.max_processing_seconds,
                    )
                ),
            )
        if claim is None:
            return JobOutcome.IDLE
        return self.process_claim(claim)

    def process_claim(self, claim: JobClaim) -> JobOutcome:
        heartbeat = _LeaseHeartbeat(
            self._session_factory,
            claim,
            self.lease_duration_seconds,
            self.renew_interval_seconds,
            self.max_processing_seconds,
            self.database_operation_timeout_seconds,
            self.heartbeat_shutdown_timeout_seconds,
        )
        heartbeat.start()
        try:
            return self._process_claim(heartbeat, claim)
        finally:
            heartbeat.stop()

    def _process_claim(
        self,
        heartbeat: _LeaseHeartbeat,
        claim: JobClaim,
    ) -> JobOutcome:
        try:
            source = self._load_source(claim)
        except JobTransitionError:
            return self._heartbeat_outcome(heartbeat)
        except SQLAlchemyError:
            if heartbeat.deadline_reached:
                return JobOutcome.MAX_RUNTIME
            if heartbeat.lost:
                return JobOutcome.LEASE_LOST
            LOGGER.warning("Could not load catalog source for analysis %s.", claim.analysis_id)
            return JobOutcome.INTERRUPTED
        except Exception as exc:
            if heartbeat.deadline_reached:
                return JobOutcome.MAX_RUNTIME
            return self._record_failure(
                heartbeat,
                claim,
                "Catalog source could not be read.",
                retryable=False,
                error_type=type(exc).__name__,
            )

        if heartbeat.deadline_reached or heartbeat.lost:
            return self._heartbeat_outcome(heartbeat)

        try:
            result = self._analysis_function(source)
        except Exception as exc:
            if heartbeat.deadline_reached:
                return JobOutcome.MAX_RUNTIME
            retryable = isinstance(exc, (TimeoutError, ConnectionError))
            return self._record_failure(
                heartbeat,
                claim,
                (
                    "Catalog analysis encountered a transient failure."
                    if retryable
                    else "Catalog analysis failed deterministically."
                ),
                retryable=retryable,
                error_type=type(exc).__name__,
            )

        if heartbeat.deadline_reached or heartbeat.lost:
            return self._heartbeat_outcome(heartbeat)

        try:
            values = self._prepare_results(result)
        except Exception as exc:
            if heartbeat.deadline_reached:
                return JobOutcome.MAX_RUNTIME
            return self._record_failure(
                heartbeat,
                claim,
                "Analysis results could not be serialized.",
                retryable=False,
                error_type=type(exc).__name__,
            )

        heartbeat.stop()
        if heartbeat.deadline_reached or heartbeat.lost:
            return self._heartbeat_outcome(heartbeat)
        try:
            with self._session_factory.begin() as session:
                complete_job_with_results(
                    session,
                    claim.analysis_id,
                    claim.lease_token,
                    **values,
                    lease_deadline=heartbeat.lease_deadline,
                )
            return JobOutcome.COMPLETED
        except JobTransitionError:
            return JobOutcome.LEASE_LOST
        except SQLAlchemyError:
            LOGGER.warning(
                "Could not persist analysis %s; its lease will expire for recovery.",
                claim.analysis_id,
            )
            return JobOutcome.INTERRUPTED

    @staticmethod
    def _heartbeat_outcome(heartbeat: _LeaseHeartbeat) -> JobOutcome:
        if heartbeat.deadline_reached:
            return JobOutcome.MAX_RUNTIME
        return JobOutcome.LEASE_LOST

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop = stop_event or threading.Event()
        while not stop.is_set():
            started = monotonic()
            try:
                outcome = self.run_once()
                if outcome not in {JobOutcome.IDLE, JobOutcome.COMPLETED}:
                    LOGGER.info(
                        "Worker job ended with outcome %s.",
                        outcome.value,
                    )
            except Exception as exc:
                LOGGER.error(
                    "Worker iteration failed (%s).",
                    type(exc).__name__,
                )
            elapsed = monotonic() - started
            stop.wait(max(0.0, self.poll_interval_seconds - elapsed))

    def _load_source(self, claim: JobClaim) -> pd.DataFrame:
        with self._session_factory.begin() as session:
            source = load_claimed_catalog_source(
                session,
                claim.analysis_id,
                claim.lease_token,
            )
        if source.original_file is not None:
            stream = BytesIO(source.original_file)
            stream.name = source.filename
            return self._ingestion_function(stream)
        if source.original_rows is not None:
            columns = source.original_rows.get("columns")
            rows = source.original_rows.get("rows")
            if not isinstance(columns, list) or not isinstance(rows, list):
                raise ValueError("Stored source catalog payload is invalid.")
            return pd.DataFrame(rows, columns=columns)
        raise ValueError("No original catalog data is stored.")

    @staticmethod
    def _prepare_results(result: dict) -> dict:
        quality = result["quality_report"]
        metrics = {
            "completeness": quality["completeness"],
            "validity": quality["validity"],
            "consistency": quality["consistency"],
            "uniqueness": quality["uniqueness"],
        }
        summary = {
            "decision": result["business_decision"]["decision"],
            "quality_status": quality["status"],
            "recommendations": quality["recommendations"],
            "top_problems": quality["top_problems"],
        }
        report = {key: value for key, value in result.items() if key != "cleaned_df"}
        return {
            "health_score": int(quality["health_score"]),
            "issue_count": sum(
                int(issue.get("count", 0)) for issue in result["issues"]
            ),
            "cleaned_record_count": len(result["cleaned_df"]),
            "affected_record_count": int(
                result["impact_summary"]["affected_records"]
            ),
            "quality_metrics": to_json_safe(metrics),
            "analysis_summary": to_json_safe(summary),
            "cleaned_rows": dataframe_to_payload(result["cleaned_df"]),
            "analysis_report": to_json_safe(report),
        }

    def _record_failure(
        self,
        heartbeat: _LeaseHeartbeat,
        claim: JobClaim,
        message: str,
        *,
        retryable: bool,
        error_type: str,
    ) -> JobOutcome:
        heartbeat.stop()
        if heartbeat.deadline_reached or heartbeat.lost:
            return self._heartbeat_outcome(heartbeat)
        try:
            with self._session_factory.begin() as session:
                fail_job(
                    session,
                    claim.analysis_id,
                    claim.lease_token,
                    message,
                    retryable=retryable,
                    lease_deadline=heartbeat.lease_deadline,
                )
            LOGGER.warning(
                "Analysis %s failed (%s).",
                claim.analysis_id,
                error_type,
            )
            return JobOutcome.FAILED
        except JobTransitionError:
            return JobOutcome.LEASE_LOST
        except SQLAlchemyError:
            LOGGER.warning(
                "Could not persist failure for analysis %s; its lease will expire for recovery.",
                claim.analysis_id,
            )
            return JobOutcome.INTERRUPTED


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be finite and greater than zero")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process queued Catalog Rescue analyses.")
    parser.add_argument(
        "--poll-interval",
        type=_positive_float,
        default=_positive_float(os.getenv("CATALOG_RESCUE_WORKER_POLL_SECONDS", "2")),
    )
    parser.add_argument(
        "--lease-seconds",
        type=_positive_float,
        default=_positive_float(
            os.getenv(
                "CATALOG_RESCUE_WORKER_LEASE_SECONDS",
                str(DEFAULT_LEASE_DURATION.total_seconds()),
            )
        ),
    )
    parser.add_argument(
        "--renew-interval",
        type=_positive_float,
        default=_positive_float(
            os.getenv(
                "CATALOG_RESCUE_WORKER_RENEW_SECONDS",
                str(DEFAULT_RENEW_INTERVAL),
            )
        ),
    )
    parser.add_argument(
        "--max-processing-seconds",
        type=_positive_float,
        default=_positive_float(
            os.getenv(
                "CATALOG_RESCUE_WORKER_MAX_PROCESSING_SECONDS",
                str(DEFAULT_MAX_PROCESSING_SECONDS),
            )
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stop_event = threading.Event()
    previous_handlers = {}

    def request_shutdown(_signum, _frame):
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_shutdown)

    try:
        worker = CatalogAnalysisWorker(
            poll_interval_seconds=args.poll_interval,
            lease_duration_seconds=args.lease_seconds,
            renew_interval_seconds=args.renew_interval,
            max_processing_seconds=args.max_processing_seconds,
        )
        worker.run_forever(stop_event)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        dispose_database_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
