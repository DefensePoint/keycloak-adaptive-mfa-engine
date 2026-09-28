"""`DecisionService._bucket_screen_resolution` in isolation.

The
request schema (`DecisionRequest.validate_screen_resolution`) rejects a
malformed value before it ever reaches this method, so this is defense in
depth for any other path that could still produce one: a value the parser
cannot classify must degrade only this one signal (fall back to the raw
value, unbucketed) rather than raise and abort the whole evaluation.

A staticmethod with no I/O, so it is tested directly rather than through the
full `__process_decision` flow (which needs a real DB/Redis session) -- the
same reasoning `_adjust_for_credibility` documents for itself.
"""

import logging

from src.service.decision import DecisionService


def test_bucket_screen_resolution_classifies_a_valid_value():
    result = DecisionService._bucket_screen_resolution("1920x1080", "user-1")
    assert result  # some known bucket string, not necessarily "1920x1080" itself
    assert "x" in result


def test_bucket_screen_resolution_degrades_gracefully_on_malformed_input(caplog):
    """A value the parser cannot interpret must not raise -- it degrades only
    this one signal (falls back to the raw value) rather than the caller
    having to catch anything."""
    with caplog.at_level(logging.WARNING):
        result = DecisionService._bucket_screen_resolution("not-a-resolution", "user-1")

    assert result == "not-a-resolution"
    assert any(
        "user-1" in record.getMessage() and "not-a-resolution" in record.getMessage()
        for record in caplog.records
    ), "expected a warning naming the user and the unclassifiable value"


def test_bucket_screen_resolution_degrades_gracefully_on_empty_string():
    result = DecisionService._bucket_screen_resolution("", "user-1")
    assert result == ""
