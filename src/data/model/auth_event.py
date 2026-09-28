"""
# AuthEvent Data Model

The **AuthEvent** model represents individual events or actions that occur
during the authentication process. This includes, logins, login errors, password
resets...

**Indexes**  
To facilitate faster retrieval of the most recent records, a composite index
is defined over `(auth_process, event_time DESC)`.
"""

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    text,
    Index,
    desc,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .base import Base


class AuthEvent(Base):
    """
    ## Fields

    - **id (UUID)**:
      Primary key for the event; auto-generated via UUID (v4).
    - **auth_process (UUID)**:
      Foreign key reference to the `auth_process` table.
    - **user_id (UUID)**:
      The user responsible for this authentication event.
    - **event_type (String)**:
      Describes the type of the event (e.g., "login").
    - **details (Text)**:
      Additional details provided by the Keycloak SPI for the event.
    - **event_time (DateTime)**:
      Timestamp (with timezone) denoting when the event occurred.
    """

    __tablename__ = "auth_event"
    __table_args__ = (
        Index(
            "ix_auth_user_event_time_desc",
            "user_id",
            desc("event_time"),
        ),
    )

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
        doc="Primary key: auto-generated UUID (v4).",
    )
    auth_process = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_process.id"),
        nullable=True,
        doc="References the auth_process for which this event belongs.",
    )
    user_id = Column(
        UUID(as_uuid=True),
        nullable=True,
        doc="References the user initiating this auth process.",
    )
    realm_id = Column(
        String(255),
        nullable=True,
        doc=(
            "The Keycloak realm (tenant) that signed the webhook event this "
            "record came from — taken from the verified token issuer, never "
            "from event/claim content."
        ),
    )
    event_type = Column(String(32), nullable=False, doc="The type of the event.")
    details = Column(Text, doc="Additional details provided by the Keycloak SPI for this event.")

    auth_context_hash = Column(
        String(64),
        nullable=True,
        doc="References the auth_context.hash.",
    )
    device_info_hash = Column(
        String(64),
        ForeignKey("device.hash"),
        nullable=True,
        doc="References the device.hash.",
    )
    network_location_hash = Column(
        String(64),
        ForeignKey("location_network.hash"),
        nullable=True,
        doc="References the location_network.hash.",
    )

    event_time = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Auto Timestamp noting when the event occurred.",
    )
