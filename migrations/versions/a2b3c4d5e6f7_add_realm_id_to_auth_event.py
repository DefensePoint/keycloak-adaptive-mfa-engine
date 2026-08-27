"""Add realm_id to auth_event

Adds a tenant/realm column to the auth_event audit table, matching
auth_process (see f1a2b3c4d5e6). The webhook that populates this table
now records the realm that SIGNED each event, so the audit trail itself
carries an authenticated tenant tag rather than trusting event/claim
content for it -- closing a gap where the login-event webhook carried
no tenant or subject binding at all.

Existing rows have no way to know which realm produced them, so the
column is left NULL rather than guessed or backfilled to a placeholder.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-17 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_event",
        sa.Column("realm_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auth_event", "realm_id")
