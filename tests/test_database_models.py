import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    create_engine,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers

from database.base import Base
from database.config import create_database_engine, get_database_url
from database.job_constants import MAX_ATTEMPTS
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User
from database.session import create_session_factory, dispose_database_engine, get_database_engine, get_db_session

ROOT_DIR = Path(__file__).resolve().parents[1]


class DatabaseModelTests(unittest.TestCase):
    def test_tables_columns_types_relationship_and_constraints(self):
        configure_mappers()
        self.assertEqual(
            set(Base.metadata.tables),
            {"users", "catalogs", "analysis_runs", "idempotency_records"},
        )
        users = User.__table__
        catalogs, runs = Catalog.__table__, AnalysisRun.__table__
        idempotency_records = IdempotencyRecord.__table__
        self.assertIsInstance(users.c.id.type, Uuid)
        self.assertIsInstance(users.c.issuer.type, String)
        self.assertIsInstance(users.c.subject.type, String)
        self.assertIsInstance(users.c.created_at.type, DateTime)
        self.assertTrue(users.c.created_at.type.timezone)
        self.assertEqual(
            {constraint.name for constraint in users.constraints if isinstance(constraint, UniqueConstraint)},
            {"uq_users_issuer_subject"},
        )
        self.assertIsInstance(catalogs.c.owner_id.type, Uuid)
        self.assertTrue(catalogs.c.owner_id.nullable)
        owner_fk = list(catalogs.c.owner_id.foreign_keys)
        self.assertEqual(len(owner_fk), 1)
        self.assertEqual(owner_fk[0].target_fullname, "users.id")
        self.assertEqual(owner_fk[0].ondelete, "RESTRICT")
        self.assertEqual(Catalog.owner.property.back_populates, "catalogs")
        self.assertEqual(User.catalogs.property.back_populates, "owner")
        self.assertEqual(User.idempotency_records.property.back_populates, "owner")
        self.assertEqual(AnalysisRun.idempotency_record.property.back_populates, "analysis")
        self.assertEqual(IdempotencyRecord.analysis.property.back_populates, "idempotency_record")
        self.assertEqual(IdempotencyRecord.owner.property.back_populates, "idempotency_records")
        self.assertIsInstance(idempotency_records.c.id.type, Uuid)
        self.assertIsInstance(idempotency_records.c.owner_id.type, Uuid)
        self.assertIsInstance(idempotency_records.c.key.type, String)
        self.assertIsInstance(idempotency_records.c.request_fingerprint.type, String)
        self.assertIsInstance(idempotency_records.c.analysis_id.type, Uuid)
        self.assertTrue(idempotency_records.c.created_at.type.timezone)
        self.assertTrue(idempotency_records.c.updated_at.type.timezone)
        idempotency_uniques = {
            (constraint.name, tuple(column.name for column in constraint.columns))
            for constraint in idempotency_records.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertEqual(
            idempotency_uniques,
            {
                ("uq_idempotency_records_owner_key", ("owner_id", "key")),
                ("uq_idempotency_records_analysis_id", ("analysis_id",)),
            },
        )
        idempotency_fks = {
            foreign_key.target_fullname
            for foreign_key in idempotency_records.foreign_keys
        }
        self.assertEqual(idempotency_fks, {"users.id", "analysis_runs.id"})
        self.assertIsInstance(catalogs.c.id.type, Uuid)
        self.assertTrue(catalogs.c.id.primary_key)
        self.assertIsInstance(catalogs.c.original_filename.type, String)
        self.assertIsInstance(catalogs.c.file_format.type, String)
        self.assertIsInstance(catalogs.c.row_count.type, Integer)
        self.assertIsInstance(catalogs.c.column_count.type, Integer)
        self.assertIsInstance(catalogs.c.column_names.type, JSON)
        self.assertIsInstance(catalogs.c.original_file.type, LargeBinary)
        self.assertIsInstance(catalogs.c.original_rows.type, JSON)
        self.assertIsInstance(catalogs.c.created_at.type, DateTime)
        self.assertTrue(catalogs.c.created_at.type.timezone)
        self.assertIsInstance(runs.c.id.type, Uuid)
        self.assertIsInstance(runs.c.catalog_id.type, Uuid)
        self.assertIsInstance(runs.c.quality_metrics.type, JSON)
        self.assertIsInstance(runs.c.analysis_summary.type, JSON)
        self.assertIsInstance(runs.c.cleaned_rows.type, JSON)
        self.assertIsInstance(runs.c.analysis_report.type, JSON)
        fk = list(runs.c.catalog_id.foreign_keys)
        self.assertEqual(len(fk), 1)
        self.assertIsInstance(fk[0], ForeignKey)
        self.assertEqual(fk[0].target_fullname, "catalogs.id")
        self.assertEqual(fk[0].ondelete, "CASCADE")
        self.assertEqual(Catalog.analysis_runs.property.back_populates, "catalog")
        self.assertEqual(AnalysisRun.catalog.property.back_populates, "analysis_runs")
        self.assertEqual(
            {i.name for i in catalogs.indexes},
            {"ix_catalogs_created_at", "ix_catalogs_owner_id"},
        )
        self.assertEqual(
            {i.name for i in runs.indexes},
            {
                "ix_analysis_runs_catalog_id",
                "ix_analysis_runs_completed_at",
                "ix_analysis_runs_status_lease_expires_at",
            },
        )
        self.assertNotIn(
            "uq_analysis_runs_idempotency_key",
            {
                constraint.name
                for constraint in runs.constraints
                if isinstance(constraint, UniqueConstraint)
            },
        )
        catalog_checks = {c.name for c in catalogs.constraints if isinstance(c, CheckConstraint)}
        run_checks = {c.name for c in runs.constraints if isinstance(c, CheckConstraint)}
        self.assertEqual(catalog_checks, {
            "ck_catalogs_original_filename_nonempty", "ck_catalogs_row_count_nonnegative",
            "ck_catalogs_column_count_nonnegative", "ck_catalogs_file_format",
        })
        self.assertEqual(run_checks, {
            "ck_analysis_runs_health_score_range", "ck_analysis_runs_issue_count_nonnegative",
            "ck_analysis_runs_cleaned_record_count_nonnegative", "ck_analysis_runs_affected_record_count_nonnegative",
            "ck_analysis_runs_status", "ck_analysis_runs_attempt_count_range",
            "ck_analysis_runs_lease_state", "ck_analysis_runs_retryability",
        })
        attempt_constraint = next(
            constraint
            for constraint in runs.constraints
            if constraint.name == "ck_analysis_runs_attempt_count_range"
        )
        self.assertEqual(
            str(attempt_constraint.sqltext),
            f"attempt_count >= 0 AND attempt_count <= {MAX_ATTEMPTS}",
        )

    def test_primary_keys_have_uuid_defaults(self):
        self.assertTrue(Catalog.__table__.c.id.default.is_callable)
        self.assertTrue(AnalysisRun.__table__.c.id.default.is_callable)

    def test_filename_is_reduced_to_basename(self):
        catalog = Catalog(original_filename=r"C:\uploads\vendor\catalog.csv", file_format="csv", row_count=0, column_count=0, column_names=[])
        self.assertEqual(catalog.original_filename, "catalog.csv")

    def test_filename_validation(self):
        values = {"file_format": "csv", "row_count": 0, "column_count": 0, "column_names": []}
        for name in ("", r"C:\uploads\\", "x" * 256):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Catalog(original_filename=name, **values)

    def test_status_constraint_allows_only_lifecycle_states(self):
        constraint = next(c for c in AnalysisRun.__table__.constraints if c.name == "ck_analysis_runs_status")
        self.assertEqual(
            str(constraint.sqltext),
            "status IN ('queued', 'processing', 'completed', 'failed')",
        )

    def test_analysis_run_defaults_to_queued_with_zero_attempts(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        with factory() as session:
            catalog = Catalog(
                original_filename="default.csv",
                file_format="csv",
                row_count=0,
                column_count=0,
                column_names=[],
            )
            run = AnalysisRun(
                catalog=catalog,
                health_score=0,
                issue_count=0,
                cleaned_record_count=0,
                affected_record_count=0,
                quality_metrics={},
                analysis_summary={},
            )
            session.add(run)
            session.flush()
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.attempt_count, 0)
            self.assertIsNotNone(run.updated_at)
            self.assertIsNone(run.completed_at)
        engine.dispose()

    def test_ownerless_catalogs_and_owner_scoped_idempotency_relationships(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        with factory.begin() as session:
            owner = User(issuer="https://issuer.example/", subject="auth0|user-1")
            other_owner = User(issuer="https://issuer.example/", subject="auth0|user-2")
            legacy_catalog = Catalog(
                original_filename="legacy.csv",
                file_format="csv",
                row_count=0,
                column_count=0,
                column_names=[],
            )
            owned_catalog = Catalog(
                original_filename="owned.csv",
                file_format="csv",
                row_count=0,
                column_count=0,
                column_names=[],
                owner=owner,
            )
            session.add_all([owner, other_owner, legacy_catalog, owned_catalog])
            session.flush()
            run = AnalysisRun(
                catalog=owned_catalog,
                status="queued",
                health_score=0,
                issue_count=0,
                cleaned_record_count=0,
                affected_record_count=0,
                quality_metrics={},
                analysis_summary={},
            )
            session.add(run)
            session.flush()
            record = IdempotencyRecord(
                owner=owner,
                analysis=run,
                key="request-1",
                request_fingerprint="a" * 64,
            )
            other_owner_record = IdempotencyRecord(
                owner=other_owner,
                analysis=AnalysisRun(
                    catalog=Catalog(
                        original_filename="other.csv",
                        file_format="csv",
                        row_count=0,
                        column_count=0,
                        column_names=[],
                        owner=other_owner,
                    ),
                    status="queued",
                    health_score=0,
                    issue_count=0,
                    cleaned_record_count=0,
                    affected_record_count=0,
                    quality_metrics={},
                    analysis_summary={},
                ),
                key="request-1",
                request_fingerprint="b" * 64,
            )
            session.add_all([record, other_owner_record])
            session.flush()
            self.assertIsNone(legacy_catalog.owner_id)
            self.assertIs(owned_catalog.owner, owner)
            self.assertIs(run.catalog.owner, owner)
            self.assertIs(record.analysis, run)
            self.assertIs(record.owner, owner)
            self.assertIs(run.idempotency_record, record)
        engine.dispose()

    def test_idempotency_keys_are_unique_per_owner(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        factory = create_session_factory(engine)
        with factory.begin() as session:
            owner_one = User(issuer="https://issuer.example/", subject="auth0|one")
            owner_two = User(issuer="https://issuer.example/", subject="auth0|two")
            session.add_all([owner_one, owner_two])
            session.flush()
            analysis_ids = []
            for owner, suffix in ((owner_one, "one"), (owner_two, "two")):
                catalog = Catalog(
                    original_filename=f"{suffix}.csv",
                    file_format="csv",
                    row_count=0,
                    column_count=0,
                    column_names=[],
                    owner=owner,
                )
                analysis = AnalysisRun(
                    catalog=catalog,
                    status="queued",
                    health_score=0,
                    issue_count=0,
                    cleaned_record_count=0,
                    affected_record_count=0,
                    quality_metrics={},
                    analysis_summary={},
                )
                session.add(analysis)
                session.flush()
                analysis_ids.append(analysis.id)
                session.add(
                    IdempotencyRecord(
                        owner=owner,
                        analysis=analysis,
                        key="same-key",
                        request_fingerprint=suffix[0] * 64,
                    )
                )
            session.flush()
            owner_one_id = owner_one.id

        with self.assertRaises(IntegrityError):
            with factory.begin() as session:
                owner = session.get(User, owner_one_id)
                catalog = Catalog(
                    original_filename="duplicate.csv",
                    file_format="csv",
                    row_count=0,
                    column_count=0,
                    column_names=[],
                    owner=owner,
                )
                analysis = AnalysisRun(
                    catalog=catalog,
                    status="queued",
                    health_score=0,
                    issue_count=0,
                    cleaned_record_count=0,
                    affected_record_count=0,
                    quality_metrics={},
                    analysis_summary={},
                )
                session.add(
                    IdempotencyRecord(
                        owner=owner,
                        analysis=analysis,
                        key="same-key",
                        request_fingerprint="e" * 64,
                    )
                )
                session.flush()

        with self.assertRaises(IntegrityError):
            with factory.begin() as session:
                session.add(
                    IdempotencyRecord(
                        owner=session.get(User, owner_one_id),
                        analysis=session.get(AnalysisRun, analysis_ids[0]),
                        key="second-key-for-same-analysis",
                        request_fingerprint="f" * 64,
                    )
                )
                session.flush()
        engine.dispose()

    def test_postgresql_url_is_normalized_and_query_parameters_preserved(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://catalog_user:secret@db.example/catalog?sslmode=require&application_name=catalog-rescue"}, clear=True):
            url = get_database_url()
        self.assertTrue(url.startswith("postgresql+psycopg://"))
        self.assertIn("sslmode=require", url)
        self.assertIn("application_name=catalog-rescue", url)

    def test_existing_psycopg_url_is_preserved(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg://user:secret@db.example/catalog"}, clear=True):
            self.assertTrue(get_database_url().startswith("postgresql+psycopg://"))

    def test_missing_database_url_has_actionable_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is not set"):
                get_database_url()
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is not set"):
                create_database_engine()

    def test_invalid_url_error_does_not_expose_credentials(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://private-user:private-password@host:bad:port/db"}, clear=True):
            with self.assertRaises(RuntimeError) as caught:
                get_database_url()
        self.assertNotIn("private-user", str(caught.exception))
        self.assertNotIn("private-password", str(caught.exception))

    def test_session_factory_reuses_lazy_engine_and_accepts_injection(self):
        injected = create_engine("sqlite://")
        factory = create_session_factory(injected)
        self.assertIs(factory.kw["bind"], injected)
        generator = get_db_session(factory)
        self.assertIs(next(generator).get_bind(), injected)
        generator.close()
        shared = create_engine("sqlite://")
        with patch("database.session.create_database_engine", return_value=shared) as mocked:
            self.assertIs(create_session_factory(), create_session_factory())
            self.assertIs(get_database_engine(), shared)
            mocked.assert_called_once_with()
        dispose_database_engine()
        dispose_database_engine(injected)

    def test_database_import_does_not_create_engine(self):
        script = """
import sqlalchemy
def forbidden(*args, **kwargs):
    raise AssertionError("Engine created during import")
sqlalchemy.create_engine = forbidden
import database
import database.base
import database.config
import database.models
import database.session
import database.job_lifecycle
"""
        subprocess.run([sys.executable, "-c", script], cwd=ROOT_DIR, env={**os.environ, "DATABASE_URL": ""}, check=True)


if __name__ == "__main__":
    unittest.main()
