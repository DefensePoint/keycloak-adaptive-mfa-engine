"""Backfill realm_id from auth_context_json

f1a2b3c4d5e6 and a2b3c4d5e6f7 added realm_id and left existing rows NULL, which
is correct for a security fix: a row whose tenant is unknown must not be served.

Those rows are not unattributable, though. auth_process has always carried the
realm in its auth_context_json snapshot, so it can be recovered exactly rather
than guessed. auth_event rows inherit it through their auth_process.

This matters for read-only consumers reporting on history: a monitoring
consumer querying a rolling 30-day window would see unattributed rows as no
activity.

Only rows whose realm can be established are updated. Anything else stays NULL.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULLIF keeps an empty string from becoming a realm named "".
    op.execute(
        """
        UPDATE auth_process
           SET realm_id = NULLIF(auth_context_json->>'realm_id', '')
         WHERE realm_id IS NULL
           AND NULLIF(auth_context_json->>'realm_id', '') IS NOT NULL
        """
    )

    # Events whose auth_process never linked keep NULL.
    op.execute(
        """
        UPDATE auth_event AS e
           SET realm_id = p.realm_id
          FROM auth_process AS p
         WHERE e.auth_process = p.id
           AND e.realm_id IS NULL
           AND p.realm_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Intentionally empty. The upgrade only fills values that were already
    # recoverable from data in the same row, so there is nothing to undo: it
    # cannot distinguish a value it wrote from one written normally afterwards,
    # and clearing both would discard live tenant attribution.
    pass
