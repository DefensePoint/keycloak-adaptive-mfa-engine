"""What the engine's queries return on a real server, on both dialects."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from src.api.health_route import HealthRoute
from src.core.config.environment import DB_TYPE, HEALTH_CHECK_TIMEOUT
from src.core.database import DB
from src.core.sql_dialect import JsonText
from src.data.model import (
    AuthContext,
    AuthEvent,
    AuthProcess,
    DecisionParamsConfig,
    Device,
    LocationNetwork,
)
from src.data.repository import monitoring_expr
from src.data.repository.decision_params_config import DecisionParamsConfigRepository
from src.data.repository.monitoring import MonitoringRepository

pytestmark = pytest.mark.asyncio(loop_scope="session")

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
HASH = "a" * 64


async def _add(*rows) -> None:
    async with DB.get_session()() as session:
        session.add_all(rows)
        await session.commit()


def _config(realm: str = "prod", group: str = "default", active: bool = True):
    return DecisionParamsConfig(
        id=uuid.uuid4(),
        realm_id=realm,
        group_id=group,
        is_active=active,
        parameters={"threshold": 3},
        parameters_hash=HASH,
    )


def _auth_context(hash_value: str, **overrides) -> AuthContext:
    fields = dict(
        hash=hash_value,
        client="web",
        ip_address="192.0.2.1",
        system_language="en",
        screen_resolution="1x1",
    )
    return AuthContext(**{**fields, **overrides})


async def _seed_login(
    realm: str = "prod",
    context: dict | None = None,
    event_time: datetime = T0,
    risk: int = 1,
    event_type: str = "LOGIN",
) -> AuthEvent:
    """One login: its config, device, network, process, and event."""
    config = _config(realm=realm)
    device_hash = uuid.uuid4().hex + uuid.uuid4().hex
    network_hash = uuid.uuid4().hex + uuid.uuid4().hex
    process = AuthProcess(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        realm_id=realm,
        auth_context_hash=HASH,
        device_info_hash=device_hash,
        network_location_hash=network_hash,
        auth_context_json=context or {},
        pre_auth_risk_decision=risk,
        parameters_config_id=config.id,
        final_status="success",
    )
    event = AuthEvent(
        id=uuid.uuid4(),
        auth_process=process.id,
        user_id=process.user_id,
        realm_id=realm,
        event_type=event_type,
        event_time=event_time,
    )
    await _add(
        config,
        Device(
            hash=device_hash,
            system_language="en",
            screen_resolution="1x1",
            device="desktop",
        ),
        LocationNetwork(hash=network_hash, ip_address="192.0.2.1"),
    )
    await _add(process)
    await _add(event)
    return event


# --- login scoring: the active-config lookup runs on every login decision ---


async def test_active_config_lookup_returns_only_the_active_row():
    active = _config(active=True)
    await _add(active, _config(group="other", active=False))

    found = await DecisionParamsConfigRepository.get_active_decision_params_config(
        "prod", "default"
    )
    assert found.id == active.id
    assert found.parameters == {"threshold": 3}


async def test_inactive_config_is_not_returned():
    await _add(_config(active=False))
    found = await DecisionParamsConfigRepository.get_active_decision_params_config(
        "prod", "default"
    )
    assert found is None


async def test_listing_active_configs_for_a_realm():
    await _add(_config(group="a"), _config(group="b"), _config(group="c", active=False))
    rows = await DecisionParamsConfigRepository.get_all_active_decision_params_by_realm(
        "prod"
    )
    assert sorted(r.group_id for r in rows) == ["a", "b"]


async def test_deactivating_a_group_config():
    await _add(_config(group="a"))
    await DecisionParamsConfigRepository.deactivate_group_config("prod", "a")
    assert (
        await DecisionParamsConfigRepository.get_active_decision_params_config("prod", "a")
        is None
    )


# --- tenant isolation: Keycloak realm and group names are case-sensitive ---


async def test_realm_lookup_is_case_sensitive():
    upper = _config(realm="Prod")
    await _add(upper)
    assert (
        await DecisionParamsConfigRepository.get_active_decision_params_config(
            "prod", "default"
        )
        is None
    )
    found = await DecisionParamsConfigRepository.get_active_decision_params_config(
        "Prod", "default"
    )
    assert found.id == upper.id


async def test_group_lookup_is_case_sensitive():
    await _add(_config(group="Admins"))
    assert (
        await DecisionParamsConfigRepository.get_active_decision_params_config(
            "prod", "admins"
        )
        is None
    )


async def test_hash_comparison_is_case_sensitive():
    lower = "b" * 64
    await _add(_auth_context(lower))
    async with DB.get_session()() as session:
        upper_match = (
            await session.execute(
                select(AuthContext).where(AuthContext.hash == lower.upper())
            )
        ).scalar_one_or_none()
    assert upper_match is None


async def test_monitoring_does_not_read_another_realm_differing_by_case():
    await _seed_login(realm="Prod")
    rows, total, _ = await MonitoringRepository.list_events("prod")
    assert rows == [] and total == 0


async def test_monitoring_falls_back_to_the_process_snapshot_for_legacy_rows():
    event = await _seed_login(realm="prod", context={"realm_id": "legacy"})
    async with DB.get_session()() as session:
        row = await session.get(AuthEvent, event.id)
        row.realm_id = ""
        process = await session.get(AuthProcess, row.auth_process)
        process.realm_id = None
        await session.commit()
    rows, total, _ = await MonitoringRepository.list_events("legacy")
    assert [r["event_id"] for r in rows] == [event.id] and total == 1


# --- text survives a round trip ---


@pytest.mark.parametrize(
    "country",
    ["Россия", "日本", "Российская Федерация!", "Ελλάδα", "🇵🇹 Portugal"],
)
async def test_non_latin_country_round_trips(country):
    hash_value = uuid.uuid4().hex + uuid.uuid4().hex
    await _add(_auth_context(hash_value, country_name=country))
    async with DB.get_session()() as session:
        row = await session.get(AuthContext, hash_value)
    assert row.country_name == country


async def test_non_latin_event_details_round_trip():
    event = await _seed_login()
    async with DB.get_session()() as session:
        row = await session.get(AuthEvent, event.id)
        row.details = "Устройство 设备 日本"
        await session.commit()
    async with DB.get_session()() as session:
        assert (await session.get(AuthEvent, event.id)).details == "Устройство 设备 日本"


async def test_non_latin_realm_lookup():
    config = _config(realm="Компания")
    await _add(config)
    found = await DecisionParamsConfigRepository.get_active_decision_params_config(
        "Компания", "default"
    )
    assert found.id == config.id


async def test_json_snapshot_keeps_non_latin_text_through_monitoring():
    await _seed_login(context={"country_name": "日本", "city_name": "Москва"})
    rows, _, _ = await MonitoringRepository.list_events("prod")
    assert rows[0]["country"] == "日本"
    assert rows[0]["city"] == "Москва"


# --- dates ---


async def test_event_time_reads_back_as_the_same_utc_instant():
    await _seed_login(event_time=T0)
    rows, _, _ = await MonitoringRepository.list_events("prod")
    value = rows[0]["event_time"]
    assert value.tzinfo is not None
    assert value == T0


async def test_server_default_event_time_is_current_utc():
    before = datetime.now(timezone.utc) - timedelta(minutes=5)
    event = await _seed_login()
    async with DB.get_session()() as session:
        row = await session.get(AuthEvent, event.id)
        process = await session.get(AuthProcess, row.auth_process)
    assert process.started_at.tzinfo is not None
    assert before < process.started_at < before + timedelta(minutes=10)


# --- monitoring: every endpoint's query, executed ---


async def test_event_pages_walk_every_row_once_in_both_directions():
    events = [
        await _seed_login(event_time=T0 + timedelta(seconds=i // 2)) for i in range(7)
    ]
    for ascending in (True, False):
        seen, cursor = [], None
        while True:
            rows, _, cursor = await MonitoringRepository.list_events(
                "prod", limit=3, cursor=cursor, ascending=ascending
            )
            seen += [r["event_id"] for r in rows]
            if cursor is None:
                break
        assert sorted(seen, key=str) == sorted((e.id for e in events), key=str)
        assert len(seen) == len(set(seen))


async def test_event_pages_merge_both_realm_sources_in_order():
    """Events with a realm of their own and events matched through their
    auth_process are read in separate branches. Interleaved in time, with
    shared timestamps and another realm's events around them, every page walk
    must return exactly the rows, in the order, of one unpaged query with the
    combined realm filter."""
    own, legacy = [], []
    for i in range(12):
        event = await _seed_login(event_time=T0 + timedelta(seconds=i // 3))
        if i % 3 == 1:
            legacy.append(event.id)
        else:
            own.append(event.id)
        await _seed_login(realm="other", event_time=T0 + timedelta(seconds=i // 3))
    async with DB.get_session()() as session:
        for event_id in legacy:
            row = await session.get(AuthEvent, event_id)
            row.realm_id = None if DB_TYPE == "mssql" else ""
            process = await session.get(AuthProcess, row.auth_process)
            process.realm_id = None
            process.auth_context_json = {"realm_id": "prod"}
        await session.commit()

    for since in (None, T0 + timedelta(seconds=1)):
        for ascending in (True, False):
            direction = (AuthEvent.event_time, AuthEvent.id) if ascending else (
                AuthEvent.event_time.desc(), AuthEvent.id.desc())
            reference = select(AuthEvent.id).outerjoin(
                AuthProcess, AuthProcess.id == AuthEvent.auth_process
            ).where(monitoring_expr.realm_filter("prod"))
            if since is not None:
                reference = reference.where(AuthEvent.event_time > since)
            async with DB.get_session()() as session:
                expected = list((await session.execute(reference.order_by(*direction))).scalars())
            seen, cursor = [], None
            while True:
                rows, _, cursor = await MonitoringRepository.list_events(
                    "prod", since=since, limit=3, cursor=cursor, ascending=ascending
                )
                seen += [r["event_id"] for r in rows]
                if cursor is None:
                    break
            assert len(expected) == (12 if since is None else 6)
            assert seen == expected, (since, ascending)


async def test_first_page_reports_the_total_and_later_pages_skip_it():
    for i in range(3):
        await _seed_login(event_time=T0 + timedelta(seconds=i))
    rows, total, cursor = await MonitoringRepository.list_events("prod", limit=2)
    assert (len(rows), total) == (2, 3)
    rows, total, cursor = await MonitoringRepository.list_events(
        "prod", limit=2, cursor=cursor
    )
    assert (len(rows), total, cursor) == (1, -1, None)


async def test_vpn_filter_reads_the_snapshot():
    await _seed_login(context={"is_vpn": True, "ip_address": "198.51.100.1"})
    await _seed_login(context={"is_vpn": False, "ip_address": "198.51.100.2"})
    await _seed_login(context={})

    on, on_total, _ = await MonitoringRepository.list_events("prod", is_vpn=True)
    off, off_total, _ = await MonitoringRepository.list_events("prod", is_vpn=False)
    assert [r["ip_address"] for r in on] == ["198.51.100.1"] and on_total == 1
    assert off_total == 2 and len(off) == 2
    assert on[0]["is_vpn"] in (True, 1)


async def _seed_failed_login(
    ip: str, country: str, vpn: int, lat=None, long=None
) -> AuthEvent:
    """A LOGIN_ERROR stored without a risk decision, as a wrong password or an
    unknown user is: no auth_process, only its network location."""
    network_hash = uuid.uuid4().hex + uuid.uuid4().hex
    await _add(
        LocationNetwork(
            hash=network_hash,
            ip_address=ip,
            country=country,
            is_vpn_flag=vpn,
            lat=lat,
            long=long,
        )
    )
    event = AuthEvent(
        id=uuid.uuid4(),
        realm_id="prod",
        event_type="LOGIN_ERROR",
        event_time=T0,
        network_location_hash=network_hash,
    )
    await _add(event)
    return event


async def test_failed_login_without_a_process_reads_its_network_location():
    located = await _seed_failed_login("198.51.100.77", "NL", 1)
    # The engine stores a country it could not resolve as the text "None".
    unlocated = await _seed_failed_login("10.0.0.9", "None", 0)

    rows, total, _ = await MonitoringRepository.list_events("prod")
    by_id = {r["event_id"]: r for r in rows}
    assert total == 2
    assert by_id[located.id]["ip_address"] == "198.51.100.77"
    assert by_id[located.id]["country"] == "NL"
    assert by_id[located.id]["is_vpn"] in (True, 1)
    assert by_id[located.id]["lat"] is None
    assert by_id[unlocated.id]["ip_address"] == "10.0.0.9"
    assert by_id[unlocated.id]["country"] is None
    assert by_id[unlocated.id]["is_vpn"] in (False, 0)

    on, on_total, _ = await MonitoringRepository.list_events("prod", is_vpn=True)
    assert [r["event_id"] for r in on] == [located.id] and on_total == 1
    assert (await MonitoringRepository.get_stats("prod"))["flagged_ips"] == 1


async def test_failed_login_with_coordinates_is_on_the_map():
    located = await _seed_failed_login("198.51.100.77", "NL", 0, 52.3676, 4.9041)
    await _seed_failed_login("10.0.0.9", "", 0)

    rows, _, _ = await MonitoringRepository.list_events("prod")
    by_id = {r["event_id"]: r for r in rows}
    assert by_id[located.id]["lat"] == pytest.approx(52.3676)
    assert by_id[located.id]["long"] == pytest.approx(4.9041)

    buckets = await MonitoringRepository.get_geo_buckets("prod")
    assert buckets == [
        {"country": "NL", "lat": 52.4, "long": 4.9, "count": 1, "risky_count": 0}
    ]


async def test_coordinates_fill_only_a_row_without_them():
    from src.data.repository.location_network import LocationNetworkRepository

    empty_hash = uuid.uuid4().hex + uuid.uuid4().hex
    full_hash = uuid.uuid4().hex + uuid.uuid4().hex
    await _add(
        LocationNetwork(hash=empty_hash, ip_address="198.51.100.8"),
        LocationNetwork(hash=full_hash, ip_address="198.51.100.9", lat=1.5, long=2.5),
    )
    assert await LocationNetworkRepository.set_coordinates_if_missing(empty_hash, 47.38, 8.54)
    assert not await LocationNetworkRepository.set_coordinates_if_missing(full_hash, 9.0, 9.0)
    async with DB.get_session()() as session:
        filled = await session.get(LocationNetwork, empty_hash)
        kept = await session.get(LocationNetwork, full_hash)
    assert (filled.lat, filled.long) == (pytest.approx(47.38), pytest.approx(8.54))
    assert (kept.lat, kept.long) == (pytest.approx(1.5), pytest.approx(2.5))


async def test_a_scored_login_prefers_its_snapshot_to_the_network_location():
    event = await _seed_login(
        context={"ip_address": "198.51.100.5", "country_name": "PT", "is_vpn": False}
    )
    async with DB.get_session()() as session:
        row = await session.get(AuthEvent, event.id)
        process = await session.get(AuthProcess, row.auth_process)
        row.network_location_hash = process.network_location_hash
        network = await session.get(LocationNetwork, process.network_location_hash)
        network.country = "XX"
        network.is_vpn_flag = 1
        await session.commit()

    rows, _, _ = await MonitoringRepository.list_events("prod")
    assert rows[0]["ip_address"] == "198.51.100.5"
    assert rows[0]["country"] == "PT"
    assert rows[0]["is_vpn"] in (False, 0)


async def test_risk_filters():
    await _seed_login(risk=1)
    await _seed_login(risk=4)
    assert (await MonitoringRepository.list_events("prod", min_risk=3))[1] == 1
    assert (await MonitoringRepository.list_events("prod", risk_decision=1))[1] == 1


async def test_window_excludes_since_and_includes_until():
    await _seed_login(event_time=T0)
    await _seed_login(event_time=T0 + timedelta(hours=1))
    assert (await MonitoringRepository.list_events("prod", since=T0))[1] == 1
    assert (await MonitoringRepository.list_events("prod", until=T0))[1] == 1


async def test_stats():
    await _seed_login(risk=1, context={"is_vpn": True, "ip_address": "198.51.100.1"})
    await _seed_login(risk=4, context={"is_vpn": True, "ip_address": "198.51.100.1"})
    await _seed_login(risk=1, context={"is_vpn": False, "ip_address": "198.51.100.2"})
    await _seed_login(realm="other", risk=4)
    assert await MonitoringRepository.get_stats("prod") == {
        "total": 3,
        "risky": 1,
        "unique_users": 3,
        "flagged_ips": 1,
    }


async def test_geo_buckets_group_at_the_configured_precision():
    lisbon = {"country_name": "Portugal", "lat": 38.7223, "long": -9.1393}
    nearby = {"country_name": "Portugal", "lat": 38.7301, "long": -9.1412}
    tokyo = {"country_name": "日本", "lat": 35.6762, "long": 139.6503}
    await _seed_login(context=lisbon, risk=4)
    await _seed_login(context=nearby)
    await _seed_login(context=tokyo)
    await _seed_login(context={"country_name": "Nowhere", "lat": 0, "long": 0})
    await _seed_login(context={"country_name": "Unknown"})

    buckets = await MonitoringRepository.get_geo_buckets("prod")
    assert buckets == [
        {"country": "Portugal", "lat": 38.7, "long": -9.1, "count": 2, "risky_count": 1},
        {"country": "日本", "lat": 35.7, "long": 139.7, "count": 1, "risky_count": 0},
    ]


async def test_geo_buckets_round_the_stored_coordinate_only_once():
    """38.74996 is in the 38.7 cell. Rounding through 4 decimals first gave 38.8."""
    await _seed_login(context={"lat": 38.74996, "long": -9.14996})
    buckets = await MonitoringRepository.get_geo_buckets("prod")
    assert [(b["lat"], b["long"]) for b in buckets] == [(38.7, -9.1)]


@pytest.mark.parametrize(
    "precision, expected",
    [(0, (39.0, -9.0)), (1, (38.7, -9.1)), (4, (38.7223, -9.1393)), (6, (38.722312, -9.139344))],
)
async def test_geo_buckets_honour_the_configured_precision(
    monkeypatch, precision, expected
):
    monkeypatch.setattr(monitoring_expr, "GEO_PRECISION", precision)
    await _seed_login(context={"lat": 38.722312, "long": -9.139344})
    buckets = await MonitoringRepository.get_geo_buckets("prod")
    assert [(b["lat"], b["long"]) for b in buckets] == [expected]


async def test_risky_users():
    event = await _seed_login(risk=4)
    await _seed_login(risk=1)
    assert await MonitoringRepository.get_risky_users("prod") == [
        {"user_id": str(event.user_id), "count": 1}
    ]
    assert await MonitoringRepository.get_risky_users("prod", threshold=2) == []


async def test_count_by_event_type():
    await _seed_login(event_type="LOGIN")
    await _seed_login(event_type="LOGIN_ERROR")
    assert await MonitoringRepository.count_by_event_type("prod", "LOGIN") == 1


# --- SQLAlchemy's compiled cache must not cross JSON keys or bound values ---


async def test_cached_statements_do_not_cross_json_keys():
    await _seed_login(context={"country_name": "Portugal", "city_name": "Lisbon"})
    values = []
    async with DB.get_session()() as session:
        for key in ("country_name", "city_name"):
            stmt = select(JsonText(AuthProcess.auth_context_json, key))
            values.append((await session.execute(stmt)).scalar_one())
    assert values == ["Portugal", "Lisbon"]


async def test_cached_realm_filter_does_not_reuse_the_previous_realm():
    await _seed_login(realm="a")
    await _seed_login(realm="b")
    await _seed_login(realm="b")
    assert (await MonitoringRepository.list_events("a"))[1] == 1
    assert (await MonitoringRepository.list_events("b"))[1] == 2


# --- /health ---------------------------------------------------------------


async def test_the_health_check_runs_on_a_real_server_outside_the_shared_pool(
    monkeypatch,
):
    def shared_pool_used():
        raise AssertionError("/health must not use the shared pool")

    monkeypatch.setattr(DB, "get_session", shared_pool_used)
    await HealthRoute._ping_db()
    assert await HealthRoute()._status(HealthRoute._ping_db) == "ok"


async def test_a_stuck_query_on_a_health_connection_times_out():
    """The driver has to honour the timeout, not just accept the setting."""
    slow = "WAITFOR DELAY '00:00:20'" if DB_TYPE == "mssql" else "SELECT pg_sleep(20)"
    started = time.monotonic()
    with pytest.raises(Exception):
        async with DB.get_health_session()() as session:
            await session.execute(text(slow))
    assert time.monotonic() - started < HEALTH_CHECK_TIMEOUT + 3


async def test_the_real_redis_ping_closes_its_client():
    await HealthRoute._ping_redis()
