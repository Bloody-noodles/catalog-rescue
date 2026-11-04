"""Add async upload timestamps and idempotency fields.

Revision ID: 0005_async_upload_idempotency
Revises: 0004_retryability_invariant
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_async_upload_idempotency"
down_revision: Union[str, None] = "0004_retryability_invariant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        ["idempotency_key"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_idempotency_data = bind.execute(
        sa.text(
            "SELECT 1 FROM analysis_runs "
            "WHERE idempotency_key IS NOT NULL OR content_fingerprint IS NOT NULL LIMIT 1"
        )
    ).first()
    if has_idempotency_data:
        raise RuntimeError(
            "Cannot downgrade while analysis_runs contains idempotency data."
        )

    op.drop_constraint(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        type_="unique",
    )
    op.drop_column("analysis_runs", "content_fingerprint")
    op.drop_column("analysis_runs", "idempotency_key")
    op.drop_column("analysis_runs", "created_at")
