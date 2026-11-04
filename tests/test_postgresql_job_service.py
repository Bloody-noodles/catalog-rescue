import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from api.auth import VerifiedIdentity, get_authenticated_identity
from api.main import app
from database.base import Base
from database.job_constants import MAX_ATTEMPTS
from database.job_lifecycle import JobTransitionError
from database.job_service import (
    claim_next_job,
    complete_job,
    recover_expired_job,
    renew_job_lease,
)
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User
from database.ownership import persist_idempotency_record
from database.session import get_api_db_session
from worker import CatalogAnalysisWorker, JobOutcome


TEST_DATABASE_URL = os.environ.get("CATALOG_RESCUE_TEST_DATABASE_URL")
ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_IDENTITY = VerifiedIdentity("https://catalog-rescue.test/", "auth0|postgres-test-user")
TEST_USER_ID = UUID("22222222-2222-4222-8222-222222222222")


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "Set CATALOG_RESCUE_TEST_DATABASE_URL to a disposable PostgreSQL test database.",
)
class PostgreSQLJobServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_DATABASE_URL)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("CATALOG_RESCUE_TEST_DATABASE_URL must be PostgreSQL.")
        cls.admin_engine = create_engine(url, pool_pre_ping=True)
        cls.schema = f"catalog_rescue_test_{uuid4().hex}"
        with cls.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{cls.schema}"'))
        cls.engine = create_engine(
            url,
            connect_args={"options": f"-csearch_path={cls.schema}"},
            pool_pre_ping=True,
        )
        Base.metadata.create_all(cls.engine)
        cls.factory = sessionmaker(cls.engine, expire_on_commit=False)
        with cls.factory.begin() as session:
            session.add(
                User(
                    id=TEST_USER_ID,
                    issuer=TEST_IDENTITY.issuer,
                    subject=TEST_IDENTITY.subject,
                )
            )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "admin_engine") and hasattr(cls, "schema"):
            with cls.admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{cls.schema}" CASCADE'))
            cls.admin_engine.dispose()

    def setUp(self):
        self.previous_database_override = app.dependency_overrides.get(
            get_api_db_session
        )
        app.dependency_overrides[get_api_db_session] = (
            self.override_database_session
        )
        self.previous_identity_override = app.dependency_overrides.get(
            get_authenticated_identity
        )
        app.dependency_overrides[get_authenticated_identity] = lambda: TEST_IDENTITY
        with self.factory.begin() as session:
            session.execute(text("DELETE FROM idempotency_records"))
            session.execute(text("DELETE FROM analysis_runs"))
            session.execute(text("DELETE FROM catalogs"))

    def tearDown(self):
        if self.previous_database_override is None:
            app.dependency_overrides.pop(get_api_db_session, None)
        else:
            app.dependency_overrides[get_api_db_session] = (
                self.previous_database_override
            )
        if self.previous_identity_override is None:
            app.dependency_overrides.pop(get_authenticated_identity, None)
        else:
            app.dependency_overrides[get_authenticated_identity] = (
                self.previous_identity_override
            )

    def override_database_session(self):
        with self.factory() as session:
            yield session

    def create_jobs(self, count=1):
        ids = []
        with self.factory.begin() as session:
            catalog = Catalog(
                owner_id=TEST_USER_ID,
                original_filename=f"{uuid4()}.csv",
                file_format="csv",
                row_count=0,
                column_count=0,
                column_names=[],
            )
            session.add(catalog)
            session.flush()
            for _ in range(count):
                run = AnalysisRun(
                    catalog_id=catalog.id,
                    status="queued",
                    attempt_count=0,
                    health_score=0,
                    issue_count=0,
                    cleaned_record_count=0,
                    affected_record_count=0,
                    quality_metrics={},
                    analysis_summary={},
                )
                catalog.original_rows = {
                    "columns": ["sku", "product_name", "price", "category"],
                    "rows": [["SKU-1", "Widget", 12.5, "Tools"]],
                }
                session.add(run)
                session.flush()
                ids.append(run.id)
        return ids

    def claim_in_new_transaction(self, barrier=None):
        with self.factory.begin() as session:
            if barrier:
                barrier.wait(timeout=10)
            return claim_next_job(session)

    def create_migration_schema(self):
        schema = f"catalog_rescue_migration_test_{uuid4().hex}"
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = self.admin_engine.url.set(
            query={
                **self.admin_engine.url.query,
                "options": f"-csearch_path={schema}",
            }
        )
        return schema, url.render_as_string(hide_password=False)

    def run_migrations(self, database_url, revision, *, downgrade=False):
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            config = Config(str(ROOT_DIR / "alembic.ini"))
            migration_command = command.downgrade if downgrade else command.upgrade
            migration_command(config, revision)
        finally:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url

    def insert_migration_fixture(self, connection, catalog_id, analysis_id, key=None):
        connection.execute(
            text(
                "INSERT INTO catalogs "
                "(id, original_filename, file_format, row_count, column_count, "
                "column_names) "
                "VALUES (:id, 'legacy.csv', 'csv', 1, 1, '[\"sku\"]'::json)"
            ),
            {"id": catalog_id},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_runs "
                "(id, catalog_id, status, completed_at, health_score, issue_count, "
                "cleaned_record_count, affected_record_count, quality_metrics, "
                "analysis_summary, idempotency_key, content_fingerprint) "
                "VALUES (:id, :catalog_id, 'completed', now(), 90, 1, 1, 1, "
                "'{}'::json, '{}'::json, :key, :fingerprint)"
            ),
            {
                "id": analysis_id,
                "catalog_id": catalog_id,
                "key": key,
                "fingerprint": "c" * 64 if key else None,
            },
        )

    def test_two_workers_competing_for_one_job(self):
        self.create_jobs(1)
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: self.claim_in_new_transaction(barrier),
                    range(2),
                )
            )
        claims = [claim for claim in results if claim is not None]
        self.assertEqual(len(claims), 1)

    def test_two_workers_claim_different_jobs(self):
        self.create_jobs(2)
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda _: self.claim_in_new_transaction(barrier),
                    range(2),
                )
            )
        self.assertTrue(all(claim is not None for claim in claims))
        self.assertEqual(len({claim.analysis_id for claim in claims}), 2)

    def test_expired_lease_recovery_and_old_owner_cannot_complete_after_reassignment(self):
        (run_id,) = self.create_jobs(1)
        with self.factory.begin() as session:
            old_claim = claim_next_job(session)
        with self.factory.begin() as session:
            session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
        with self.factory.begin() as session:
            self.assertEqual(recover_expired_job(session, run_id), "queued")
        with self.factory.begin() as session:
            new_claim = claim_next_job(session)
        self.assertNotEqual(old_claim.lease_token, new_claim.lease_token)
        with self.factory.begin() as session:
            with self.assertRaises(JobTransitionError):
                complete_job(session, run_id, old_claim.lease_token)
        with self.factory.begin() as session:
            complete_job(session, run_id, new_claim.lease_token)

    def test_renewal_after_expiration_is_rejected_by_database_clock(self):
        (run_id,) = self.create_jobs(1)
        with self.factory.begin() as session:
            claim = claim_next_job(session)
        with self.factory.begin() as session:
            session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id)
                .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
            )
        with self.factory.begin() as session:
            with self.assertRaises(JobTransitionError):
                renew_job_lease(session, run_id, claim.lease_token)

    def test_retry_exhaustion_after_repeated_expired_claims(self):
        (run_id,) = self.create_jobs(1)
        for expected_attempt in range(1, MAX_ATTEMPTS + 1):
            with self.factory.begin() as session:
                claim = claim_next_job(session)
            self.assertEqual(claim.attempt_count, expected_attempt)
            with self.factory.begin() as session:
                session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == run_id)
                    .values(lease_expires_at=text("clock_timestamp() - interval '1 second'"))
                )
            with self.factory.begin() as session:
                next_status = recover_expired_job(session, run_id)
            if expected_attempt < MAX_ATTEMPTS:
                self.assertEqual(next_status, "queued")
            else:
                self.assertEqual(next_status, "failed")
        with self.factory.begin() as session:
            self.assertIsNone(claim_next_job(session))

    def test_rollback_during_claim_restores_queued_state(self):
        (run_id,) = self.create_jobs(1)
        with self.assertRaisesRegex(RuntimeError, "rollback claim"):
            with self.factory.begin() as session:
                claim_next_job(session)
                raise RuntimeError("rollback claim")
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.attempt_count, 0)
            self.assertIsNone(run.lease_token)

    def test_worker_persists_results_atomically_in_postgresql(self):
        (run_id,) = self.create_jobs(1)
        worker = CatalogAnalysisWorker(
            self.factory,
            poll_interval_seconds=0.1,
            lease_duration_seconds=15,
            renew_interval_seconds=2,
        )
        self.assertEqual(worker.run_once(), JobOutcome.COMPLETED)
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.attempt_count, 1)
            self.assertIsNotNone(run.completed_at)
            self.assertIsNotNone(run.cleaned_rows)
            self.assertIn("quality_report", run.analysis_report)

    def test_worker_losing_reassigned_lease_cannot_persist_analysis_result(self):
        (run_id,) = self.create_jobs(1)
        analysis_started = threading.Event()
        release_analysis = threading.Event()

        def delayed_analysis(dataframe):
            from catalog_engine import analyze_catalog
            analysis_started.set()
            if not release_analysis.wait(timeout=10):
                raise TimeoutError("test analysis release timed out")
            return analyze_catalog(dataframe)

        worker = CatalogAnalysisWorker(
            self.factory,
            poll_interval_seconds=0.1,
            lease_duration_seconds=30,
            renew_interval_seconds=10,
            analysis_function=delayed_analysis,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(worker.run_once)
            self.assertTrue(analysis_started.wait(timeout=10))
            with self.factory.begin() as session:
                session.execute(
                    update(AnalysisRun)
                    .where(AnalysisRun.id == run_id)
                    .values(
                        lease_expires_at=text(
                            "clock_timestamp() - interval '1 second'"
                        )
                    )
                )
            with self.factory.begin() as session:
                self.assertEqual(recover_expired_job(session, run_id), "queued")
            with self.factory.begin() as session:
                replacement = claim_next_job(session)
            release_analysis.set()
            self.assertEqual(future.result(timeout=15), JobOutcome.LEASE_LOST)

        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "processing")
            self.assertEqual(run.lease_token, replacement.lease_token)
            self.assertIsNone(run.cleaned_rows)
            self.assertIsNone(run.analysis_report)

    def test_worker_max_runtime_expires_lease_and_fences_still_running_analysis(self):
        (run_id,) = self.create_jobs(1)
        analysis_started = threading.Event()
        release_analysis = threading.Event()
        max_processing_seconds = 10
        analysis_started_at = []

        def delayed_analysis(dataframe):
            from catalog_engine import analyze_catalog
            analysis_started_at.append(time.monotonic())
            analysis_started.set()
            if not release_analysis.wait(timeout=max_processing_seconds + 20):
                raise TimeoutError("test analysis release timed out")
            return analyze_catalog(dataframe)

        limited_worker = CatalogAnalysisWorker(
            self.factory,
            lease_duration_seconds=15,
            renew_interval_seconds=0.05,
            max_processing_seconds=max_processing_seconds,
            analysis_function=delayed_analysis,
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(limited_worker.run_once)
            if not analysis_started.wait(timeout=max_processing_seconds + 10):
                if future.done():
                    try:
                        outcome = future.result()
                    except Exception as exc:
                        self.fail(
                            "Worker future raised before analysis started: "
                            f"{type(exc).__name__}: {exc}"
                        )
                    self.fail(
                        "Worker future returned before analysis started: "
                        f"{outcome!r}"
                    )
                self.fail(
                    "Analysis callback did not start and worker future is still running."
                )

            try:
                remaining_runtime = (
                    analysis_started_at[0]
                    + max_processing_seconds
                    - time.monotonic()
                )
                if remaining_runtime > 0:
                    time.sleep(remaining_runtime)

                lease_expired = False
                expiry_wait_deadline = time.monotonic() + 10
                while time.monotonic() < expiry_wait_deadline:
                    with self.factory() as session:
                        lease_expired = session.scalar(
                            select(
                                AnalysisRun.lease_expires_at
                                <= func.clock_timestamp()
                            ).where(AnalysisRun.id == run_id)
                        )
                    if lease_expired:
                        break
                    time.sleep(0.05)
                self.assertTrue(
                    lease_expired,
                    "The claimed job lease did not expire after maximum processing time.",
                )

                recovery_worker = CatalogAnalysisWorker(
                    self.factory,
                    lease_duration_seconds=15,
                    renew_interval_seconds=2,
                )
                self.assertEqual(recovery_worker.run_once(), JobOutcome.COMPLETED)
            finally:
                release_analysis.set()
            self.assertEqual(future.result(timeout=10), JobOutcome.MAX_RUNTIME)

        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.attempt_count, 2)
            self.assertIsNotNone(run.analysis_report)

    def test_concurrent_async_idempotency_submissions_create_one_postgresql_job(self):
        previous_override = app.dependency_overrides.get(get_api_db_session)

        def override_database_session():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_api_db_session] = override_database_session
        content = b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"

        def submit():
            with TestClient(app) as client:
                return client.post(
                    "/v2/catalogs/analyze",
                    files={"file": ("catalog.csv", content, "text/csv")},
                    headers={"Idempotency-Key": "parallel-postgres-request"},
                )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: submit(), range(2)))
        finally:
            if previous_override is None:
                app.dependency_overrides.pop(get_api_db_session, None)
            else:
                app.dependency_overrides[get_api_db_session] = previous_override

        self.assertEqual([response.status_code for response in responses], [202, 202])
        payloads = [response.json() for response in responses]
        self.assertEqual(payloads[0]["analysis_id"], payloads[1]["analysis_id"])
        self.assertEqual(payloads[0]["catalog_id"], payloads[1]["catalog_id"])
        with self.factory() as session:
            matching_runs = list(
                session.scalars(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.owner_id == TEST_USER_ID,
                        IdempotencyRecord.key == "parallel-postgres-request",
                    )
                )
            )
            self.assertEqual(len(matching_runs), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Catalog)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(AnalysisRun)), 1)

    def test_concurrent_same_key_different_fingerprints_returns_conflict_without_orphans(self):
        contents = (
            b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n",
            b"sku,product_name,price,category\nSKU-2,Gadget,20,Tools\n",
        )
        barrier = threading.Barrier(2)

        def submit(content):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.post(
                    "/v2/catalogs/analyze",
                    files={"file": ("catalog.csv", content, "text/csv")},
                    headers={"Idempotency-Key": "parallel-different-content"},
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(submit, contents))

        self.assertEqual(sorted(response.status_code for response in responses), [202, 409])
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Catalog)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(AnalysisRun)), 1)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(IdempotencyRecord)),
                1,
            )

    def test_same_idempotency_key_is_isolated_between_owners(self):
        first_identity = TEST_IDENTITY
        second_identity = VerifiedIdentity(
            TEST_IDENTITY.issuer,
            f"auth0|second-owner-{uuid4()}",
        )
        content = b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"

        def submit(identity):
            app.dependency_overrides[get_authenticated_identity] = (
                lambda identity=identity: identity
            )
            with TestClient(app) as client:
                return client.post(
                    "/v2/catalogs/analyze",
                    files={"file": ("catalog.csv", content, "text/csv")},
                    headers={"Idempotency-Key": "same-key-different-owners"},
                )

        first = submit(first_identity)
        second = submit(second_identity)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertNotEqual(first.json()["analysis_id"], second.json()["analysis_id"])
        self.assertNotEqual(first.json()["catalog_id"], second.json()["catalog_id"])

        first_replay = submit(first_identity)
        second_replay = submit(second_identity)
        self.assertEqual(first_replay.json()["analysis_id"], first.json()["analysis_id"])
        self.assertEqual(second_replay.json()["analysis_id"], second.json()["analysis_id"])

        app.dependency_overrides[get_authenticated_identity] = lambda: first_identity
        with TestClient(app) as client:
            self.assertEqual(
                client.get(f"/analyses/{second.json()['analysis_id']}").status_code,
                404,
            )
        app.dependency_overrides[get_authenticated_identity] = lambda: second_identity
        with TestClient(app) as client:
            self.assertEqual(
                client.get(f"/analyses/{first.json()['analysis_id']}").status_code,
                404,
            )

    def test_unkeyed_async_submissions_create_independent_jobs(self):
        content = b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"

        def submit():
            with TestClient(app) as client:
                return client.post(
                    "/v2/catalogs/analyze",
                    files={"file": ("catalog.csv", content, "text/csv")},
                )

        first, second = submit(), submit()
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertNotEqual(first.json()["analysis_id"], second.json()["analysis_id"])
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Catalog)), 2)
            self.assertEqual(session.scalar(select(func.count()).select_from(AnalysisRun)), 2)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(IdempotencyRecord)),
                0,
            )

    def test_postgresql_foreign_keys_and_owner_consistency_roll_back(self):
        analysis_id = self.create_jobs(1)[0]
        with self.factory() as session:
            analysis = session.get(AnalysisRun, analysis_id)
            owner_id = TEST_USER_ID

        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.add(
                    IdempotencyRecord(
                        owner_id=uuid4(),
                        key="invalid-owner-fk",
                        request_fingerprint="a" * 64,
                        analysis_id=analysis_id,
                    )
                )
                session.flush()

        with self.assertRaises(IntegrityError):
            with self.factory.begin() as session:
                session.add(
                    IdempotencyRecord(
                        owner_id=owner_id,
                        key="invalid-analysis-fk",
                        request_fingerprint="b" * 64,
                        analysis_id=uuid4(),
                    )
                )
                session.flush()

        with self.assertRaisesRegex(ValueError, "must own the associated catalog"):
            with self.factory.begin() as session:
                owner = session.get(User, owner_id)
                other_owner = User(
                    issuer=TEST_IDENTITY.issuer,
                    subject=f"auth0|mismatch-{uuid4()}",
                )
                catalog = Catalog(
                    owner=other_owner,
                    original_filename="mismatch.csv",
                    file_format="csv",
                    row_count=0,
                    column_count=0,
                    column_names=[],
                )
                session.add_all([other_owner, catalog])
                session.flush()
                analysis = AnalysisRun(
                    catalog=catalog,
                    status="queued",
                    attempt_count=0,
                    retryable=False,
                    health_score=0,
                    issue_count=0,
                    cleaned_record_count=0,
                    affected_record_count=0,
                    quality_metrics={},
                    analysis_summary={},
                )
                session.add(analysis)
                session.flush()
                persist_idempotency_record(
                    session,
                    owner=owner,
                    catalog=catalog,
                    analysis=analysis,
                    key="mismatch-owner",
                    request_fingerprint="c" * 64,
                )

        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Catalog)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(AnalysisRun)), 1)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(IdempotencyRecord)),
                0,
            )

    def test_unrelated_integrity_errors_are_not_replayed(self):
        def violate_catalog_check(session, _flush_context, _instances):
            for item in session.new:
                if isinstance(item, Catalog):
                    item.column_count = -1

        event.listen(Session, "before_flush", violate_catalog_check)
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/v2/catalogs/analyze",
                    files={
                        "file": (
                            "catalog.csv",
                            b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n",
                            "text/csv",
                        )
                    },
                    headers={"Idempotency-Key": "unrelated-integrity-error"},
                )
        finally:
            event.remove(Session, "before_flush", violate_catalog_check)

        self.assertEqual(response.status_code, 503, response.text)
        with self.factory() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Catalog)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(AnalysisRun)), 0)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(IdempotencyRecord)),
                0,
            )

    def test_worker_processes_job_created_by_async_postgresql_api(self):
        previous_override = app.dependency_overrides.get(get_api_db_session)

        def override_database_session():
            with self.factory() as session:
                yield session

        app.dependency_overrides[get_api_db_session] = override_database_session
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/v2/catalogs/analyze",
                    files={
                        "file": (
                            "catalog.csv",
                            b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n",
                            "text/csv",
                        )
                    },
                )
        finally:
            if previous_override is None:
                app.dependency_overrides.pop(get_api_db_session, None)
            else:
                app.dependency_overrides[get_api_db_session] = previous_override

        self.assertEqual(response.status_code, 202, response.text)
        run_id = UUID(response.json()["analysis_id"])
        worker = CatalogAnalysisWorker(
            self.factory,
            poll_interval_seconds=0.1,
            lease_duration_seconds=15,
            renew_interval_seconds=2,
        )
        self.assertEqual(worker.run_once(), JobOutcome.COMPLETED)
        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.attempt_count, 1)
            self.assertIsNotNone(run.analysis_report)
            self.assertIsNotNone(run.cleaned_rows)
            cleaned_record_count = run.cleaned_record_count

        app.dependency_overrides[get_api_db_session] = override_database_session
        try:
            with TestClient(app) as client:
                result = client.get(f"/analyses/{run_id}")
        finally:
            if previous_override is None:
                app.dependency_overrides.pop(get_api_db_session, None)
            else:
                app.dependency_overrides[get_api_db_session] = previous_override

        self.assertEqual(result.status_code, 200, result.text)
        result_payload = result.json()
        self.assertTrue(
            {
                "before_results",
                "after_results",
                "impact_summary",
                "quality_report",
                "business_decision",
                "issues",
                "action_report",
                "change_log",
                "issue_table",
                "export_report",
            }.issubset(result_payload["analysis_report"])
        )
        self.assertEqual(
            len(result_payload["cleaned_rows"]["rows"]),
            cleaned_record_count,
        )

    def test_0006_migration_uses_actual_chain_and_downgrades_safely(self):
        schema, database_url = self.create_migration_schema()
        engine = create_engine(database_url, pool_pre_ping=True)
        catalog_id, second_catalog_id = uuid4(), uuid4()
        analysis_id, second_analysis_id = uuid4(), uuid4()
        user_id = uuid4()
        idempotency_id = uuid4()

        try:
            self.run_migrations(database_url, "0005_async_upload_idempotency")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "0005_async_upload_idempotency",
                )
            with engine.begin() as connection:
                self.insert_migration_fixture(
                    connection, catalog_id, analysis_id, "legacy-global-key"
                )
                self.insert_migration_fixture(
                    connection, second_catalog_id, second_analysis_id
                )

            self.run_migrations(database_url, "0006_user_ownership_idempotency")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "0006_user_ownership_idempotency",
                )
            inspector = inspect(engine)
            self.assertIn("users", inspector.get_table_names())
            self.assertIn("idempotency_records", inspector.get_table_names())
            self.assertIn(
                "owner_id",
                {column["name"] for column in inspector.get_columns("catalogs")},
            )
            unique_constraints = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("analysis_runs")
            }
            self.assertNotIn("uq_analysis_runs_idempotency_key", unique_constraints)
            self.assertIn(
                "uq_users_issuer_subject",
                {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints("users")
                },
            )
            self.assertEqual(
                {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints(
                        "idempotency_records"
                    )
                },
                {
                    "uq_idempotency_records_owner_key",
                    "uq_idempotency_records_analysis_id",
                },
            )

            with engine.begin() as connection:
                self.assertEqual(
                    connection.execute(
                        text(
                            "SELECT COUNT(*) FROM catalogs WHERE id IN (:id, :second_id)"
                        ),
                        {"id": catalog_id, "second_id": second_catalog_id},
                    ).scalar_one(),
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            "SELECT COUNT(*) FROM analysis_runs "
                            "WHERE id IN (:id, :second_id)"
                        ),
                        {"id": analysis_id, "second_id": second_analysis_id},
                    ).scalar_one(),
                    2,
                )
                self.assertIsNone(
                    connection.execute(
                        text("SELECT owner_id FROM catalogs WHERE id = :id"),
                        {"id": catalog_id},
                    ).scalar_one()
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            "SELECT idempotency_key, content_fingerprint "
                            "FROM analysis_runs WHERE id = :id"
                        ),
                        {"id": analysis_id},
                    ).one(),
                    ("legacy-global-key", "c" * 64),
                )

                connection.execute(
                    text(
                        "UPDATE analysis_runs SET idempotency_key = :key "
                        "WHERE id = :id"
                    ),
                    {"key": "legacy-global-key", "id": second_analysis_id},
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            "SELECT COUNT(*) FROM analysis_runs "
                            "WHERE idempotency_key = 'legacy-global-key'"
                        )
                    ).scalar_one(),
                    2,
                )
                connection.execute(
                    text(
                        "UPDATE analysis_runs SET idempotency_key = NULL, "
                        "content_fingerprint = NULL WHERE id = :id"
                    ),
                    {"id": second_analysis_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO users (id, issuer, subject) "
                        "VALUES (:id, :issuer, :subject)"
                    ),
                    {
                        "id": user_id,
                        "issuer": "https://issuer.example/",
                        "subject": "auth0|migration-test",
                    },
                )
                connection.execute(
                    text("UPDATE catalogs SET owner_id = :owner WHERE id = :id"),
                    {"owner": user_id, "id": catalog_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO idempotency_records "
                        "(id, owner_id, key, request_fingerprint, analysis_id) "
                        "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
                    ),
                    {
                        "id": idempotency_id,
                        "owner": user_id,
                        "key": "user-key",
                        "fingerprint": "d" * 64,
                        "analysis": analysis_id,
                    },
                )

            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO users (id, issuer, subject) "
                            "VALUES (:id, :issuer, :subject)"
                        ),
                        {
                            "id": uuid4(),
                            "issuer": "https://issuer.example/",
                            "subject": "auth0|migration-test",
                        },
                    )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text("UPDATE catalogs SET owner_id = :owner WHERE id = :id"),
                        {"owner": uuid4(), "id": second_catalog_id},
                    )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO idempotency_records "
                            "(id, owner_id, key, request_fingerprint, analysis_id) "
                            "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
                        ),
                        {
                            "id": uuid4(),
                            "owner": user_id,
                            "key": "user-key",
                            "fingerprint": "e" * 64,
                            "analysis": second_analysis_id,
                        },
                    )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO idempotency_records "
                            "(id, owner_id, key, request_fingerprint, analysis_id) "
                            "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
                        ),
                        {
                            "id": uuid4(),
                            "owner": user_id,
                            "key": "different-key",
                            "fingerprint": "e" * 64,
                            "analysis": analysis_id,
                        },
                    )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO idempotency_records "
                            "(id, owner_id, key, request_fingerprint, analysis_id) "
                            "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
                        ),
                        {
                            "id": uuid4(),
                            "owner": uuid4(),
                            "key": "unknown-owner",
                            "fingerprint": "e" * 64,
                            "analysis": second_analysis_id,
                        },
                    )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO idempotency_records "
                            "(id, owner_id, key, request_fingerprint, analysis_id) "
                            "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
                        ),
                        {
                            "id": uuid4(),
                            "owner": user_id,
                            "key": "unknown-analysis",
                            "fingerprint": "e" * 64,
                            "analysis": uuid4(),
                        },
                    )

            with self.assertRaisesRegex(RuntimeError, "ownership or idempotency data"):
                self.run_migrations(
                    database_url,
                    "0005_async_upload_idempotency",
                    downgrade=True,
                )

            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM idempotency_records WHERE id = :id"),
                    {"id": idempotency_id},
                )
                connection.execute(
                    text("UPDATE catalogs SET owner_id = NULL WHERE id = :id"),
                    {"id": catalog_id},
                )
                connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

            self.run_migrations(
                database_url,
                "0005_async_upload_idempotency",
                downgrade=True,
            )
            inspector = inspect(engine)
            self.assertNotIn("users", inspector.get_table_names())
            self.assertNotIn("idempotency_records", inspector.get_table_names())
            self.assertNotIn(
                "owner_id",
                {column["name"] for column in inspector.get_columns("catalogs")},
            )
            self.assertIn(
                "uq_analysis_runs_idempotency_key",
                {
                    constraint["name"]
                    for constraint in inspector.get_unique_constraints("analysis_runs")
                },
            )
            with self.assertRaises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE analysis_runs SET idempotency_key = :key "
                            "WHERE id = :id"
                        ),
                        {"key": "legacy-global-key", "id": second_analysis_id},
                    )
            with engine.begin() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT COUNT(*) FROM catalogs")).scalar_one(),
                    2,
                )
                self.assertEqual(
                    connection.execute(
                        text("SELECT COUNT(*) FROM analysis_runs")
                    ).scalar_one(),
                    2,
                )
        finally:
            engine.dispose()
            with self.admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))

    def test_heartbeat_statement_timeout_relinquishes_ownership(self):
        (run_id,) = self.create_jobs(1)
        analysis_started = threading.Event()
        release_analysis = threading.Event()

        def delayed_analysis(dataframe):
            from catalog_engine import analyze_catalog
            analysis_started.set()
            if not release_analysis.wait(timeout=10):
                raise TimeoutError("test analysis release timed out")
            return analyze_catalog(dataframe)

        worker = CatalogAnalysisWorker(
            self.factory,
            lease_duration_seconds=15,
            renew_interval_seconds=0.05,
            max_processing_seconds=10,
            database_operation_timeout_seconds=0.1,
            heartbeat_shutdown_timeout_seconds=0.5,
            analysis_function=delayed_analysis,
        )
        lock_session = self.factory()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(worker.run_once)
                self.assertTrue(analysis_started.wait(timeout=10))
                lock_session.begin()
                lock_session.execute(
                    select(AnalysisRun.id)
                    .where(AnalysisRun.id == run_id)
                    .with_for_update()
                ).one()
                time.sleep(0.35)
                release_analysis.set()
                self.assertEqual(future.result(timeout=5), JobOutcome.LEASE_LOST)
        finally:
            lock_session.rollback()
            lock_session.close()

        with self.factory() as session:
            run = session.get(AnalysisRun, run_id)
            self.assertEqual(run.status, "processing")
            self.assertIsNone(run.analysis_report)


if __name__ == "__main__":
    unittest.main()
