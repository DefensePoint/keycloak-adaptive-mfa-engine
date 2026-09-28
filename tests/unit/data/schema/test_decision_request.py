import pytest
from pydantic import ValidationError

from src.data.schema import DecisionRequest
from src.utils.auth.device.screen_resolution_checker import ScreenResolutionChecker


def _valid_kwargs(**overrides) -> dict:
    base = {
        "event_id": "e",
        "group_id": "g",
        "realm_id": "r",
        "user_id": "u",
        "client": "c",
        "ip_address": "1.1.1.1",
        "user_agent": "ua",
        "system_language": "en",
        "screen_resolution": "1920x1080",
        "auth_context_hash": "h",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "value",
    ["1920x1080", "1x1", "99999x99999", "800X600", "640x480"],
)
def test_screen_resolution_accepts_valid_values(value):
    req = DecisionRequest(**_valid_kwargs(screen_resolution=value))
    assert req.screen_resolution == value


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "",
        "1920x",
        "x1080",
        "1920-1080",
        "1920x1080x",
        "1920 x 1080",
        "-1x1",
        "1.5x1080",
        "123456x1080",  # more than 5 digits
        "1920x1080\n",  # trailing newline: `$` alone would let this through,
        # but ScreenResolutionChecker._parse_to_pair still rejects it (the
        # split leaves "1080\n", not all-digit) -- caught by adversarial
        # review; regression test for fullmatch() vs match().
        "1920x1080\r\n",
        "\n1920x1080",
        "1920x1080 ",
        "١٢x1080",  # Arabic-Indic digits: str.isdigit() accepts
        # them but they are not ASCII "digits" in the intended sense.
    ],
)
def test_screen_resolution_rejects_malformed_values(value):
    """A malformed value must be refused at the request boundary (a 422 from
    this schema) rather than reaching the risk evaluation, where it could
    otherwise abort the whole decision or get silently converted into a fixed
    permissive verdict."""
    with pytest.raises(ValidationError) as exc_info:
        DecisionRequest(**_valid_kwargs(screen_resolution=value))
    assert "screen_resolution" in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    ["1920x1080", "1x1", "99999x99999", "800X600", "1920x1080\n", "1920x1080\r\n"],
)
def test_schema_agrees_with_the_parser_on_every_value(value):
    """Regression for a gap found in review: the schema
    must never ACCEPT a value ScreenResolutionChecker would still reject
    (that would silently degrade the signal instead of cleanly refusing the
    request), and must never REJECT a value the parser actually accepts."""
    try:
        DecisionRequest(**_valid_kwargs(screen_resolution=value))
        schema_accepts = True
    except ValidationError:
        schema_accepts = False

    try:
        ScreenResolutionChecker(current_resolution=value)
        parser_accepts = True
    except ValueError:
        parser_accepts = False

    assert schema_accepts == parser_accepts, (
        f"{value!r}: schema_accepts={schema_accepts}, parser_accepts={parser_accepts} -- "
        f"these must always agree"
    )
