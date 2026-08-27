from src.utils.data_processing.user_agent import UserAgentInfo

# Two Chrome desktop UAs that differ only by major version, mimicking a routine
# browser auto-update (150 -> 151) for the same user on the same machine.
_CHROME_150 = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
_CHROME_151 = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def test_browser_signal_family_only_ignores_major_version():
    """Family-only signal is identical across a browser major-version bump."""
    a = UserAgentInfo(_CHROME_150).get_browser_signal(include_version=False)
    b = UserAgentInfo(_CHROME_151).get_browser_signal(include_version=False)
    assert a == b == "Chrome"


def test_browser_signal_with_version_distinguishes_major_version():
    """With version included, the same bump produces a different signal."""
    a = UserAgentInfo(_CHROME_150).get_browser_signal(include_version=True)
    b = UserAgentInfo(_CHROME_151).get_browser_signal(include_version=True)
    assert a == "Chrome|150"
    assert b == "Chrome|151"
    assert a != b


def test_browser_signal_with_version_matches_family_major():
    """include_version=True is exactly the legacy family|major value."""
    ua = UserAgentInfo(_CHROME_150)
    assert ua.get_browser_signal(include_version=True) == ua.get_browser_family_major()


def test_browser_signal_family_only_still_distinguishes_browsers():
    """Family-only must still tell Chrome from Firefox (real signal preserved)."""
    firefox = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) "
        "Gecko/20100101 Firefox/130.0"
    )
    chrome = UserAgentInfo(_CHROME_150).get_browser_signal(include_version=False)
    ff = UserAgentInfo(firefox).get_browser_signal(include_version=False)
    assert chrome == "Chrome"
    assert ff == "Firefox"
    assert chrome != ff
