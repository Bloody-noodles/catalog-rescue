import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from database.base import Base


class Catalog(Base):
    __tablename__ = "catalogs"
    __table_args__ = (
        CheckConstraint(
            "original_filename <> ''",
            name="ck_catalogs_original_filename_nonempty",
        ),
        CheckConstraint("row_count >= 0", name="ck_catalogs_row_count_nonnegative"),
        CheckConstraint(
            "column_count >= 0",
            name="ck_catalogs_column_count_nonnegative",
        ),
        CheckConstraint(
            "file_format IN ('csv', 'xlsx', 'xls')",
            name="ck_catalogs_file_format",
        ),
        Index("ix_catalogs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="catalog",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("original_filename")
    def store_filename_basename(self, _key, value):
        if not isinstance(value, str):
            raise ValueError("original_filename must be a non-empty string.")
        basename = value.replace("\\", "/").rsplit("/", 1)[-1]
        if not basename:
            raise ValueError("original_filename must include a filename.")
        if len(basename) > 255:
            raise ValueError("original_filename must be 255 characters or fewer.")
        return basename


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "health_score >= 0 AND health_score <= 100",
            name="ck_analysis_runs_health_score_range",
        ),
        CheckConstraint(
            "status = 'completed'",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint(
            "issue_count >= 0",
            name="ck_analysis_runs_issue_count_nonnegative",
        ),
        CheckConstraint(
            "cleaned_record_count >= 0",
            name="ck_analysis_runs_cleaned_record_count_nonnegative",
        ),
        CheckConstraint(
            "affected_record_count >= 0",
            name="ck_analysis_runs_affected_record_count_nonnegative",
        ),
        Index("ix_analysis_runs_catalog_id", "catalog_id"),
        Index("ix_analysis_runs_completed_at", "completed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    catalog_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "catalogs.id",
            name="fk_analysis_runs_catalog_id_catalogs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="completed",
        server_default="completed",
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    health_score: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaned_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    affected_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    analysis_summary: Mapped[dict] = mapped_column(JSON, nullable=False)

    catalog: Mapped[Catalog] = relationship(back_populates="analysis_runs")
