"""Add realm_id to auth_process

Adds a tenant/realm column to the authentication history table. Every
stored record is now scoped to the Keycloak realm that produced it, and
the old user_id-only lookup index is replaced with one led by realm_id, so
per-user history reads/writes can be filtered per tenant -- closing a gap
where the risk decision API treated a request's user_id as the only key
for a user's history, with no check that the caller's realm actually
owned that user.

Existing rows have no way to know which realm they belonged to, so the
column is left NULL (nullable) rather than guessed or backfilled to a
placeholder. NULL never matches a realm-scoped `==` filter, so those rows
simply stop being returned by any realm-scoped query going forward, which
is the safe direction for a security fix.

The index swap runs CONCURRENTLY, each in its own autocommit block outside
the migration's transaction, and builds the new index before dropping the
old one — required so this does not hold a blocking lock (or leave the
table briefly unindexed) on a populated production table.

Revision ID: f1a2b3c4d5e6
Revises: c7d8e9f0a1b2
Create Date: 2026-08-17 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_process",
        sa.Column("realm_id", sa.String(length=255), nullable=True),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_auth_process_realm_user_final_finished",
            "auth_process",
            ["realm_id", "user_id", "final_status", sa.text("finished_at DESC")],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_auth_process_user_final_finished",
            table_name="auth_process",
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_auth_process_user_final_finished",
            "auth_process",
            ["user_id", "final_status", sa.text("finished_at DESC")],
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_auth_process_realm_user_final_finished",
            table_name="auth_process",
            postgresql_concurrently=True,
        )
    op.drop_column("auth_process", "realm_id")
