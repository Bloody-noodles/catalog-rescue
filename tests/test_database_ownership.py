import unittest
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.base import Base
from database.models import AnalysisRun, Catalog, IdempotencyRecord, User
from database.ownership import persist_idempotency_record


class IdempotencyOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_owner_mismatch_rolls_back_catalog_analysis_and_idempotency_record(self):
        user_id, catalog_owner_id = uuid4(), uuid4()
        with self.assertRaisesRegex(ValueError, "must own the associated catalog"):
            with self.factory.begin() as session:
                owner = User(
                    id=user_id,
                    issuer="https://issuer.example/",
                    subject="user",
                )
                catalog_owner = User(
                    id=catalog_owner_id,
                    issuer="https://issuer.example/",
                    subject="other-user",
                )
                catalog = Catalog(
                    owner_id=catalog_owner_id,
                    original_filename="catalog.csv",
                    file_format="csv",
                    row_count=0,
                    column_count=0,
                    column_names=[],
                )
                session.add_all([owner, catalog_owner, catalog])
                session.flush()
                analysis = AnalysisRun(
                    catalog_id=catalog.id,
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
                    key="key",
                    request_fingerprint="a" * 64,
                )

        with self.factory() as session:
            self.assertEqual(session.scalar(select(User.id).limit(1)), None)
            self.assertEqual(session.scalar(select(Catalog.id).limit(1)), None)
            self.assertEqual(session.scalar(select(AnalysisRun.id).limit(1)), None)
            self.assertEqual(session.scalar(select(IdempotencyRecord.id).limit(1)), None)

    def test_analysis_must_belong_to_the_supplied_catalog(self):
        with self.assertRaisesRegex(ValueError, "must belong to the associated catalog"):
            with self.factory.begin() as session:
                owner = User(issuer="https://issuer.example/", subject="user")
                session.add(owner)
                session.flush()
                catalogs = [
                    Catalog(
                        owner_id=owner.id,
                        original_filename=f"catalog-{index}.csv",
                        file_format="csv",
                        row_count=0,
                        column_count=0,
                        column_names=[],
                    )
                    for index in range(2)
                ]
                session.add_all(catalogs)
                session.flush()
                analysis = AnalysisRun(
                    catalog_id=catalogs[1].id,
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
                    catalog=catalogs[0],
                    analysis=analysis,
                    key="key",
                    request_fingerprint="b" * 64,
                )


if __name__ == "__main__":
    unittest.main()
