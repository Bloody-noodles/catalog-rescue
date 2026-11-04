import os
import unittest
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


TEST_DATABASE_URL = os.environ.get("CATALOG_RESCUE_TEST_DATABASE_URL")
ROOT_DIR = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    TEST_DATABASE_URL,
    "Set CATALOG_RESCUE_TEST_DATABASE_URL to a disposable PostgreSQL test database.",
)
class PostgreSQLMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(TEST_DATABASE_URL)
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        if not url.drivername.startswith("postgresql"):
            raise RuntimeError("CATALOG_RESCUE_TEST_DATABASE_URL must be PostgreSQL.")

        cls.admin_engine = create_engine(url, pool_pre_ping=True)

    def setUp(self):
        self.schema = f"catalog_rescue_migration_test_{uuid4().hex}"
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        url = self.admin_engine.url
        self.database_url = url.set(
            query={
                **url.query,
                "options": f"-csearch_path={self.schema}",
            }
        ).render_as_string(hide_password=False)
        self.engine = create_engine(self.database_url, pool_pre_ping=True)

    def tearDown(self):
        self.engine.dispose()
        with self.admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    @classmethod
    def tearDownClass(cls):
        cls.admin_engine.dispose()

    def run_migrations(self, revision, *, downgrade=False):
        previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.database_url
        try:
            config = Config(str(ROOT_DIR / "alembic.ini"))
            migration_command = command.downgrade if downgrade else command.upgrade
            migration_command(config, revision)
        finally:
            if previous_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_database_url

    @staticmethod
    def insert_legacy_rows(connection, catalog_id, analysis_id, key=None):
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

    def assert_integrity_error(self, statement, parameters):
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as connection:
                connection.execute(text(statement), parameters)

    def test_0006_migration_uses_actual_chain_and_downgrades_safely(self):
        catalog_id, second_catalog_id = uuid4(), uuid4()
        analysis_id, second_analysis_id = uuid4(), uuid4()
        user_id, idempotency_id = uuid4(), uuid4()

        self.run_migrations("0005_async_upload_idempotency")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one(),
                "0005_async_upload_idempotency",
            )
        with self.engine.begin() as connection:
            self.insert_legacy_rows(
                connection, catalog_id, analysis_id, "legacy-global-key"
            )
            self.insert_legacy_rows(connection, second_catalog_id, second_analysis_id)

        self.run_migrations("0006_user_ownership_idempotency")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one(),
                "0006_user_ownership_idempotency",
            )

        inspector = inspect(self.engine)
        self.assertIn("users", inspector.get_table_names())
        self.assertIn("idempotency_records", inspector.get_table_names())
        self.assertIn(
            "owner_id",
            {column["name"] for column in inspector.get_columns("catalogs")},
        )
        self.assertNotIn(
            "uq_analysis_runs_idempotency_key",
            {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("analysis_runs")
            },
        )
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

        with self.engine.begin() as connection:
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
                    "UPDATE analysis_runs SET idempotency_key = :key WHERE id = :id"
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

        self.assert_integrity_error(
            "INSERT INTO users (id, issuer, subject) "
            "VALUES (:id, :issuer, :subject)",
            {
                "id": uuid4(),
                "issuer": "https://issuer.example/",
                "subject": "auth0|migration-test",
            },
        )
        self.assert_integrity_error(
            "UPDATE catalogs SET owner_id = :owner WHERE id = :id",
            {"owner": uuid4(), "id": second_catalog_id},
        )
        invalid_record = (
            "INSERT INTO idempotency_records "
            "(id, owner_id, key, request_fingerprint, analysis_id) "
            "VALUES (:id, :owner, :key, :fingerprint, :analysis)"
        )
        self.assert_integrity_error(
            invalid_record,
            {
                "id": uuid4(),
                "owner": user_id,
                "key": "user-key",
                "fingerprint": "e" * 64,
                "analysis": second_analysis_id,
            },
        )
        self.assert_integrity_error(
            invalid_record,
            {
                "id": uuid4(),
                "owner": user_id,
                "key": "different-key",
                "fingerprint": "e" * 64,
                "analysis": analysis_id,
            },
        )
        self.assert_integrity_error(
            invalid_record,
            {
                "id": uuid4(),
                "owner": uuid4(),
                "key": "unknown-owner",
                "fingerprint": "e" * 64,
                "analysis": second_analysis_id,
            },
        )
        self.assert_integrity_error(
            invalid_record,
            {
                "id": uuid4(),
                "owner": user_id,
                "key": "unknown-analysis",
                "fingerprint": "e" * 64,
                "analysis": uuid4(),
            },
        )

        with self.assertRaisesRegex(RuntimeError, "ownership or idempotency data"):
            self.run_migrations("0005_async_upload_idempotency", downgrade=True)

        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM idempotency_records WHERE id = :id"),
                {"id": idempotency_id},
            )
            connection.execute(
                text("UPDATE catalogs SET owner_id = NULL WHERE id = :id"),
                {"id": catalog_id},
            )
            connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

        self.run_migrations("0005_async_upload_idempotency", downgrade=True)
        inspector = inspect(self.engine)
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
        self.assert_integrity_error(
            "UPDATE analysis_runs SET idempotency_key = :key WHERE id = :id",
            {"key": "legacy-global-key", "id": second_analysis_id},
        )
        with self.engine.begin() as connection:
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

    def test_0007_email_column_is_nullable_and_downgrade_discards_email(self):
        catalog_id, analysis_id = uuid4(), uuid4()
        user_id = uuid4()
        self.run_migrations("0005_async_upload_idempotency")
        self.run_migrations("0006_user_ownership_idempotency")
        with self.engine.begin() as connection:
            self.insert_legacy_rows(connection, catalog_id, analysis_id)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, issuer, subject) "
                    "VALUES (:id, :issuer, :subject)"
                ),
                {
                    "id": user_id,
                    "issuer": "https://issuer.example/",
                    "subject": "auth0|existing-user",
                },
            )

        self.run_migrations("head")
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one(),
                "0007_user_profile_email",
            )
            user_email_column = next(
                column
                for column in inspect(self.engine).get_columns("users")
                if column["name"] == "email"
            )
            self.assertTrue(user_email_column["nullable"])
            self.assertIsNone(
                connection.execute(
                    text("SELECT email FROM users WHERE id = :id"),
                    {"id": user_id},
                ).scalar_one()
            )
            self.assertIsNone(
                connection.execute(
                    text("SELECT owner_id FROM catalogs WHERE id = :id"),
                    {"id": catalog_id},
                ).scalar_one()
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT catalog_id FROM analysis_runs WHERE id = :id"),
                    {"id": analysis_id},
                ).scalar_one(),
                catalog_id,
            )

        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET email = :email WHERE id = :id"),
                {"email": "verified@example.com", "id": user_id},
            )

        self.run_migrations("0006_user_ownership_idempotency", downgrade=True)
        with self.engine.connect() as connection:
            self.assertNotIn(
                "email",
                {column["name"] for column in inspect(self.engine).get_columns("users")},
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE id = :id"),
                    {"id": user_id},
                ).scalar_one(),
                1,
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT COUNT(*) FROM catalogs WHERE id = :id"),
                    {"id": catalog_id},
                ).scalar_one(),
                1,
            )


if __name__ == "__main__":
    unittest.main()
