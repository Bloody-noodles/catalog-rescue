import os
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.pool import StaticPool

from api.auth import get_authenticated_identity
from api.main import app
from database.base import Base
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User
from database.session import create_session_factory, get_api_db_session


ROOT_DIR = Path(__file__).resolve().parents[1]
ISSUER = "https://catalog-rescue.test/"
AUDIENCE = "https://catalog-rescue.test/api"


class AuthenticatedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.factory = create_session_factory(cls.engine)
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.previous_db_override = app.dependency_overrides.get(get_api_db_session)
        cls.previous_auth_override = app.dependency_overrides.pop(
            get_authenticated_identity,
            None,
        )

        def override_database_session():
            with cls.factory() as session:
                yield session

        app.dependency_overrides[get_api_db_session] = override_database_session
        cls.env = patch.dict(
            os.environ,
            {
                "AUTH0_ISSUER": ISSUER,
                "AUTH0_AUDIENCE": AUDIENCE,
                "AUTH0_JWKS_URL": f"{ISSUER}.well-known/jwks.json",
                "CATALOG_RESCUE_REQUIRED_SCOPE": "catalog:access",
            },
        )
        cls.env.start()
        cls.jwks = patch(
            "api.auth._jwks_client",
            return_value=SimpleNamespace(
                get_signing_key_from_jwt=lambda _token: SimpleNamespace(
                    key=cls.key.public_key()
                )
            ),
        )
        cls.jwks.start()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.jwks.stop()
        cls.env.stop()
        if cls.previous_db_override is None:
            app.dependency_overrides.pop(get_api_db_session, None)
        else:
            app.dependency_overrides[get_api_db_session] = cls.previous_db_override
        if cls.previous_auth_override is not None:
            app.dependency_overrides[get_authenticated_identity] = (
                cls.previous_auth_override
            )
        cls.engine.dispose()

    def setUp(self):
        with self.factory.begin() as session:
            session.execute(delete(IdempotencyRecord))
            session.execute(delete(AnalysisRun))
            session.execute(delete(Catalog))
            session.execute(delete(User))

    @classmethod
    def token(cls, subject="auth0|owner-a", scope="catalog:access"):
        return jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": subject,
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "scope": scope,
            },
            cls.key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )

    @classmethod
    def headers(cls, subject="auth0|owner-a", scope="catalog:access"):
        return {"Authorization": f"Bearer {cls.token(subject, scope)}"}

    def upload_bytes(self):
        return b"sku,product_name,price,category\nSKU-1,Widget,12.5,Tools\n"

    def test_real_bearer_dependency_protects_upload_and_scope_challenge(self):
        missing = self.client.post("/catalogs/analyze")
        self.assertEqual(missing.status_code, 401, missing.text)

        malformed = self.client.post(
            "/catalogs/analyze",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        self.assertEqual(malformed.status_code, 401, malformed.text)

        forbidden = self.client.post(
            "/catalogs/analyze",
            headers=self.headers(scope="profile:read"),
            files={"file": ("catalog.csv", self.upload_bytes(), "text/csv")},
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        self.assertEqual(
            forbidden.headers["www-authenticate"],
            'Bearer error="insufficient_scope", scope="catalog:access"',
        )

        authorized = self.client.post(
            "/v2/catalogs/analyze",
            headers=self.headers(),
            files={"file": ("catalog.csv", self.upload_bytes(), "text/csv")},
        )
        self.assertEqual(authorized.status_code, 202, authorized.text)
        with self.factory() as session:
            catalog = session.get(Catalog, UUID(authorized.json()["catalog_id"]))
            self.assertIsNotNone(catalog)
            self.assertEqual(
                session.scalar(
                    select(User.subject).where(User.id == catalog.owner_id)
                ),
                "auth0|owner-a",
            )

    def test_signed_tokens_scope_sync_async_and_retry_resources_by_owner(self):
        content = self.upload_bytes()
        sync = self.client.post(
            "/catalogs/analyze",
            headers=self.headers(),
            files={"file": ("catalog.csv", content, "text/csv")},
        )
        self.assertEqual(sync.status_code, 200, sync.text)
        sync_catalog_id = sync.json()["catalog_id"]
        sync_analysis_id = sync.json()["analysis_id"]

        self.assertEqual(
            self.client.get(
                f"/catalogs/{sync_catalog_id}", headers=self.headers()
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/catalogs/{sync_catalog_id}/analyses",
                headers=self.headers(),
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/v2/catalogs/{sync_catalog_id}/analyses",
                headers=self.headers(),
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/analyses/{sync_analysis_id}/status", headers=self.headers()
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/analyses/{sync_analysis_id}", headers=self.headers()
            ).status_code,
            200,
        )
        downloaded = self.client.get(
            f"/catalogs/{sync_catalog_id}/file", headers=self.headers()
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, content)

        async_response = self.client.post(
            "/v2/catalogs/analyze",
            headers={**self.headers(), "Idempotency-Key": "retry-owned-job"},
            files={"file": ("catalog.csv", content, "text/csv")},
        )
        self.assertEqual(async_response.status_code, 202, async_response.text)
        async_catalog_id = async_response.json()["catalog_id"]
        async_analysis_id = async_response.json()["analysis_id"]
        with self.factory.begin() as session:
            analysis = session.get(AnalysisRun, UUID(async_analysis_id))
            analysis.status = "failed"
            analysis.retryable = True
            analysis.attempt_count = 1

        other_headers = self.headers(subject="auth0|owner-b")
        protected_urls = (
            f"/catalogs/{sync_catalog_id}",
            f"/catalogs/{sync_catalog_id}/analyses",
            f"/v2/catalogs/{sync_catalog_id}/analyses",
            f"/catalogs/{sync_catalog_id}/file",
            f"/analyses/{sync_analysis_id}",
            f"/analyses/{sync_analysis_id}/status",
            f"/analyses/{async_analysis_id}",
            f"/analyses/{async_analysis_id}/status",
        )
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url, headers=other_headers)
                self.assertEqual(response.status_code, 404, response.text)

        self.assertEqual(
            self.client.post(
                f"/analyses/{async_analysis_id}/retry",
                headers=other_headers,
            ).status_code,
            404,
        )
        retried = self.client.post(
            f"/analyses/{async_analysis_id}/retry",
            headers=self.headers(),
        )
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["status"], "queued")

        with self.factory() as session:
            catalog = session.get(Catalog, UUID(async_catalog_id))
            self.assertEqual(
                session.scalar(
                    select(User.subject).where(User.id == catalog.owner_id)
                ),
                "auth0|owner-a",
            )

    def test_authenticated_requests_cannot_access_ownerless_historical_records(self):
        catalog = Catalog(
            original_filename="historical.csv",
            file_format="csv",
            row_count=0,
            column_count=0,
            column_names=[],
        )
        with self.factory.begin() as session:
            session.add(catalog)
            session.flush()
            analysis = AnalysisRun(
                catalog_id=catalog.id,
                status="completed",
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

        paths = (
            f"/catalogs/{catalog_id}",
            f"/catalogs/{catalog_id}/analyses",
            f"/v2/catalogs/{catalog_id}/analyses",
            f"/catalogs/{catalog_id}/file",
            f"/analyses/{analysis_id}",
            f"/analyses/{analysis_id}/status",
            f"/analyses/{analysis_id}/retry",
        )
        for path in paths:
            response = (
                self.client.post(path, headers=self.headers())
                if path.endswith("/retry")
                else self.client.get(path, headers=self.headers())
            )
            with self.subTest(path=path):
                self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
