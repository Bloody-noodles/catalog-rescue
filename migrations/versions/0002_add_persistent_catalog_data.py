"""Add original catalog and persisted analysis payloads.

Revision ID: 0002_add_persistent_catalog_data
Revises: 0001_initial_database_schema
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_persistent_catalog_data"
down_revision: Union[str, None] = "0001_initial_database_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("catalogs", sa.Column("original_file", sa.LargeBinary(), nullable=True))
    op.add_column("catalogs", sa.Column("original_rows", sa.JSON(), nullable=True))
    op.add_column("analysis_runs", sa.Column("cleaned_rows", sa.JSON(), nullable=True))
    op.add_column("analysis_runs", sa.Column("analysis_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_runs", "analysis_report")
    op.drop_column("analysis_runs", "cleaned_rows")
    op.drop_column("catalogs", "original_rows")
    op.drop_column("catalogs", "original_file")
