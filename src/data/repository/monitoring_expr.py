"""Shared SQLAlchemy expressions for the monitoring read queries.

Context fields read `auth_context` first and fall back to the
`auth_context_json` snapshot on `auth_process`. Nothing writes rows to
`auth_context`, and a LEFT JOIN against it yields NULL rather than an error, so
a query reading only the table returns no data and no failure.

IP, country, VPN flag and coordinates fall back once more, to
`location_network`. A LOGIN_ERROR stored without a risk decision (a wrong
password or an unknown user, which fail before AMFA's step runs) has no
`auth_process` and so no snapshot, but the webhook still wrote its network
location. Its coordinates are there only for rows written since that table
had them (migration 5ae8978564f9), or filled since.

The realm filter reads the `realm_id` column first and falls back to the same
snapshot. Migrations f1a2b3c4d5e6 and a2b3c4d5e6f7 left pre-existing rows NULL.
"""

from sqlalchemy import Boolean, Float, Numeric, and_, case, cast, func, literal, or_

from src.core.sql_dialect import EmptyAsNull, JsonBool, JsonText, NullIfEq
from src.data.model import AuthContext, AuthEvent, AuthProcess, LocationNetwork


def _json_text(key: str):
    """Extract a JSON key as text, treating an empty string as NULL.

    Compiles to Postgres `->>` and to SQL Server `JSON_VALUE`. Empty string
    becomes NULL on both.
    """
    return func.nullif(JsonText(AuthProcess.auth_context_json, key), "")


def _json_bool(key: str):
    return JsonBool(AuthProcess.auth_context_json, key)


# --- realm / tenant -------------------------------------------------------

realm_id_expr = func.coalesce(
    func.nullif(AuthProcess.realm_id, ""),
    _json_text("realm_id"),
)


def realm_filter(realm_id: str):
    """Restrict a query to one realm.

    Checks `auth_event.realm_id` first, guarded so the auth_process/JSON
    fallback only applies when it's absent (a legacy row, or an event whose
    `auth_process` never linked). An unconditional OR across both sources
    measurably prevented Postgres from using
    ix_auth_event_realm_id_event_time_id at all: verified live against a
    305k-row seeded table, the unconditional OR ran a full parallel scan in
    ~185ms, and this form used an index-only scan in ~0.1ms. Confirmed
    equivalent on data written after b3c4d5e6f7a8 (which backfilled
    auth_event.realm_id from auth_process for every recoverable row) and
    a2b3c4d5e6f7 (which stamps it directly at write time going forward): the
    two sources never disagree for rows that have both.
    """
    return or_(realm_on_event(realm_id), realm_fallback(realm_id))


def realm_on_event(realm_id: str):
    """The realm stamped on the event itself: what the realm index serves."""
    return NullIfEq(AuthEvent.realm_id, realm_id)


def realm_fallback(realm_id: str):
    """An event with no realm of its own, matched through its auth_process."""
    return and_(EmptyAsNull(AuthEvent.realm_id), realm_id_expr == realm_id)


# --- login context --------------------------------------------------------

# The network location's VPN flag as a value. A comparison cannot stand in for
# a value inside COALESCE on SQL Server, so it goes through a CASE.
_network_is_vpn = case(
    (LocationNetwork.is_vpn_flag.is_(None), None),
    (LocationNetwork.is_vpn_flag != 0, literal(True)),
    else_=literal(False),
).cast(Boolean)

client_expr = func.coalesce(AuthContext.client, _json_text("client"), literal(""))
ip_expr = func.coalesce(
    AuthContext.ip_address,
    _json_text("ip_address"),
    func.nullif(LocationNetwork.ip_address, ""),
    literal(""),
)
# The engine stores a country it could not resolve as the text "None".
country_expr = func.coalesce(
    func.nullif(AuthContext.country_name, ""),
    _json_text("country_name"),
    func.nullif(func.nullif(LocationNetwork.country, ""), "None"),
)
lat_expr = func.coalesce(
    AuthContext.lat, cast(_json_text("lat"), Float), LocationNetwork.lat
)
long_expr = func.coalesce(
    AuthContext.long, cast(_json_text("long"), Float), LocationNetwork.long
)
is_vpn_expr = func.coalesce(
    AuthContext.is_vpn, _json_bool("is_vpn"), _network_is_vpn, literal(False)
)

# AuthContext has no city column, so city has no table-first fallback to apply.
city_expr = _json_text("city_name")
os_expr = func.coalesce(func.nullif(AuthContext.operating_system, ""), _json_text("operating_system"))
browser_expr = func.coalesce(func.nullif(AuthContext.browser, ""), _json_text("browser"))
device_expr = func.coalesce(func.nullif(AuthContext.device, ""), _json_text("device"))
system_language_expr = func.coalesce(
    func.nullif(AuthContext.system_language, ""), _json_text("system_language")
)
screen_resolution_expr = func.coalesce(
    func.nullif(AuthContext.screen_resolution, ""), _json_text("screen_resolution")
)


# --- geolocation ----------------------------------------------------------

# 0.1 degree, roughly 11 km.
GEO_PRECISION = 1


def has_usable_geo():
    """Exclude logins without a real coordinate.

    The geolocation helper writes 0,0 when a lookup fails, which is normal for
    a private address.
    """
    return (
        lat_expr.isnot(None)
        & long_expr.isnot(None)
        & ~((lat_expr == 0) & (long_expr == 0))
    )


def geo_cell(expr):
    """Round a coordinate to its map cell.

    Casting to `numeric` at the cell's own scale is the rounding, and it works on
    both dialects: PostgreSQL has no `round(double precision, int)`. A second
    rounding step would move 38.74996 to 38.75 and then to the wrong cell, 38.8.
    The scale must be explicit, because SQL Server's bare `NUMERIC` is an integer.
    The 8 integer digits are headroom: a bad stored value must not overflow the
    cast and fail the whole query.
    """
    return cast(cast(expr, Numeric(8 + GEO_PRECISION, GEO_PRECISION)), Float)


# --- risk -----------------------------------------------------------------

def risky_filter(min_risk: int):
    """Rows at or above a risk level.

    An event with no linked `auth_process` yields NULL and does not match.
    """
    return AuthProcess.pre_auth_risk_decision >= min_risk


def risky_count_case(min_risk: int):
    """`COUNT(*) FILTER (WHERE risk >= min_risk)` as a countable expression."""
    return case((risky_filter(min_risk), 1))
