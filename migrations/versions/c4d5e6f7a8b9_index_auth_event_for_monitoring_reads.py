"""Index auth_event for the monitoring read endpoints

The monitoring queries (src/data/repository/monitoring.py) filter by realm and
page/order by (event_time, id), and every one of them left-joins auth_process
through auth_event.auth_process. None of that is covered by an existing
index: ix_auth_user_event_time_desc leads with user_id, which none of these
queries filter on, and auth_event.auth_process has no index at all.

b3c4d5e6f7a8 backfilled auth_event.realm_id from auth_process for every row
where it was recoverable, so the realm-scoped path here now covers the large
majority of rows directly off auth_event, without needing the auth_process
join at all.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-25 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Serves realm_filter's auth_event.realm_id branch plus the (event_time,
    # id) keyset ordering directly, for every row realm_id was recoverable
    # for. CONCURRENTLY would be preferable on a live table, but this repo's
    # other migrations run inside the standard Alembic transaction, so we
    # stay consistent with that rather than special-casing one migration.
    op.create_index(
        "ix_auth_event_realm_id_event_time_id",
        "auth_event",
        ["realm_id", sa.text("event_time DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("realm_id IS NOT NULL"),
    )
    # Supports the auth_event -> auth_process join every monitoring query
    # makes (for the orphan-row fallback in realm_filter, and for
    # risk/final_status columns), which had no index on the FK side at all.
    op.create_index(
        "ix_auth_event_auth_process",
        "auth_event",
        ["auth_process"],
        postgresql_where=sa.text("auth_process IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_auth_event_auth_process", table_name="auth_event")
    op.drop_index("ix_auth_event_realm_id_event_time_id", table_name="auth_event")
