from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "auth_context",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("device", sa.String(length=128), nullable=True),
        sa.Column("client", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("system_language", sa.String(length=64), nullable=False),
        sa.Column("screen_resolution", sa.String(length=64), nullable=False),
        sa.Column("operating_system", sa.String(length=64), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("long", sa.Float(), nullable=True),
        sa.Column("is_vpn", sa.Boolean(), nullable=True),
        sa.Column("country_name", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("hash"),
    )

    op.create_table(
        "decision_params_config",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("realm_id", sa.String(length=255), nullable=False),
        sa.Column("group_id", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("parameters_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scoring_config", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "device",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("system_language", sa.String(length=64), nullable=False),
        sa.Column("screen_resolution", sa.String(length=64), nullable=False),
        sa.Column("operating_system", sa.String(length=64), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("device", sa.String(length=64), nullable=False),
        sa.Column("client", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("hash"),
    )

    op.create_table(
        "location_network",
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("geolocation_cluster_label", sa.Integer(), nullable=True),
        sa.Column("country", sa.String(length=32), nullable=True),
        sa.Column("is_vpn_flag", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.PrimaryKeyConstraint("hash"),
    )

    op.create_table(
        "auth_process",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("auth_context_hash", sa.String(length=64), nullable=False),
        sa.Column("device_info_hash", sa.String(length=64), nullable=False),
        sa.Column("network_location_hash", sa.String(length=64), nullable=False),
        sa.Column("auth_context_json", sa.JSON(), nullable=False),
        sa.Column("pre_auth_risk_decision", sa.Integer(), nullable=False),
        sa.Column("parameters_config_id", sa.UUID(), nullable=False),
        sa.Column("final_status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("risk_eval_vars", sa.JSON(), nullable=True),
        sa.Column("net_loc_credibility", sa.Float(), nullable=True),
        sa.Column("device_credibility", sa.Float(), nullable=True),
        sa.Column("realm_id", sa.String(length=255), nullable=True),
        # auth_context_hash intentionally has no foreign key: the original
        # chain dropped it (b0e1146d79df), auth_context rows are written
        # independently of the processes that reference them.
        sa.ForeignKeyConstraint(["device_info_hash"], ["device.hash"]),
        sa.ForeignKeyConstraint(["network_location_hash"], ["location_network.hash"]),
        sa.ForeignKeyConstraint(["parameters_config_id"], ["decision_params_config.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_process_realm_user_final_finished",
        "auth_process",
        ["realm_id", "user_id", "final_status", sa.text("finished_at DESC")],
    )

    op.create_table(
        "auth_event",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("auth_process", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "event_time",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("auth_context_hash", sa.String(length=64), nullable=True),
        sa.Column("device_info_hash", sa.String(length=64), nullable=True),
        sa.Column("network_location_hash", sa.String(length=64), nullable=True),
        sa.Column("realm_id", sa.String(length=255), nullable=True),
        # No foreign key on auth_context_hash, matching auth_process above.
        sa.ForeignKeyConstraint(["auth_process"], ["auth_process.id"]),
        sa.ForeignKeyConstraint(["device_info_hash"], ["device.hash"]),
        sa.ForeignKeyConstraint(["network_location_hash"], ["location_network.hash"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_user_event_time_desc",
        "auth_event",
        ["user_id", sa.text("event_time DESC")],
    )
    # Expression index: the monitoring queries filter through
    # NULLIF(realm_id, ''), never the bare column (see d5e6f7a8b9c0 in the
    # pre-squash history for the EXPLAIN-verified rationale).
    op.create_index(
        "ix_auth_event_realm_id_event_time_id",
        "auth_event",
        [sa.text("NULLIF(realm_id, '')"), sa.text("event_time DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_event_realm_id_event_time_id", table_name="auth_event")
    op.drop_index("ix_auth_user_event_time_desc", table_name="auth_event")
    op.drop_table("auth_event")
    op.drop_index(
        "ix_auth_process_realm_user_final_finished", table_name="auth_process"
    )
    op.drop_table("auth_process")
    op.drop_table("location_network")
    op.drop_table("device")
    op.drop_table("decision_params_config")
    op.drop_table("auth_context")
    # The uuid-ossp extension is left in place: it is database-scoped, may be
    # shared, and dropping it is an operator decision.
