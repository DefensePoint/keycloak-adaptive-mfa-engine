"""Shared SQLAlchemy expressions for the monitoring read queries.

Context fields read `auth_context` first and fall back to the
`auth_context_json` snapshot on `auth_process`. Nothing writes rows to
`auth_context`, and a LEFT JOIN against it yields NULL rather than an error, so
a query reading only the table returns no data and no failure.

The realm filter reads the `realm_id` column first and falls back to the same
snapshot. Migrations f1a2b3c4d5e6 and a2b3c4d5e6f7 left pre-existing rows NULL.
"""

from sqlalchemy import Boolean, Float, Numeric, and_, case, cast, func, literal, or_

from src.data.model import AuthContext, AuthEvent, AuthProcess


def _json_text(key: str):
    """Extract a JSON key as text, treating an empty string as NULL.

    The column is `JSON`, not `JSONB`, so `as_string()` emits `->>`. A `->`
    extraction keeps the JSON quoting and never matches a plain string.
    """
    return func.nullif(AuthProcess.auth_context_json[key].as_string(), "")


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
    return or_(
        func.nullif(AuthEvent.realm_id, "") == realm_id,
        and_(
            func.nullif(AuthEvent.realm_id, "").is_(None),
            realm_id_expr == realm_id,
        ),
    )


# --- login context --------------------------------------------------------

client_expr = func.coalesce(AuthContext.client, _json_text("client"), literal(""))
ip_expr = func.coalesce(AuthContext.ip_address, _json_text("ip_address"), literal(""))
country_expr = func.coalesce(
    func.nullif(AuthContext.country_name, ""), _json_text("country_name")
)
lat_expr = func.coalesce(AuthContext.lat, cast(_json_text("lat"), Float))
long_expr = func.coalesce(AuthContext.long, cast(_json_text("long"), Float))
is_vpn_expr = func.coalesce(
    AuthContext.is_vpn, cast(_json_text("is_vpn"), Boolean), literal(False)
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

    Rounds through `numeric`: PostgreSQL has no `round(double precision, int)`.
    """
    return cast(func.round(cast(expr, Numeric), GEO_PRECISION), Float)


# --- risk -----------------------------------------------------------------

def risky_filter(min_risk: int):
    """Rows at or above a risk level.

    An event with no linked `auth_process` yields NULL and does not match.
    """
    return AuthProcess.pre_auth_risk_decision >= min_risk


def risky_count_case(min_risk: int):
    """`COUNT(*) FILTER (WHERE risk >= min_risk)` as a countable expression."""
    return case((risky_filter(min_risk), 1))
