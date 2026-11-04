import unittest
from uuid import uuid4

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.job_constants import MAX_ATTEMPTS
from database.job_lifecycle import JobTransitionError
from database.job_service import (
    claim_next_job,
    complete_job,
    fail_job,
    recover_expired_job,
    renew_job_lease,
    retry_failed_job,
)
from database.models import AnalysisRun, Catalog


class AnalysisJobServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def create_job(self, *, status="queued", attempt_count=0):
        with self.factory.begin() as session:
            catalog = Catalog(
                original_filename=f"{uuid4()}.csv",
                file_format="csv",
                row_count=0,
                column_count=0,
                column_names=[],
            )
            run = AnalysisRun(
                catalog=catalog,
                status=status,
                attempt_count=attempt_count,
                health_score=0,
                issue_count=0,
                cleaned_record_count=0,
                affected_record_count=0,
                quality_metrics={},
                analysis_summary={},
            )
            session.add(run)
            session.flush()
            return run.id

    def test_claim_increments_attempt_and_database_transitions_are_conditional(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        self.assertIsNotNone(claim)
        self.assertEqual(claim.attempt_count, 1)

        with self.factory.begin() as session:
            with self.assertRaises(JobTransitionError):
                complete_job(session, run_id, uuid4())
        with self.factory.begin() as session:
            complete_job(session, run_id, claim.lease_token)
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "completed")
            self.assertFalse(run.retryable)

    def test_retryable_failure_and_expired_lease_recovery_are_persisted(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        with self.factory.begin() as session:
            fail_job(
                session,
                run_id,
                claim.lease_token,
                "temporary",
                retryable=True,
            )
        with self.factory.begin() as session:
            retry_failed_job(session, run_id)
        with self.factory.begin() as session:
            next_claim = claim_next_job(session)
        self.assertEqual(next_claim.attempt_count, 2)

        with self.factory.begin() as session:
            session.execute(
                AnalysisRun.__table__.update()
                .where(AnalysisRun.id == run_id)
                .values(
                    lease_expires_at=func.datetime("now", "-1 second")
                )
            )
        with self.factory.begin() as session:
            self.assertEqual(recover_expired_job(session, run_id), "queued")
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "queued")
            self.assertFalse(run.retryable)
            self.assertEqual(run.error_message, "Processing lease expired.")

        with self.factory.begin() as session:
            new_claim = claim_next_job(session)
        self.assertNotEqual(next_claim.lease_token, new_claim.lease_token)
        with self.factory.begin() as session:
            with self.assertRaises(JobTransitionError):
                complete_job(session, run_id, next_claim.lease_token)
        with self.factory.begin() as session:
            complete_job(session, run_id, new_claim.lease_token)

    def test_requeue_clears_previous_attempt_result_fields(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        with self.factory.begin() as session:
            fail_job(
                session,
                run_id,
                claim.lease_token,
                "temporary",
                retryable=True,
            )
            session.execute(
                AnalysisRun.__table__.update()
                .where(AnalysisRun.id == run_id)
                .values(
                    health_score=87,
                    issue_count=4,
                    cleaned_record_count=12,
                    affected_record_count=3,
                    quality_metrics={"old": True},
                    analysis_summary={"old": True},
                    cleaned_rows={"columns": ["old"], "rows": [[1]]},
                    analysis_report={"old": True},
                )
            )

        with self.factory.begin() as session:
            retry_failed_job(session, run_id)

        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.health_score, 0)
            self.assertEqual(run.issue_count, 0)
            self.assertEqual(run.cleaned_record_count, 0)
            self.assertEqual(run.affected_record_count, 0)
            self.assertEqual(run.quality_metrics, {})
            self.assertEqual(run.analysis_summary, {})
            self.assertIsNone(run.cleaned_rows)
            self.assertIsNone(run.analysis_report)

    def test_retryable_failure_is_rejected_at_attempt_limit(self):
        run_id = self.create_job(attempt_count=MAX_ATTEMPTS - 1)
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        self.assertEqual(claim.attempt_count, MAX_ATTEMPTS)
        with self.factory.begin() as session:
            fail_job(
                session,
                run_id,
                claim.lease_token,
                "last attempt",
                retryable=True,
            )
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "failed")
            self.assertFalse(run.retryable)
        with self.factory.begin() as session:
            with self.assertRaises(JobTransitionError):
                retry_failed_job(session, run_id)

    def test_rollback_restores_job_to_queued(self):
        run_id = self.create_job()
        with self.assertRaisesRegex(RuntimeError, "force rollback"):
            with self.factory.begin() as session:
                claim_next_job(session)
                raise RuntimeError("force rollback")
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.attempt_count, 0)
            self.assertIsNone(run.lease_token)
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        self.assertEqual(claim.attempt_count, 1)


if __name__ == "__main__":
    unittest.main()
