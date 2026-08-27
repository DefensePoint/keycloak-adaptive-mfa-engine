"""change auth process table name to correct spell

Revision ID: d2c8a354fa75
Revises: 64a676369888
Create Date: 2025-05-16 15:30:18.304153

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2c8a354fa75"
down_revision: Union[str, None] = "64a676369888"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) add the correctly spelled column
    op.add_column(
        "auth_process", sa.Column("device_credibility", sa.Float(), nullable=True)
    )

    # 2) copy data over from the old (misspelled) column
    op.execute(
        sa.text("UPDATE auth_process " "SET device_credibility = device_credibily")
    )

    # 3) drop the old, misspelled column
    op.drop_column("auth_process", "device_credibily")


def downgrade() -> None:
    # 1) re-create the old, misspelled column
    op.add_column(
        "auth_process", sa.Column("device_credibily", sa.Float(), nullable=True)
    )

    # 2) copy data back from the correctly spelled column
    op.execute(
        sa.text("UPDATE auth_process " "SET device_credibily = device_credibility")
    )

    # 3) drop the corrected column
    op.drop_column("auth_process", "device_credibility")
