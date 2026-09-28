"""Response models for the monitoring endpoints.

Field names are kept stable and self-explanatory so external monitoring
consumers need no translation layer.
"""

from datetime import datetime
from typing import Annotated, List, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator


def _uuid_to_str(value):
    """Render a UUID column as a string.

    The driver returns uuid.UUID objects for these columns.
    """
    return str(value) if isinstance(value, UUID) else value


# Shared coercion for every UUID-backed field below, so the two response
# models that carry one don't each redefine the same validator.
UUIDStr = Annotated[str, BeforeValidator(_uuid_to_str)]
OptionalUUIDStr = Annotated[Optional[str], BeforeValidator(_uuid_to_str)]


class MonitoringEventRow(BaseModel):
    """One authentication event, flattened across the three tables."""

    event_id: UUIDStr
    event_time: datetime
    event_type: str
    user_id: OptionalUUIDStr = None
    client: str = ""
    ip_address: str = ""
    country: Optional[str] = None
    city: Optional[str] = None
    lat: Optional[float] = None
    long: Optional[float] = None
    is_vpn: bool = False
    risk_level: Optional[int] = None
    final_status: Optional[str] = None
    operating_system: Optional[str] = None
    browser: Optional[str] = None
    device: Optional[str] = None
    system_language: Optional[str] = None
    screen_resolution: Optional[str] = None


class MonitoringEventsPage(BaseModel):
    """A page of events plus the total matching the same filters.

    `next_cursor` is `event_time|event_id`. Compound because two events can
    share a timestamp.
    """

    items: List[MonitoringEventRow]
    total: int
    next_cursor: Optional[str] = None


class MonitoringStats(BaseModel):
    """Aggregate counts over one realm and time window.

    `flagged_ips` counts distinct VPN-flagged addresses, not events.
    """

    total: int
    risky: int
    unique_users: int
    flagged_ips: int


class MonitoringGeoBucket(BaseModel):
    """Events grouped into a rounded coordinate cell for map display."""

    country: Optional[str] = None
    lat: float
    long: float
    count: int
    risky_count: int


class MonitoringRiskyUser(BaseModel):
    """A user whose risky-event count reached the requested threshold."""

    user_id: UUIDStr
    count: int


class MonitoringEventCount(BaseModel):
    """Count of one event type within a time window."""

    event_type: str
    count: int
