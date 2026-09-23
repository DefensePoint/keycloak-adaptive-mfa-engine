import pytest
from src.utils.auth.device.screen_resolution_checker import ScreenResolutionChecker


def test_parse_valid_resolution():
    checker = ScreenResolutionChecker("1920x1080")
    assert checker.current_resolution == (1920, 1080)


def test_parse_valid_resolution_with_capital_x():
    checker = ScreenResolutionChecker("1280X720")
    assert checker.current_resolution == (1280, 720)


def test_parse_invalid_resolution_format():
    try:
        ScreenResolutionChecker("1920-1080")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_parse_invalid_resolution_format():
    try:
        ScreenResolutionChecker("x")
        assert False, "List with diff values! input: x"
    except ValueError:
        pass


def test_parse_non_digit_resolution():
    try:
        ScreenResolutionChecker("1920xHD")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_find_closest_exact_match():
    checker = ScreenResolutionChecker("1920x1080")
    assert checker.find_closest_resolution() == "1920x1080"


def test_find_closest_approximate_match():
    checker = ScreenResolutionChecker("1910x1070")
    assert checker.find_closest_resolution() == "1920x1080"


def test_find_closest_small_resolution():
    checker = ScreenResolutionChecker("250x140")
    assert checker.find_closest_resolution() == "256x144"


def test_find_closest_high_resolution():
    checker = ScreenResolutionChecker("5000x2000")
    assert checker.find_closest_resolution() == "5120x2160"


def test_find_closest_nonstandard_near_hd():
    checker = ScreenResolutionChecker("1300x740")
    assert checker.find_closest_resolution() == "1280x720"


def test_resolution_case_insensitive():
    checker1 = ScreenResolutionChecker("1280x720")
    checker2 = ScreenResolutionChecker("1280X720")
    assert checker1.find_closest_resolution() == checker2.find_closest_resolution()


def test_resolution_with_leading_zeros():
    checker = ScreenResolutionChecker("01280x00720")
    assert checker.current_resolution == (1280, 720)
    assert checker.find_closest_resolution() == "1280x720"
