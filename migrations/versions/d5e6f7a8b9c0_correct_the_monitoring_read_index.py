"""Correct the monitoring-read index

c4d5e6f7a8b9 added two indexes that turned out, on live verification against
a seeded 305k-row table, not to do what they were meant to:

1. ix_auth_event_realm_id_event_time_id indexed the bare `realm_id` column,
   but every monitoring query filters through `nullif(realm_id, '')`
   (monitoring_expr.py), never the bare column. Postgres cannot use a
   plain-column index to satisfy a wrapped expression, even one that is
   logically equivalent for any non-empty literal: EXPLAIN confirmed this
   index was never chosen, and the query fell back to a full scan
   regardless. Replaced with an index on the expression actually queried.

2. ix_auth_event_auth_process (on auth_event.auth_process) assumed the
   monitoring queries look up FROM auth_process INTO auth_event via that
   FK. They don't: every query starts at auth_event and joins INTO
   auth_process by primary key (`auth_process.id = auth_event.auth_process`),
   which the existing auth_process_pkey already serves — confirmed via
   EXPLAIN, which never touched this index. Dropped: it was write overhead
   with no matching read pattern in this codebase.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-25 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_auth_event_auth_process", table_name="auth_event")
    op.drop_index("ix_auth_event_realm_id_event_time_id", table_name="auth_event")
    op.create_index(
        "ix_auth_event_realm_id_event_time_id",
        "auth_event",
        [sa.text("NULLIF(realm_id, '')"), sa.text("event_time DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_event_realm_id_event_time_id", table_name="auth_event")
    op.create_index(
        "ix_auth_event_realm_id_event_time_id",
        "auth_event",
        ["realm_id", sa.text("event_time DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("realm_id IS NOT NULL"),
    )
    op.create_index(
        "ix_auth_event_auth_process",
        "auth_event",
        ["auth_process"],
        postgresql_where=sa.text("auth_process IS NOT NULL"),
    )
