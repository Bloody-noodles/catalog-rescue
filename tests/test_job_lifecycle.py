import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from database.job_lifecycle import (
    DEFAULT_LEASE_DURATION,
    MAX_ATTEMPTS,
    JobTransitionError,
    complete_run,
    fail_run,
    recover_expired_lease,
    renew_lease,
    retry_failed_run,
    start_processing,
)
from database.models import AnalysisRun


START = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)


def make_run() -> AnalysisRun:
    return AnalysisRun(
        catalog_id=uuid4(),
        status="queued",
        attempt_count=0,
        health_score=0,
        issue_count=0,
        cleaned_record_count=0,
        affected_record_count=0,
        quality_metrics={},
        analysis_summary={},
    )


class AnalysisRunLifecycleTests(unittest.TestCase):
    def test_processing_renewal_and_completion_update_lifecycle_fields(self):
        run = make_run()
        token = start_processing(run, now=START)
        self.assertEqual(run.status, "processing")
        self.assertEqual(run.attempt_count, 1)
        self.assertEqual(run.started_at, START)
        self.assertEqual(run.lease_expires_at, START + DEFAULT_LEASE_DURATION)

        renewed_at = START + timedelta(minutes=4)
        renewed_expiry = renew_lease(run, token, now=renewed_at)
        self.assertEqual(renewed_expiry, renewed_at + DEFAULT_LEASE_DURATION)
        self.assertEqual(run.updated_at, renewed_at)

        completed_at = renewed_at + timedelta(seconds=1)
        complete_run(run, token, now=completed_at)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.completed_at, completed_at)
        self.assertIsNone(run.lease_token)
        self.assertIsNone(run.lease_expires_at)

    def test_invalid_transitions_and_expired_or_stale_lease_are_rejected(self):
        run = make_run()
        token = start_processing(run, now=START)
        with self.assertRaises(JobTransitionError):
            start_processing(run, now=START)
        with self.assertRaises(JobTransitionError):
            renew_lease(run, uuid4(), now=START + timedelta(seconds=1))
        with self.assertRaises(JobTransitionError):
            complete_run(
                run,
                token,
                now=START + DEFAULT_LEASE_DURATION,
            )

    def test_permanent_failure_is_recorded_and_cannot_be_retried(self):
        run = make_run()
        token = start_processing(run, now=START)
        fail_run(
            run,
            token,
            "Invalid catalog format",
            retryable=False,
            now=START + timedelta(seconds=1),
        )
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_message, "Invalid catalog format")
        self.assertFalse(run.retryable)
        with self.assertRaises(JobTransitionError):
            retry_failed_run(run, now=START + timedelta(seconds=2))

    def test_retryable_failure_can_be_requeued_with_bounded_attempts(self):
        run = make_run()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            token = start_processing(
                run,
                now=START + timedelta(minutes=attempt * 10),
            )
            self.assertEqual(run.attempt_count, attempt)
            fail_run(
                run,
                token,
                "Temporary processing failure",
                retryable=True,
                now=START + timedelta(minutes=attempt * 10, seconds=1),
            )
            if attempt < MAX_ATTEMPTS:
                run.cleaned_rows = {"rows": [["stale"]]}
                run.analysis_report = {"stale": True}
                retry_failed_run(
                    run,
                    now=START + timedelta(minutes=attempt * 10, seconds=2),
                )
                self.assertEqual(run.status, "queued")
                self.assertIsNone(run.cleaned_rows)
                self.assertIsNone(run.analysis_report)
            else:
                self.assertFalse(run.retryable)
                with self.assertRaises(JobTransitionError):
                    retry_failed_run(run, now=START + timedelta(hours=1))

    def test_expired_lease_recovers_for_retry_and_rejects_old_worker(self):
        run = make_run()
        old_token = start_processing(run, now=START)
        with self.assertRaises(JobTransitionError):
            recover_expired_lease(run, now=START + DEFAULT_LEASE_DURATION - timedelta(seconds=1))

        recovery_time = START + DEFAULT_LEASE_DURATION
        self.assertEqual(recover_expired_lease(run, now=recovery_time), "queued")
        self.assertFalse(run.retryable)
        self.assertEqual(run.error_message, "Processing lease expired.")
        with self.assertRaises(JobTransitionError):
            complete_run(run, old_token, now=recovery_time)

        new_token = start_processing(run, now=recovery_time + timedelta(seconds=1))
        self.assertNotEqual(old_token, new_token)
        with self.assertRaises(JobTransitionError):
            renew_lease(run, old_token, now=recovery_time + timedelta(seconds=2))

    def test_expired_lease_after_last_attempt_fails_terminally(self):
        run = make_run()
        for attempt in range(MAX_ATTEMPTS):
            started = START + timedelta(minutes=attempt * 10)
            start_processing(run, now=started)
            status = recover_expired_lease(
                run,
                now=started + DEFAULT_LEASE_DURATION,
            )
        self.assertEqual(status, "failed")
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.retryable)
        with self.assertRaises(JobTransitionError):
            start_processing(run, now=START + timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
