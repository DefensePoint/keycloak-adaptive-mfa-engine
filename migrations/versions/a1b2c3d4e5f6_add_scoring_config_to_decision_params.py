"""Add scoring_config to decision_params_config

Adds an optional per-realm/group risk-scoring configuration column
(mode, bias, thresholds). Null falls back to deployment env defaults.

Revision ID: a1b2c3d4e5f6
Revises: d2c8a354fa75
Create Date: 2026-06-22 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d2c8a354fa75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "decision_params_config",
        sa.Column("scoring_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("decision_params_config", "scoring_config")
