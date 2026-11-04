import io
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.auth import VerifiedIdentity, get_authenticated_identity
from api.main import MAX_UPLOAD_BYTES, app
from catalog_engine import analyze_catalog
from catalog_ingestion import load_catalog
from database.base import Base
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User
from database.serialization import dataframe_to_payload
from database.session import create_session_factory, get_api_db_session
from worker import CatalogAnalysisWorker

ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(TEST_ENGINE)
TEST_FACTORY = create_session_factory(TEST_ENGINE)
TEST_IDENTITY = VerifiedIdentity("https://catalog-rescue.test/", "auth0|test-user")
TEST_USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def override_database_session():
    with TEST_FACTORY() as session:
        yield session


app.dependency_overrides[get_api_db_session] = override_database_session
app.dependency_overrides[get_authenticated_identity] = lambda: TEST_IDENTITY
CLIENT = TestClient(app)


class CatalogApiTests(unittest.TestCase):
    def setUp(self):
        with TEST_FACTORY() as session:
            session.execute(delete(IdempotencyRecord))
            session.execute(delete(AnalysisRun))
            session.execute(delete(Catalog))
            user = session.get(User, TEST_USER_ID)
            if user is None:
                session.add(
                    User(
                        id=TEST_USER_ID,
                        issuer=TEST_IDENTITY.issuer,
                        subject=TEST_IDENTITY.subject,
                    )
                )
            session.commit()
            session.commit()

    def create_completed_analysis_from_engine(
        self,
        fixture_path="sample_data/adversarial/05_garbage_values.csv",
    ):
        source_bytes = (ROOT_DIR / fixture_path).read_bytes()
        source = io.BytesIO(source_bytes)
        source.name = "catalog.csv"
        dataframe = load_catalog(source)
        result = analyze_catalog(dataframe)
        result_values = CatalogAnalysisWorker._prepare_results(result)

        catalog = Catalog(
            owner_id=TEST_USER_ID,
            original_filename="catalog.csv",
            file_format="csv",
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            column_names=[str(column) for column in dataframe.columns],
            original_file=source_bytes,
            original_rows=dataframe_to_payload(dataframe),
        )
        with TEST_FACTORY.begin() as session:
            session.add(catalog)
            session.flush()
            analysis = AnalysisRun(
                catalog_id=catalog.id,
                status="completed",
                completed_at=datetime.now(timezone.utc),
                cleaned_rows=result_values["cleaned_rows"],
                analysis_report=result_values["analysis_report"],
                health_score=result_values["health_score"],
                issue_count=result_values["issue_count"],
                cleaned_record_count=result_values["cleaned_record_count"],
                affected_record_count=result_values["affected_record_count"],
                quality_metrics=result_values["quality_metrics"],
                analysis_summary=result_values["analysis_summary"],
            )
            session.add(analysis)
            session.flush()
            analysis_id = analysis.id
        return analysis_id

    def test_health(self):
        response = CLIENT.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_openapi_docs_routes_are_available(self):
        self.assertEqual(CLIENT.get("/openapi.json").status_code, 200)
        self.assertEqual(CLIENT.get("/docs").status_code, 200)

    def test_missing_upload_returns_validation_error(self):
        response = CLIENT.post("/catalogs/analyze")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("Traceback", response.text)

    def test_csv_analysis_persists_original_and_analysis(self):
        path = ROOT_DIR / "sample_data" / "adversarial" / "08_clean_catalog.csv"
        original = path.read_bytes()
        response = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.csv", original, "text/csv")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["records"], 5)
        self.assertEqual(payload["fields"], 8)
        self.assertEqual(payload["cleaned_records"], 5)
        self.assertEqual(
            set(payload["quality_metrics"]),
            {"completeness", "validity", "consistency", "uniqueness"},
        )
        UUID(payload["catalog_id"])
        UUID(payload["analysis_id"])

        with TEST_FACTORY() as session:
            catalog = session.get(Catalog, UUID(payload["catalog_id"]))
            analysis = session.get(AnalysisRun, UUID(payload["analysis_id"]))
            self.assertEqual(catalog.original_file, original)
            self.assertEqual(catalog.original_filename, "catalog.csv")
            self.assertEqual(len(catalog.original_rows["rows"]), 5)
            self.assertEqual(analysis.catalog_id, catalog.id)
            self.assertEqual(analysis.status, "completed")
            self.assertEqual(analysis.attempt_count, 0)
            self.assertIsNotNone(analysis.completed_at)
            self.assertEqual(len(analysis.cleaned_rows["rows"]), 5)
            self.assertIn("quality_report", analysis.analysis_report)

    def test_retrieval_endpoints_return_saved_records(self):
        path = ROOT_DIR / "sample_data" / "adversarial" / "08_clean_catalog.csv"
        original = path.read_bytes()
        created = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.csv", original, "text/csv")},
        )
        self.assertEqual(created.status_code, 200, created.text)
        payload = created.json()
        catalog_id, analysis_id = payload["catalog_id"], payload["analysis_id"]

        self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}").status_code, 200)
        history = CLIENT.get(f"/catalogs/{catalog_id}/analyses")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        detail = CLIENT.get(f"/analyses/{analysis_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("cleaned_rows", detail.json())
        self.assertIn("analysis_report", detail.json())
        self.assertEqual(
            set(detail.json()["analysis_report"]),
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
            },
        )
        download = CLIENT.get(f"/catalogs/{catalog_id}/file")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, original)

    def test_unknown_records_return_404(self):
        missing = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(CLIENT.get(f"/catalogs/{missing}").status_code, 404)
        self.assertEqual(CLIENT.get(f"/catalogs/{missing}/analyses").status_code, 404)
        self.assertEqual(CLIENT.get(f"/analyses/{missing}").status_code, 404)
        self.assertEqual(CLIENT.get(f"/catalogs/{missing}/file").status_code, 404)

    def test_xlsx_analysis_succeeds(self):
        frame = pd.DataFrame({"sku": ["XLSX-1"], "product_name": ["Widget"], "price": [12.5], "category": ["Tools"]})
        content = io.BytesIO()
        frame.to_excel(content, index=False, engine="openpyxl")
        response = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["records"], 1)

    def test_oversized_upload_returns_413(self):
        response = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("large.csv", b"x" * (MAX_UPLOAD_BYTES + 1), "text/csv")},
        )
        self.assertEqual(response.status_code, 413)

    def test_unsupported_file_returns_safe_error(self):
        secret = "PRIVATE_CATALOG_CONTENT"
        response = CLIENT.post("/catalogs/analyze", files={"file": ("catalog.txt", secret.encode(), "text/plain")})
        self.assertEqual(response.status_code, 415)
        self.assertNotIn(secret, response.text)
        self.assertNotIn("Traceback", response.text)

    def test_malformed_csv_returns_safe_error(self):
        secret = "PRIVATE_CATALOG_CONTENT"
        response = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.csv", b"\xff" + secret.encode(), "text/csv")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(secret, response.text)
        self.assertNotIn("Traceback", response.text)

    def test_analysis_failure_saves_no_records(self):
        with patch("api.main.analyze_catalog", side_effect=RuntimeError("secret detail")):
            response = CLIENT.post(
                "/catalogs/analyze",
                files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret detail", response.text)
        with TEST_FACTORY() as session:
            self.assertEqual(session.query(Catalog).count(), 0)
            self.assertEqual(session.query(AnalysisRun).count(), 0)

    def test_async_upload_queues_without_running_analysis(self):
        source = b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"
        with patch("api.main.analyze_catalog", side_effect=AssertionError("analysis was called")):
            response = CLIENT.post(
                "/v2/catalogs/analyze",
                files={"file": ("catalog.csv", source, "text/csv")},
            )
        self.assertEqual(response.status_code, 202, response.text)
        payload = response.json()
        self.assertEqual(payload["status"], "queued")
        catalog_id = UUID(payload["catalog_id"])
        analysis_id = UUID(payload["analysis_id"])
        self.assertEqual(payload["status_url"], f"/analyses/{analysis_id}/status")
        self.assertNotIn("result_url", payload)
        self.assertEqual(response.headers["location"], payload["status_url"])
        self.assertEqual(response.headers["retry-after"], "2")

        with TEST_FACTORY() as session:
            catalog = session.get(Catalog, catalog_id)
            analysis = session.get(AnalysisRun, analysis_id)
            self.assertEqual(catalog.original_file, source)
            self.assertEqual(catalog.row_count, 1)
            self.assertEqual(analysis.catalog_id, catalog_id)
            self.assertEqual(analysis.status, "queued")
            self.assertIsNone(analysis.analysis_report)
            self.assertIsNone(analysis.cleaned_rows)
            self.assertEqual(catalog.owner_id, TEST_USER_ID)

    def test_async_upload_validation_and_size_boundary(self):
        self.assertEqual(CLIENT.post("/v2/catalogs/analyze").status_code, 422)
        unsupported = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.txt", b"private", "text/plain")},
        )
        self.assertEqual(unsupported.status_code, 415)

        malformed = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"\xffprivate", "text/csv")},
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertNotIn("private", malformed.text)

        oversized = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("large.csv", b"x" * (MAX_UPLOAD_BYTES + 1), "text/csv")},
        )
        self.assertEqual(oversized.status_code, 413)

        valid = b"sku\nSKU-1\n"
        exactly_at_limit = valid + b"\n" * (MAX_UPLOAD_BYTES - len(valid))
        boundary = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("boundary.csv", exactly_at_limit, "text/csv")},
        )
        self.assertEqual(boundary.status_code, 202, boundary.text)

    def test_async_upload_is_atomic_and_database_errors_are_sanitized(self):
        def fail_analysis_insert(session, _flush_context, _instances):
            if any(isinstance(item, AnalysisRun) for item in session.new):
                raise SQLAlchemyError("sensitive database details")

        event.listen(Session, "before_flush", fail_analysis_insert)
        try:
            response = CLIENT.post(
                "/v2/catalogs/analyze",
                files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
            )
        finally:
            event.remove(Session, "before_flush", fail_analysis_insert)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive database details", response.text)
        with TEST_FACTORY() as session:
            self.assertEqual(session.query(Catalog).count(), 0)
            self.assertEqual(session.query(AnalysisRun).count(), 0)

    def test_idempotency_replay_mismatch_and_unkeyed_submissions(self):
        source = b"sku\nSKU-1\n"
        headers = {"Idempotency-Key": "request-123"}
        first = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
            headers=headers,
        )
        replay = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
            headers=headers,
        )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["catalog_id"], first.json()["catalog_id"])
        self.assertEqual(replay.json()["analysis_id"], first.json()["analysis_id"])

        with TEST_FACTORY.begin() as session:
            run = session.get(AnalysisRun, UUID(first.json()["analysis_id"]))
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        completed_replay = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
            headers=headers,
        )
        self.assertEqual(completed_replay.json()["status"], "completed")
        self.assertEqual(
            completed_replay.json()["result_url"],
            f"/analyses/{first.json()['analysis_id']}",
        )

        mismatch = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-2\n", "text/csv")},
            headers=headers,
        )
        self.assertEqual(mismatch.status_code, 409)

        unkeyed_a = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
        )
        unkeyed_b = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
        )
        self.assertEqual(unkeyed_a.status_code, 202)
        self.assertEqual(unkeyed_b.status_code, 202)
        self.assertNotEqual(unkeyed_a.json()["analysis_id"], unkeyed_b.json()["analysis_id"])
        with TEST_FACTORY() as session:
            unkeyed_run = session.get(AnalysisRun, UUID(unkeyed_a.json()["analysis_id"]))
            self.assertIsNone(unkeyed_run.idempotency_key)
            self.assertIsNone(unkeyed_run.content_fingerprint)

    def test_authentication_and_resource_ownership(self):
        created = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
        )
        self.assertEqual(created.status_code, 202)
        catalog_id = created.json()["catalog_id"]
        analysis_id = created.json()["analysis_id"]
        owner_submission = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
            headers={"Idempotency-Key": "shared-key"},
        )
        self.assertEqual(owner_submission.status_code, 202)

        identity_override = app.dependency_overrides.pop(get_authenticated_identity)
        try:
            unauthenticated = CLIENT.get(f"/catalogs/{catalog_id}")
        finally:
            app.dependency_overrides[get_authenticated_identity] = identity_override
        self.assertEqual(unauthenticated.status_code, 401)

        other_identity = VerifiedIdentity("https://catalog-rescue.test/", "auth0|other-user")
        with TEST_FACTORY.begin() as session:
            session.add(
                User(
                    issuer=other_identity.issuer,
                    subject=other_identity.subject,
                )
            )
        app.dependency_overrides[get_authenticated_identity] = lambda: other_identity
        try:
            self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}").status_code, 404)
            self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}/analyses").status_code, 404)
            self.assertEqual(CLIENT.get(f"/v2/catalogs/{catalog_id}/analyses").status_code, 404)
            self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}/file").status_code, 404)
            self.assertEqual(CLIENT.get(f"/analyses/{analysis_id}").status_code, 404)
            self.assertEqual(CLIENT.get(f"/analyses/{analysis_id}/status").status_code, 404)
            replay = CLIENT.post(
                "/v2/catalogs/analyze",
                files={"file": ("catalog.csv", b"sku\nSKU-2\n", "text/csv")},
                headers={"Idempotency-Key": "shared-key"},
            )
        finally:
            app.dependency_overrides[get_authenticated_identity] = identity_override

        self.assertEqual(replay.status_code, 202)
        first_owner_retry = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
            headers={"Idempotency-Key": "shared-key"},
        )
        self.assertEqual(first_owner_retry.json()["analysis_id"], owner_submission.json()["analysis_id"])
        self.assertNotEqual(replay.json()["analysis_id"], owner_submission.json()["analysis_id"])

    def test_ownerless_historical_records_are_not_accessible(self):
        catalog = Catalog(
            original_filename="legacy.csv",
            file_format="csv",
            row_count=0,
            column_count=0,
            column_names=[],
        )
        with TEST_FACTORY.begin() as session:
            session.add(catalog)
            session.flush()
            analysis = AnalysisRun(
                catalog_id=catalog.id,
                status="completed",
                completed_at=datetime.now(timezone.utc),
                health_score=0,
                issue_count=0,
                cleaned_record_count=0,
                affected_record_count=0,
                quality_metrics={},
                analysis_summary={},
                cleaned_rows={"columns": [], "rows": []},
                analysis_report={},
            )
            session.add(analysis)
            session.flush()
            catalog_id, analysis_id = catalog.id, analysis.id

        self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}").status_code, 404)
        self.assertEqual(CLIENT.get(f"/analyses/{analysis_id}").status_code, 404)
        self.assertEqual(CLIENT.get(f"/analyses/{analysis_id}/status").status_code, 404)
        self.assertEqual(CLIENT.get(f"/catalogs/{catalog_id}/file").status_code, 404)

    def test_retry_endpoint_requires_owned_retryable_failure(self):
        submitted = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
        )
        analysis_id = UUID(submitted.json()["analysis_id"])
        with TEST_FACTORY.begin() as session:
            analysis = session.get(AnalysisRun, analysis_id)
            analysis.status = "failed"
            analysis.retryable = True
            analysis.attempt_count = 1

        retried = CLIENT.post(f"/analyses/{analysis_id}/retry")
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json(), {"analysis_id": str(analysis_id), "status": "queued"})
        self.assertEqual(CLIENT.post(f"/analyses/{analysis_id}/retry").status_code, 409)

    def test_status_result_gating_and_v2_history(self):
        submitted = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("catalog.csv", b"sku\nSKU-1\n", "text/csv")},
        )
        analysis_id = UUID(submitted.json()["analysis_id"])
        catalog_id = UUID(submitted.json()["catalog_id"])
        status_url = submitted.json()["status_url"]

        status = CLIENT.get(status_url)
        self.assertEqual(status.status_code, 200)
        queued = status.json()
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["analysis_id"], str(analysis_id))
        self.assertNotIn("result_url", queued)
        self.assertIn("created_at", queued)

        with TEST_FACTORY.begin() as session:
            run = session.get(AnalysisRun, analysis_id)
            run.analysis_report = {"stale": True}
        pending_result = CLIENT.get(f"/analyses/{analysis_id}")
        self.assertEqual(pending_result.status_code, 409)
        self.assertNotIn("stale", pending_result.text)

        with TEST_FACTORY.begin() as session:
            run = session.get(AnalysisRun, analysis_id)
            run.status = "processing"
            run.started_at = datetime.now(timezone.utc)
            run.lease_token = uuid4()
            run.lease_expires_at = datetime.now(timezone.utc)
        processing_status = CLIENT.get(status_url)
        self.assertEqual(processing_status.status_code, 200)
        self.assertEqual(processing_status.json()["status"], "processing")
        self.assertNotIn("result_url", processing_status.json())
        self.assertEqual(CLIENT.get(f"/analyses/{analysis_id}").status_code, 409)

        with TEST_FACTORY.begin() as session:
            run = session.get(AnalysisRun, analysis_id)
            run.status = "failed"
            run.retryable = True
            run.error_message = "private SQL and exception details"
            run.lease_token = None
            run.lease_expires_at = None
        failed_status = CLIENT.get(status_url)
        self.assertEqual(failed_status.status_code, 200)
        self.assertTrue(failed_status.json()["retryable"])
        self.assertNotIn("private", failed_status.text)
        failed_result = CLIENT.get(f"/analyses/{analysis_id}")
        self.assertEqual(failed_result.status_code, 409)
        self.assertNotIn("private", failed_result.text)
        self.assertEqual(failed_result.json()["detail"]["status"], "failed")

        history = CLIENT.get(f"/v2/catalogs/{catalog_id}/analyses")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.json()), 1)
        self.assertIsNone(history.json()[0]["completed_at"])
        legacy_history = CLIENT.get(f"/catalogs/{catalog_id}/analyses")
        self.assertEqual(legacy_history.status_code, 200)
        self.assertEqual(legacy_history.json(), [])

    def test_completed_async_result_and_all_status_values(self):
        analysis_id = self.create_completed_analysis_from_engine()
        status = CLIENT.get(f"/analyses/{analysis_id}/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")
        self.assertEqual(status.json()["result_url"], f"/analyses/{analysis_id}")

        result = CLIENT.get(f"/analyses/{analysis_id}")
        self.assertEqual(result.status_code, 200)
        self.assertIn("quality_report", result.json()["analysis_report"])
        self.assertIn("cleaned_rows", result.json())

        incomplete = CLIENT.post(
            "/v2/catalogs/analyze",
            files={"file": ("incomplete.csv", b"sku\nSKU-2\n", "text/csv")},
        )
        incomplete_id = UUID(incomplete.json()["analysis_id"])
        with TEST_FACTORY.begin() as session:
            run = session.get(AnalysisRun, incomplete_id)
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
        incomplete_result = CLIENT.get(f"/analyses/{incomplete_id}")
        self.assertEqual(incomplete_result.status_code, 500)
        self.assertNotIn("analysis_report", incomplete_result.json())

        missing = "00000000-0000-0000-0000-000000000001"
        self.assertEqual(CLIENT.get(f"/analyses/{missing}/status").status_code, 404)

    def test_completed_result_validation_accepts_actual_engine_report(self):
        analysis_id = self.create_completed_analysis_from_engine()

        response = CLIENT.get(f"/analyses/{analysis_id}")

        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()["analysis_report"]
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
            }.issubset(report)
        )
        self.assertEqual(
            response.json()["cleaned_record_count"],
            len(response.json()["cleaned_rows"]["rows"]),
        )

    def test_completed_result_validation_accepts_varied_engine_reports(self):
        fixtures = (
            ("clean", "sample_data/adversarial/08_clean_catalog.csv"),
            ("duplicates", "sample_data/adversarial/04_duplicate_heavy.csv"),
            ("missing_values", "sample_data/adversarial/05_garbage_values.csv"),
            ("automatic_cleaning", "sample_data/adversarial/05_garbage_values.csv"),
            ("torture", "sample_data/torture_catalog.csv"),
        )

        for case, fixture_path in fixtures:
            with self.subTest(case=case):
                analysis_id = self.create_completed_analysis_from_engine(fixture_path)
                response = CLIENT.get(f"/analyses/{analysis_id}")

                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                report = payload["analysis_report"]
                self.assertEqual(
                    payload["cleaned_record_count"],
                    len(payload["cleaned_rows"]["rows"]),
                )
                business_summary = report["quality_report"]["business_summary"]
                self.assertEqual(business_summary["affected_records"], 0)
                self.assertEqual(business_summary["affected_percentage"], 0)
                self.assertEqual(business_summary["issues_resolved"], 0)

                if case == "clean":
                    self.assertEqual(report["issues"], [])
                    self.assertEqual(report["change_log"], [])
                elif case == "duplicates":
                    self.assertGreater(
                        len(report["before_results"]["duplicate_skus"]["rows"]),
                        0,
                    )
                    self.assertGreater(
                        len(report["before_results"]["duplicate_rows"]["rows"]),
                        0,
                    )
                elif case == "missing_values":
                    self.assertGreater(
                        sum(report["before_results"]["missing_values"].values()),
                        0,
                    )
                elif case == "automatic_cleaning":
                    self.assertGreater(len(report["change_log"]), 0)
                    self.assertGreater(
                        report["impact_summary"]["affected_records"],
                        0,
                    )
                    self.assertGreater(
                        report["impact_summary"]["issues_resolved"],
                        0,
                    )
                else:
                    self.assertGreater(len(report["change_log"]), 0)
                    self.assertGreater(
                        sum(report["before_results"]["missing_values"].values()),
                        0,
                    )
                    self.assertGreater(
                        report["impact_summary"]["affected_records"],
                        0,
                    )

    def test_completed_result_validation_rejects_invalid_persisted_results(self):
        invalidations = (
            (
                "unexpected non-empty report",
                lambda run: setattr(run, "analysis_report", {"unexpected": True}),
            ),
            (
                "missing required report section",
                lambda run: setattr(
                    run,
                    "analysis_report",
                    {
                        key: value
                        for key, value in run.analysis_report.items()
                        if key != "quality_report"
                    },
                ),
            ),
            (
                "incorrect report section type",
                lambda run: setattr(
                    run,
                    "analysis_report",
                    {**run.analysis_report, "after_results": []},
                ),
            ),
            (
                "invalid cleaned-row payload",
                lambda run: setattr(
                    run,
                    "cleaned_rows",
                    {"columns": ["sku"], "rows": "not-a-row-list"},
                ),
            ),
            (
                "cleaned-row count mismatch",
                lambda run: setattr(
                    run, "cleaned_record_count", run.cleaned_record_count + 1
                ),
            ),
            (
                "missing quality metric",
                lambda run: setattr(
                    run,
                    "quality_metrics",
                    {
                        key: value
                        for key, value in run.quality_metrics.items()
                        if key != "validity"
                    },
                ),
            ),
            (
                "out-of-range quality metric",
                lambda run: setattr(
                    run,
                    "quality_metrics",
                    {**run.quality_metrics, "validity": 101},
                ),
            ),
        )

        for label, invalidate in invalidations:
            with self.subTest(case=label):
                analysis_id = self.create_completed_analysis_from_engine()
                with TEST_FACTORY.begin() as session:
                    analysis = session.get(AnalysisRun, analysis_id)
                    invalidate(analysis)

                response = CLIENT.get(f"/analyses/{analysis_id}")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(
                    response.json()["detail"],
                    "The stored analysis result is invalid or incomplete.",
                )

                with TEST_FACTORY() as session:
                    stored = session.get(AnalysisRun, analysis_id)
                    self.assertEqual(stored.status, "completed")

    def test_completed_result_validation_preserves_synchronous_api_compatibility(self):
        source = (
            ROOT_DIR / "sample_data" / "adversarial" / "05_garbage_values.csv"
        ).read_bytes()
        created = CLIENT.post(
            "/catalogs/analyze",
            files={"file": ("catalog.csv", source, "text/csv")},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["status"], "completed")

        detail = CLIENT.get(f"/analyses/{created.json()['analysis_id']}")

        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["analysis_report"]["after_results"]["row_count"], 6)

    def test_api_import_does_not_add_fastapi_dependency_to_engine(self):
        script = (
            "import sys; import catalog_engine; import catalog_ingestion; "
            "assert 'fastapi' not in sys.modules; assert 'streamlit' not in sys.modules"
        )
        subprocess.run([sys.executable, "-c", script], cwd=ROOT_DIR, check=True)


if __name__ == "__main__":
    unittest.main()
