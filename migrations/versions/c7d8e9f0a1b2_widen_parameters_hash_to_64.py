"""Widen decision_params_config.parameters_hash to 64 chars

The column was VARCHAR(32) but every writer stores a SHA3-256 hex digest,
which is 64 characters. On PostgreSQL that insert is rejected with
"value too long for type character varying(32)", so config activation could
fail. Widen to VARCHAR(64) to match the digest and the sibling hash columns
(device, auth_context, location_network are all VARCHAR(64)).

Also set NOT NULL: every config version is identified by its hash and every
writer supplies one, so a null parameters_hash is never valid. Existing rows
all have a non-null hash, so the constraint applies cleanly.

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28 06:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "decision_params_config",
        "parameters_hash",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=True,
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "decision_params_config",
        "parameters_hash",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
        nullable=True,
    )
