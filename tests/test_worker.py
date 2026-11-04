import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, update
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.job_constants import MAX_ATTEMPTS
from database.job_service import claim_next_job, recover_expired_job
from database.models import AnalysisRun, Catalog
from worker import CatalogAnalysisWorker, JobOutcome, _LeaseHeartbeat


SOURCE_CSV = b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"


class CatalogAnalysisWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "worker-tests.sqlite"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def create_job(self, *, original_file=SOURCE_CSV, original_rows=None):
        with self.factory.begin() as session:
            catalog = Catalog(
                original_filename="catalog.csv",
                file_format="csv",
                row_count=1,
                column_count=4,
                column_names=["sku", "product_name", "price", "category"],
                original_file=original_file,
                original_rows=original_rows,
            )
            run = AnalysisRun(
                catalog=catalog,
                status="queued",
                attempt_count=0,
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

    def run_worker(self, **kwargs):
        options = {
            "poll_interval_seconds": 0.01,
            "lease_duration_seconds": 6,
            "renew_interval_seconds": 0.2,
        }
        options.update(kwargs)
        return CatalogAnalysisWorker(
            self.factory,
            **options,
        )

    def get_run(self, run_id):
        with self.factory() as session:
            return session.get(AnalysisRun, run_id)

    def test_successful_processing_persists_cleaned_rows_and_full_report(self):
        run_id = self.create_job()
        outcome = self.run_worker().run_once()

        self.assertEqual(outcome, JobOutcome.COMPLETED)
        run = self.get_run(run_id)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.attempt_count, 1)
        self.assertEqual(run.cleaned_record_count, 1)
        self.assertEqual(run.cleaned_rows["rows"][0][0], "SKU-1")
        self.assertIn("quality_report", run.analysis_report)
        self.assertEqual(
            set(run.quality_metrics),
            {"completeness", "validity", "consistency", "uniqueness"},
        )
        self.assertTrue(run.analysis_summary["decision"])

    def test_retryable_analysis_failure_is_persisted(self):
        run_id = self.create_job()

        def fail_analysis(_dataframe):
            raise TimeoutError("temporary")

        outcome = self.run_worker(analysis_function=fail_analysis).run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.FAILED)
        self.assertEqual(run.status, "failed")
        self.assertTrue(run.retryable)
        self.assertEqual(
            run.error_message,
            "Catalog analysis encountered a transient failure.",
        )

    def test_deterministic_analysis_failure_is_not_retryable(self):
        run_id = self.create_job()

        def fail_analysis(_dataframe):
            raise ValueError("invalid input")

        outcome = self.run_worker(analysis_function=fail_analysis).run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.FAILED)
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.retryable)
        self.assertEqual(
            run.error_message,
            "Catalog analysis failed deterministically.",
        )

    def test_unclassified_analysis_exception_is_not_retried(self):
        run_id = self.create_job()

        def fail_analysis(_dataframe):
            raise RuntimeError("unexpected failure")

        outcome = self.run_worker(analysis_function=fail_analysis).run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.FAILED)
        self.assertFalse(run.retryable)
        self.assertEqual(run.error_message, "Catalog analysis failed deterministically.")

    def test_transient_failure_at_attempt_limit_is_not_retryable(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(attempt_count=MAX_ATTEMPTS - 1)
            )

        def fail_analysis(_dataframe):
            raise TimeoutError("temporary")

        outcome = self.run_worker(analysis_function=fail_analysis).run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.FAILED)
        self.assertEqual(run.attempt_count, MAX_ATTEMPTS)
        self.assertFalse(run.retryable)

    def test_processing_deadline_stops_renewal_and_prevents_result_persistence(self):
        run_id = self.create_job()
        started = threading.Event()
        release = threading.Event()
        renew_times = []
        from worker import renew_job_lease as original_renew

        def tracked_renew(*args, **kwargs):
            renew_times.append(time.monotonic())
            return original_renew(*args, **kwargs)

        def blocked_analysis(dataframe):
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test analysis release timed out")
            from catalog_engine import analyze_catalog
            return analyze_catalog(dataframe)

        max_runtime = 1.5
        worker = self.run_worker(
            analysis_function=blocked_analysis,
            lease_duration_seconds=5,
            renew_interval_seconds=0.1,
            max_processing_seconds=max_runtime,
        )
        with patch("worker.renew_job_lease", side_effect=tracked_renew):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker.run_once)
                self.assertTrue(started.wait(timeout=5))
                time.sleep(max_runtime + 0.2)
                renew_count_at_deadline = len(renew_times)
                time.sleep(0.1)
                self.assertEqual(len(renew_times), renew_count_at_deadline)
                self.assertFalse(future.done())
                release.set()
                self.assertEqual(future.result(timeout=5), JobOutcome.MAX_RUNTIME)

        run = self.get_run(run_id)
        self.assertEqual(run.status, "processing")
        self.assertIsNone(run.cleaned_rows)
        self.assertIsNone(run.analysis_report)
        self.assertTrue(renew_times)

    def test_heartbeat_shutdown_is_bounded_when_renewal_blocks(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        started = threading.Event()
        release = threading.Event()

        def blocked_renewal(*_args, **_kwargs):
            started.set()
            release.wait(timeout=5)

        heartbeat = _LeaseHeartbeat(
            self.factory,
            claim,
            lease_duration_seconds=5,
            renew_interval_seconds=0.01,
            max_processing_seconds=10,
            database_operation_timeout_seconds=0.1,
            shutdown_timeout_seconds=0.05,
        )
        with patch("worker.renew_job_lease", side_effect=blocked_renewal):
            heartbeat.start()
            self.assertTrue(started.wait(timeout=5))
            before_stop = time.monotonic()
            self.assertFalse(heartbeat.stop())
            self.assertLess(time.monotonic() - before_stop, 0.5)
            self.assertTrue(heartbeat.lost)
            release.set()
            heartbeat._thread.join(timeout=1)
            self.assertFalse(heartbeat._thread.is_alive())

    def test_permanent_source_failure_is_not_retryable(self):
        run_id = self.create_job(original_file=b"\xffinvalid csv", original_rows=None)

        outcome = self.run_worker().run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.FAILED)
        self.assertEqual(run.status, "failed")
        self.assertFalse(run.retryable)
        self.assertEqual(run.error_message, "Catalog source could not be read.")

    def test_worker_renews_lease_during_long_analysis(self):
        run_id = self.create_job()
        renew_calls = []
        from worker import renew_job_lease as original_renew

        def tracked_renew(*args, **kwargs):
            renew_calls.append(1)
            return original_renew(*args, **kwargs)

        def slow_analysis(dataframe):
            time.sleep(0.7)
            from catalog_engine import analyze_catalog
            return analyze_catalog(dataframe)

        with patch("worker.renew_job_lease", side_effect=tracked_renew):
            outcome = self.run_worker(
                analysis_function=slow_analysis,
                lease_duration_seconds=6,
                renew_interval_seconds=0.1,
            ).run_once()
        self.assertEqual(outcome, JobOutcome.COMPLETED)
        self.assertGreaterEqual(len(renew_calls), 2)
        self.assertEqual(self.get_run(run_id).status, "completed")

    def test_worker_does_not_finalize_after_lease_is_lost(self):
        run_id = self.create_job()
        started = threading.Event()
        continue_analysis = threading.Event()

        def blocked_analysis(dataframe):
            started.set()
            if not continue_analysis.wait(timeout=10):
                raise TimeoutError("test analysis release timed out")
            from catalog_engine import analyze_catalog
            return analyze_catalog(dataframe)

        worker = self.run_worker(
            analysis_function=blocked_analysis,
            renew_interval_seconds=5,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(worker.run_once)
            self.assertTrue(started.wait(timeout=10))
            with self.factory.begin() as session:
                session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == run_id)
                    .values(lease_expires_at=func.datetime("now", "-1 second"))
                )
            with self.factory.begin() as session:
                recover_expired_job(session, run_id)
            with self.factory.begin() as session:
                reassigned = claim_next_job(session)
            continue_analysis.set()
            self.assertEqual(future.result(timeout=15), JobOutcome.LEASE_LOST)

        run = self.get_run(run_id)
        self.assertEqual(run.status, "processing")
        self.assertEqual(run.lease_token, reassigned.lease_token)
        self.assertIsNone(run.analysis_report)

    def test_shutdown_stops_after_current_job_and_leaves_next_queued(self):
        first_id = self.create_job()
        second_id = self.create_job()
        started = threading.Event()
        release = threading.Event()

        def slow_analysis(dataframe):
            started.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test analysis release timed out")
            from catalog_engine import analyze_catalog
            return analyze_catalog(dataframe)

        worker = self.run_worker(analysis_function=slow_analysis)
        stop = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(worker.run_forever, stop)
            self.assertTrue(started.wait(timeout=10))
            stop.set()
            release.set()
            future.result(timeout=15)
        statuses = {
            self.get_run(first_id).status,
            self.get_run(second_id).status,
        }
        self.assertEqual(statuses, {"completed", "queued"})

    def test_expired_job_is_recovered_and_reclaimed(self):
        run_id = self.create_job()
        with self.factory.begin() as session:
            first_claim = claim_next_job(session)
        with self.factory.begin() as session:
            session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(lease_expires_at=func.datetime("now", "-1 second"))
            )

        outcome = self.run_worker().run_once()
        run = self.get_run(run_id)
        self.assertEqual(outcome, JobOutcome.COMPLETED)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.attempt_count, 2)
        self.assertNotEqual(run.lease_token, first_claim.lease_token)


if __name__ == "__main__":
    unittest.main()
