"""Add optional verified email profile data to users.

Revision ID: 0007_user_profile_email
Revises: 0006_user_ownership_idempotency
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_user_profile_email"
down_revision: Union[str, None] = "0006_user_ownership_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "email")
