"""location_network coordinates

A login that fails before AMFA's step (a wrong password, an unknown user) is
stored with no auth_process, so it has no snapshot to read coordinates from,
and the monitoring map could not place it. location_network is written for
every event, so it carries them from now on.

Existing rows are not backfilled here: copying from auth_process would scan
that table during the upgrade. A row gets its coordinates the next time the
engine sees its address.

Revision ID: 5ae8978564f9
Revises: f7a8b9c0d1e2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5ae8978564f9"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("location_network", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("location_network", sa.Column("long", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("location_network", "long")
    op.drop_column("location_network", "lat")
