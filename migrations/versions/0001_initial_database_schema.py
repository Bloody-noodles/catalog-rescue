"""Create the initial catalog and analysis-run schema.

Revision ID: 0001_initial_database_schema
Revises:
Create Date: 2026-11-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_database_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalogs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_format", sa.String(length=10), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("column_names", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "column_count >= 0",
            name="ck_catalogs_column_count_nonnegative",
        ),
        sa.CheckConstraint(
            "original_filename <> ''",
            name="ck_catalogs_original_filename_nonempty",
        ),
        sa.CheckConstraint(
            "file_format IN ('csv', 'xlsx', 'xls')",
            name="ck_catalogs_file_format",
        ),
        sa.CheckConstraint(
            "row_count >= 0",
            name="ck_catalogs_row_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalogs_created_at",
        "catalogs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("catalog_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="completed",
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("health_score", sa.Integer(), nullable=False),
        sa.Column("issue_count", sa.Integer(), nullable=False),
        sa.Column("cleaned_record_count", sa.Integer(), nullable=False),
        sa.Column("affected_record_count", sa.Integer(), nullable=False),
        sa.Column("quality_metrics", sa.JSON(), nullable=False),
        sa.Column("analysis_summary", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "affected_record_count >= 0",
            name="ck_analysis_runs_affected_record_count_nonnegative",
        ),
        sa.CheckConstraint(
            "cleaned_record_count >= 0",
            name="ck_analysis_runs_cleaned_record_count_nonnegative",
        ),
        sa.CheckConstraint(
            "health_score >= 0 AND health_score <= 100",
            name="ck_analysis_runs_health_score_range",
        ),
        sa.CheckConstraint(
            "issue_count >= 0",
            name="ck_analysis_runs_issue_count_nonnegative",
        ),
        sa.CheckConstraint(
            "status = 'completed'",
            name="ck_analysis_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_id"],
            ["catalogs.id"],
            name="fk_analysis_runs_catalog_id_catalogs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_runs_catalog_id",
        "analysis_runs",
        ["catalog_id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_runs_completed_at",
        "analysis_runs",
        ["completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_completed_at", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_catalog_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_index("ix_catalogs_created_at", table_name="catalogs")
    op.drop_table("catalogs")
