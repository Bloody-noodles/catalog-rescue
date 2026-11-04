"""Add user ownership and owner-scoped idempotency records.

Revision ID: 0006_user_ownership_idempotency
Revises: 0005_async_upload_idempotency
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_user_ownership_idempotency"
down_revision: Union[str, None] = "0005_async_upload_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("issuer <> ''", name="ck_users_issuer_nonempty"),
        sa.CheckConstraint("subject <> ''", name="ck_users_subject_nonempty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
    )
    op.add_column(
        "catalogs",
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_catalogs_owner_id_users",
        "catalogs",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_catalogs_owner_id", "catalogs", ["owner_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("analysis_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("key <> ''", name="ck_idempotency_records_key_nonempty"),
        sa.CheckConstraint(
            "request_fingerprint <> ''",
            name="ck_idempotency_records_fingerprint_nonempty",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_idempotency_records_fingerprint_length",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analysis_runs.id"],
            name="fk_idempotency_records_analysis_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_idempotency_records_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            name="uq_idempotency_records_analysis_id",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "key",
            name="uq_idempotency_records_owner_key",
        ),
    )

    op.drop_constraint(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        type_="unique",
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_owned_catalogs = bind.execute(
        sa.text("SELECT 1 FROM catalogs WHERE owner_id IS NOT NULL LIMIT 1")
    ).first()
    has_users = bind.execute(sa.text("SELECT 1 FROM users LIMIT 1")).first()
    has_idempotency_records = bind.execute(
        sa.text("SELECT 1 FROM idempotency_records LIMIT 1")
    ).first()
    if has_owned_catalogs or has_users or has_idempotency_records:
        raise RuntimeError(
            "Cannot downgrade while user ownership or idempotency data exists."
        )

    has_duplicate_legacy_keys = bind.execute(
        sa.text(
            "SELECT idempotency_key FROM analysis_runs "
            "WHERE idempotency_key IS NOT NULL "
            "GROUP BY idempotency_key HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if has_duplicate_legacy_keys:
        raise RuntimeError(
            "Cannot restore the legacy idempotency constraint while duplicate keys exist."
        )

    op.create_unique_constraint(
        "uq_analysis_runs_idempotency_key",
        "analysis_runs",
        ["idempotency_key"],
    )
    op.drop_table("idempotency_records")
    op.drop_index("ix_catalogs_owner_id", table_name="catalogs")
    op.drop_constraint(
        "fk_catalogs_owner_id_users",
        "catalogs",
        type_="foreignkey",
    )
    op.drop_column("catalogs", "owner_id")
    op.drop_table("users")
