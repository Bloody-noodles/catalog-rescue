"""Constrain retryability to failed jobs eligible for another attempt.

Revision ID: 0004_retryability_invariant
Revises: 0003_analysis_run_job_lifecycle
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from database.job_constants import MAX_ATTEMPTS


revision: str = "0004_retryability_invariant"
down_revision: Union[str, None] = "0003_analysis_run_job_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        f"attempt_count >= 0 AND attempt_count <= {MAX_ATTEMPTS}",
    )
    op.create_check_constraint(
        "ck_analysis_runs_retryability",
        "analysis_runs",
        "retryable = false OR "
        f"(status = 'failed' AND attempt_count < {MAX_ATTEMPTS})",
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
        sa.column("retryable", sa.Boolean()),
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
                analysis_runs.c.retryable.is_(True),
            )
        )
        .limit(1)
    ).first()
    if has_lifecycle_data:
        raise RuntimeError(
            "Cannot downgrade while analysis_runs contains lifecycle data."
        )
    op.drop_constraint(
        "ck_analysis_runs_retryability",
        "analysis_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analysis_runs_attempt_count_range",
        "analysis_runs",
        "attempt_count >= 0 AND attempt_count <= 3",
    )
