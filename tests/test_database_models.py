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
    String,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import configure_mappers

from database.base import Base
from database.config import create_database_engine, get_database_url
from database.models import AnalysisRun, Catalog
from database.session import (
    create_session_factory,
    dispose_database_engine,
    get_database_engine,
    get_db_session,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


class DatabaseModelTests(unittest.TestCase):
    def test_tables_columns_types_relationship_and_constraints(self):
        configure_mappers()
        self.assertEqual(set(Base.metadata.tables), {"catalogs", "analysis_runs"})

        catalogs = Catalog.__table__
        runs = AnalysisRun.__table__
        self.assertIsInstance(catalogs.c.id.type, Uuid)
        self.assertTrue(catalogs.c.id.primary_key)
        self.assertIsInstance(catalogs.c.original_filename.type, String)
        self.assertIsInstance(catalogs.c.file_format.type, String)
        self.assertIsInstance(catalogs.c.row_count.type, Integer)
        self.assertIsInstance(catalogs.c.column_count.type, Integer)
        self.assertIsInstance(catalogs.c.column_names.type, JSON)
        self.assertIsInstance(catalogs.c.created_at.type, DateTime)
        self.assertTrue(catalogs.c.created_at.type.timezone)
        self.assertIsNotNone(catalogs.c.created_at.server_default)

        self.assertIsInstance(runs.c.id.type, Uuid)
        self.assertTrue(runs.c.id.primary_key)
        self.assertIsInstance(runs.c.catalog_id.type, Uuid)
        self.assertIsInstance(runs.c.status.type, String)
        self.assertIsInstance(runs.c.completed_at.type, DateTime)
        self.assertTrue(runs.c.completed_at.type.timezone)
        self.assertIsNotNone(runs.c.completed_at.server_default)
        self.assertIsInstance(runs.c.health_score.type, Integer)
        self.assertIsInstance(runs.c.issue_count.type, Integer)
        self.assertIsInstance(runs.c.cleaned_record_count.type, Integer)
        self.assertIsInstance(runs.c.affected_record_count.type, Integer)
        self.assertIsInstance(runs.c.quality_metrics.type, JSON)
        self.assertIsInstance(runs.c.analysis_summary.type, JSON)

        foreign_keys = list(runs.c.catalog_id.foreign_keys)
        self.assertEqual(len(foreign_keys), 1)
        self.assertIsInstance(foreign_keys[0], ForeignKey)
        self.assertEqual(foreign_keys[0].target_fullname, "catalogs.id")
        self.assertEqual(foreign_keys[0].ondelete, "CASCADE")
        self.assertEqual(Catalog.analysis_runs.property.back_populates, "catalog")
        self.assertEqual(AnalysisRun.catalog.property.back_populates, "analysis_runs")

        self.assertEqual(
            {index.name for index in catalogs.indexes},
            {"ix_catalogs_created_at"},
        )
        self.assertEqual(
            {index.name for index in runs.indexes},
            {"ix_analysis_runs_catalog_id", "ix_analysis_runs_completed_at"},
        )
        catalog_checks = {
            constraint.name
            for constraint in catalogs.constraints
            if isinstance(constraint, CheckConstraint)
        }
        run_checks = {
            constraint.name
            for constraint in runs.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertEqual(
            catalog_checks,
            {
                "ck_catalogs_original_filename_nonempty",
                "ck_catalogs_row_count_nonnegative",
                "ck_catalogs_column_count_nonnegative",
                "ck_catalogs_file_format",
            },
        )
        self.assertEqual(
            run_checks,
            {
                "ck_analysis_runs_health_score_range",
                "ck_analysis_runs_issue_count_nonnegative",
                "ck_analysis_runs_cleaned_record_count_nonnegative",
                "ck_analysis_runs_affected_record_count_nonnegative",
                "ck_analysis_runs_status",
            },
        )

    def test_primary_keys_have_uuid_python_defaults(self):
        catalog_default = Catalog.__table__.c.id.default
        analysis_default = AnalysisRun.__table__.c.id.default
        self.assertTrue(catalog_default.is_callable)
        self.assertTrue(analysis_default.is_callable)

    def test_filename_is_reduced_to_basename(self):
        catalog = Catalog(
            original_filename=r"C:\uploads\vendor\catalog.csv",
            file_format="csv",
            row_count=0,
            column_count=0,
            column_names=[],
        )
        self.assertEqual(catalog.original_filename, "catalog.csv")

    def test_filename_validation_rejects_empty_and_overlong_values(self):
        catalog_values = {
            "file_format": "csv",
            "row_count": 0,
            "column_count": 0,
            "column_names": [],
        }
        for filename in ("", r"C:\uploads\\", "x" * 256):
            with self.subTest(filename_length=len(filename)):
                with self.assertRaises(ValueError):
                    Catalog(original_filename=filename, **catalog_values)

    def test_status_constraint_only_allows_completed(self):
        status_constraint = next(
            constraint
            for constraint in AnalysisRun.__table__.constraints
            if constraint.name == "ck_analysis_runs_status"
        )
        self.assertEqual(str(status_constraint.sqltext), "status = 'completed'")

    def test_postgresql_url_is_normalized_and_query_parameters_preserved(self):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": (
                    "postgresql://catalog_user:secret@db.example/catalog"
                    "?sslmode=require&application_name=catalog-rescue"
                )
            },
            clear=True,
        ):
            url = get_database_url()

        self.assertTrue(url.startswith("postgresql+psycopg://"))
        self.assertIn("sslmode=require", url)
        self.assertIn("application_name=catalog-rescue", url)

    def test_existing_psycopg_url_is_preserved(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql+psycopg://user:secret@db.example/catalog"},
            clear=True,
        ):
            url = get_database_url()
        self.assertTrue(url.startswith("postgresql+psycopg://"))

    def test_missing_database_url_has_actionable_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is not set"):
                get_database_url()
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is not set"):
                create_database_engine()

    def test_invalid_database_url_error_does_not_expose_credentials(self):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgresql://private-user:private-password@host:bad:port/db"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as context:
                get_database_url()
        self.assertNotIn("private-user", str(context.exception))
        self.assertNotIn("private-password", str(context.exception))

    def test_session_factory_reuses_lazy_engine_and_accepts_injection(self):
        injected_engine = create_engine("sqlite://")
        injected_factory = create_session_factory(injected_engine)
        self.assertIs(injected_factory.kw["bind"], injected_engine)
        injected_session_generator = get_db_session(injected_factory)
        injected_session = next(injected_session_generator)
        self.assertIs(injected_session.get_bind(), injected_engine)
        injected_session_generator.close()

        shared_engine = create_engine("sqlite://")
        with patch(
            "database.session.create_database_engine",
            return_value=shared_engine,
        ) as create_engine_mock:
            first_factory = create_session_factory()
            second_factory = create_session_factory()
            self.assertIs(first_factory, second_factory)
            self.assertIs(get_database_engine(), shared_engine)
            create_engine_mock.assert_called_once_with()
        dispose_database_engine()
        dispose_database_engine(injected_engine)

    def test_database_package_import_does_not_create_engine_or_connect(self):
        script = """
import sqlalchemy

def forbidden(*args, **kwargs):
    raise AssertionError("Database engine was created during import")

sqlalchemy.create_engine = forbidden
import database
import database.base
import database.config
import database.models
import database.session
"""
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT_DIR,
            env={**os.environ, "DATABASE_URL": ""},
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
