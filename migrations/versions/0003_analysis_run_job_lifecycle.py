"""Add bounded analysis-job lifecycle and lease fields.

Revision ID: 0003_analysis_run_job_lifecycle
Revises: 0002_add_persistent_catalog_data
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_analysis_run_job_lifecycle"
down_revision: Union[str, None] = "0002_add_persistent_catalog_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_status", "analysis_runs", type_="check")
    op.alter_column(
        "analysis_runs",
        "status",
        existing_type=sa.String(length=20),
        server_default="queued",
    )
    op.alter_column(
        "analysis_runs",
        "completed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )
    op.add_column(
        "analysis_runs",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("lease_token", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "ck_analysis_runs_status",
        "analysis_runs",
        "status IN ('queued', 'processing', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        "attempt_count >= 0 AND attempt_count <= 3",
    )
    op.create_check_constraint(
        "ck_analysis_runs_lease_state",
        "analysis_runs",
        "(status = 'processing' AND lease_expires_at IS NOT NULL "
        "AND lease_token IS NOT NULL AND started_at IS NOT NULL) OR "
        "(status <> 'processing' AND lease_expires_at IS NULL "
        "AND lease_token IS NULL)",
    )
    op.create_index(
        "ix_analysis_runs_status_lease_expires_at",
        "analysis_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    analysis_runs = sa.table(
        "analysis_runs",
        sa.column("status", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("error_message", sa.Text()),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.column("lease_token", sa.Uuid(as_uuid=True)),
    )
    has_lifecycle_data = op.get_bind().execute(
        sa.select(sa.literal(True))
        .select_from(analysis_runs)
        .where(
            sa.or_(
                analysis_runs.c.status != "completed",
                analysis_runs.c.attempt_count != 0,
                analysis_runs.c.started_at.is_not(None),
                analysis_runs.c.error_message.is_not(None),
                analysis_runs.c.lease_expires_at.is_not(None),
                analysis_runs.c.lease_token.is_not(None),
            )
        )
        .limit(1)
    ).first()
    if has_lifecycle_data:
        raise RuntimeError(
            "Cannot downgrade while analysis_runs contains lifecycle data."
        )

    op.drop_index(
        "ix_analysis_runs_status_lease_expires_at",
        table_name="analysis_runs",
    )
    op.drop_constraint(
        "ck_analysis_runs_lease_state",
        "analysis_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_runs_status",
        "analysis_runs",
        type_="check",
    )
    op.drop_column("analysis_runs", "retryable")
    op.drop_column("analysis_runs", "lease_token")
    op.drop_column("analysis_runs", "lease_expires_at")
    op.drop_column("analysis_runs", "error_message")
    op.drop_column("analysis_runs", "updated_at")
    op.drop_column("analysis_runs", "started_at")
    op.drop_column("analysis_runs", "attempt_count")
    op.alter_column(
        "analysis_runs",
        "completed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    op.alter_column(
        "analysis_runs",
        "status",
        existing_type=sa.String(length=20),
        server_default="completed",
    )
    op.create_check_constraint(
        "ck_analysis_runs_status",
        "analysis_runs",
        "status = 'completed'",
    )
