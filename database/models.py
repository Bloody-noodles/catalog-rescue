import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from database.base import Base
from database.job_constants import MAX_ATTEMPTS


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
        CheckConstraint("issuer <> ''", name="ck_users_issuer_nonempty"),
        CheckConstraint("subject <> ''", name="ck_users_subject_nonempty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    catalogs: Mapped[list["Catalog"]] = relationship(back_populates="owner")
    idempotency_records: Mapped[list["IdempotencyRecord"]] = relationship(
        back_populates="owner"
    )


class Catalog(Base):
    __tablename__ = "catalogs"
    __table_args__ = (
        CheckConstraint("original_filename <> ''", name="ck_catalogs_original_filename_nonempty"),
        CheckConstraint("row_count >= 0", name="ck_catalogs_row_count_nonnegative"),
        CheckConstraint("column_count >= 0", name="ck_catalogs_column_count_nonnegative"),
        CheckConstraint("file_format IN ('csv', 'xlsx', 'xls')", name="ck_catalogs_file_format"),
        Index("ix_catalogs_created_at", "created_at"),
        Index("ix_catalogs_owner_id", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_catalogs_owner_id_users", ondelete="RESTRICT"),
        nullable=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    original_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    original_rows: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="catalog", cascade="all, delete-orphan", passive_deletes=True
    )
    owner: Mapped[User | None] = relationship(back_populates="catalogs")

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
        CheckConstraint("health_score >= 0 AND health_score <= 100", name="ck_analysis_runs_health_score_range"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint(
            f"attempt_count >= 0 AND attempt_count <= {MAX_ATTEMPTS}",
            name="ck_analysis_runs_attempt_count_range",
        ),
        CheckConstraint(
            "retryable = false OR "
            f"(status = 'failed' AND attempt_count < {MAX_ATTEMPTS})",
            name="ck_analysis_runs_retryability",
        ),
        CheckConstraint(
            "(status = 'processing' AND lease_expires_at IS NOT NULL "
            "AND lease_token IS NOT NULL AND started_at IS NOT NULL) OR "
            "(status <> 'processing' AND lease_expires_at IS NULL "
            "AND lease_token IS NULL)",
            name="ck_analysis_runs_lease_state",
        ),
        CheckConstraint("issue_count >= 0", name="ck_analysis_runs_issue_count_nonnegative"),
        CheckConstraint("cleaned_record_count >= 0", name="ck_analysis_runs_cleaned_record_count_nonnegative"),
        CheckConstraint("affected_record_count >= 0", name="ck_analysis_runs_affected_record_count_nonnegative"),
        Index("ix_analysis_runs_catalog_id", "catalog_id"),
        Index("ix_analysis_runs_completed_at", "completed_at"),
        Index(
            "ix_analysis_runs_status_lease_expires_at",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("catalogs.id", name="fk_analysis_runs_catalog_id_catalogs", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    health_score: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cleaned_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    affected_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    analysis_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    cleaned_rows: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analysis_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    catalog: Mapped[Catalog] = relationship(back_populates="analysis_runs")
    idempotency_record: Mapped[Optional["IdempotencyRecord"]] = relationship(
        back_populates="analysis",
        uselist=False,
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("owner_id", "key", name="uq_idempotency_records_owner_key"),
        UniqueConstraint("analysis_id", name="uq_idempotency_records_analysis_id"),
        CheckConstraint("key <> ''", name="ck_idempotency_records_key_nonempty"),
        CheckConstraint(
            "request_fingerprint <> ''",
            name="ck_idempotency_records_fingerprint_nonempty",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_idempotency_records_fingerprint_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_idempotency_records_owner_id_users", ondelete="RESTRICT"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "analysis_runs.id",
            name="fk_idempotency_records_analysis_id_analysis_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[User] = relationship(back_populates="idempotency_records")
    analysis: Mapped[AnalysisRun] = relationship(back_populates="idempotency_record")
