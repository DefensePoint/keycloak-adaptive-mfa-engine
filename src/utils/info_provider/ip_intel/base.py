"""The provider result contract.

Two signals are resolved from an IP address, geolocation and anonymiser status,
and each has two implementations: a bundled one reading local data files, and an
optional one calling a third-party API. All four must return the same shape, or
switching provider silently changes what reaches the risk engine.

The contract is expressed as ``TypedDict`` rather than dataclasses deliberately.
Providers return plain dicts, the legacy shims map those onto the historical
dicts the risk checks already consume, and nothing needs to change at runtime for
the shape to be described and enforced. ``GEO_RESULT_KEYS`` and
``ANONYMITY_RESULT_KEYS`` are the runtime enforcement point, asserted by
``tests/unit/utils/info_provider/ip_intel/test_provider_contract.py`` against
every provider on both its resolved and its unresolved path.

Two invariants apply to every implementation:

* **Never raise.** This code runs on the authentication path. A missing data
  file, a corrupt database or an unreachable API must degrade the signal, not
  fail the login.
* **Never block indefinitely.** The bundled providers hold no socket at all; the
  API providers bound their own waits.
"""

from typing import Literal, Protocol, TypedDict

# --- geolocation -------------------------------------------------------------


class GeoResult(TypedDict):
    """What a geo provider returns.

    ``resolved`` is load-bearing: ``False`` means no position was established and
    the caller must not read ``lat``/``long`` as a location. The legacy shim maps
    that to ``0`` rather than ``None``, because ``impossible_travel`` raises on a
    ``None`` coordinate and treats ``(0, 0)`` as its not-geolocatable sentinel.

    ``country_iso`` is the ISO alpha-2 code, and it is what the legacy
    ``country_name`` field carries. Admins configure country allow/deny lists
    with the code, and stored history holds the code, so emitting a display name
    there would silently stop every configured country rule from matching.
    ``country_display_name`` is informational only.

    ``coordinate_source`` records how the position was obtained, which is what
    makes a country-centroid deployment diagnosable: every address in a country
    resolving to one point is expected there, not a bug.
    """

    lat: float | None
    long: float | None
    country_iso: str | None
    country_display_name: str
    city_name: str
    resolved: bool
    coordinate_source: Literal["city-db", "country-centroid", "none"]
    source: str


GEO_RESULT_KEYS = frozenset(GeoResult.__annotations__)


class GeoProvider(Protocol):
    def lookup(self, ip_address: str) -> GeoResult: ...


# --- anonymiser status -------------------------------------------------------

# Evaluation order matters and is shared by the providers and the tests.
#
# Suppression labels mark legitimate shared egress: Apple iCloud Private Relay,
# CDNs and corporate SASE all originate from hosting ranges, so without them a
# large population of ordinary users looks like a VPN. They are an override
# applied before any other verdict, never a competing weight.
SUPPRESSION_LABELS = ("privacy_relay", "corporate_egress")

# A match here is on its own sufficient to call an address anonymised.
HIGH_CONFIDENCE_LABELS = ("tor_exit", "commercial_vpn")

# Hosting is a weaker claim: it says where an address lives, not that it
# anonymises traffic. Gated behind ANON_DATACENTER_IS_VPN, off by default.
MEDIUM_CONFIDENCE_LABELS = ("datacenter",)

# Sources that can RAISE a flag, as opposed to suppression which only clears one.
DETECTION_LABELS = HIGH_CONFIDENCE_LABELS + MEDIUM_CONFIDENCE_LABELS

ALL_LABELS = SUPPRESSION_LABELS + DETECTION_LABELS


class AnonymityResult(TypedDict):
    """What an anonymity provider returns.

    Three fields carry meaning a bare ``is_vpn`` boolean cannot:

    * ``resolved`` separates "checked, found nothing" from "had nothing to check
      against". Reporting an unchecked address as clean is the silent fail-open
      this work exists to remove.
    * ``unchecked`` lists labels that could not be evaluated *for this address
      family*. The bundled Tor and VPN lists are IPv4-only, and there are no IPv6
      Tor exit addresses to be had, so for an IPv6 client only the ASN-backed
      datacenter check can answer. A "clean" verdict is only as strong as the
      sources actually consulted.
    * ``confidence`` is graded and accounts for absent suppression data.
      Suppression can only ever clear a flag, so its absence weakens a *positive*
      verdict (legitimate shared egress can no longer be ruled out) while leaving
      a negative one alone.

    ``is_vpn`` remains the single boolean the scoring path consumes, so the
    database schema and every risk check stay untouched.
    """

    labels: list[str]
    is_vpn: bool
    confidence: int
    list_age_days: int | None
    resolved: bool
    unchecked: list[str]
    source: str


ANONYMITY_RESULT_KEYS = frozenset(AnonymityResult.__annotations__)


class AnonymityProvider(Protocol):
    def classify(self, ip_address: str) -> AnonymityResult: ...


# --- shared unresolved shapes ------------------------------------------------

# Providers build their unresolved returns from these so the shape cannot drift
# between the resolved and unresolved paths, which are otherwise separate
# literals that get edited independently.

GEO_UNRESOLVED: GeoResult = {
    "lat": None,
    "long": None,
    "country_iso": None,
    "country_display_name": "",
    "city_name": "",
    "resolved": False,
    "coordinate_source": "none",
    "source": "unknown",
}

ANONYMITY_UNRESOLVED: AnonymityResult = {
    "labels": [],
    "is_vpn": False,
    "confidence": 0,
    "list_age_days": None,
    "resolved": False,
    "unchecked": list(ALL_LABELS),
    "source": "unknown",
}


def geo_unresolved(source: str) -> GeoResult:
    """An unresolved geo result attributed to ``source``."""
    return {**GEO_UNRESOLVED, "source": source}


def anonymity_unresolved(source: str, unchecked=None) -> AnonymityResult:
    """An unresolved anonymity result attributed to ``source``.

    The list members are rebuilt on every call rather than copied from the
    template. ``{**TEMPLATE}`` is a shallow copy, so the returned ``labels`` and
    ``unchecked`` would be the *same* list objects the template holds: one caller
    appending to a result it was handed would corrupt the default for every later
    lookup in the process, and the symptom would appear far from the cause.
    """
    return {
        **ANONYMITY_UNRESOLVED,
        "labels": [],
        "unchecked": list(ALL_LABELS if unchecked is None else unchecked),
        "source": source,
    }
