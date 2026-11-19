"""event_time in microseconds on SQL Server

SQL Server stamped auth_event.event_time with SYSUTCDATETIME(), to 100 ns.
The engine reads it back to the microsecond, so a page cursor built from a
row fell just before that row: walking the monitoring events oldest first
returned rows again, and newest first skipped them. The default now stamps
microseconds, and existing times are truncated to the microsecond the engine
has always read for them. Postgres stores microseconds already.

The data fix rewrites the rows with a sub-microsecond time. event_time leads
the clustered index on SQL Server, so on a large table this upgrade takes
longer than usual.

Revision ID: 94c441a0b691
Revises: 5ae8978564f9
"""

from typing import Sequence, Union

from alembic import op


revision: str = "94c441a0b691"
down_revision: Union[str, None] = "5ae8978564f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_NAME = "df_auth_event_event_time"


def _set_default(expression: str) -> None:
    """Replace event_time's default; the initial migration left it unnamed."""
    op.execute(
        """
        DECLARE @name sysname = (
            SELECT dc.name FROM sys.default_constraints dc
            JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
            WHERE dc.parent_object_id = OBJECT_ID('auth_event') AND c.name = 'event_time');
        DECLARE @sql nvarchar(400) = N'ALTER TABLE auth_event DROP CONSTRAINT ' + QUOTENAME(@name);
        IF @name IS NOT NULL EXEC (@sql);
        """
    )
    op.execute(f"ALTER TABLE auth_event ADD CONSTRAINT {DEFAULT_NAME} DEFAULT {expression} FOR event_time")


def upgrade() -> None:
    if op.get_bind().dialect.name != "mssql":
        return
    _set_default("TODATETIMEOFFSET(CAST(SYSUTCDATETIME() AS DATETIME2(6)), 0)")
    op.execute(
        "UPDATE auth_event SET event_time = DATEADD(nanosecond, -(DATEPART(nanosecond, event_time) % 1000), event_time) "
        "WHERE DATEPART(nanosecond, event_time) % 1000 <> 0"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "mssql":
        return
    _set_default("TODATETIMEOFFSET(SYSUTCDATETIME(), 0)")
