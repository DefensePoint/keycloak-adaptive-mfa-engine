"""Matching an OS allow or deny list entry against the OS a login reports.

The login's OS is the user-agent parser's family name, while an admin types what
they call the system. Each case below is an entry an admin could reasonably type,
measured against the family the engine derives for a real browser.
"""

import pytest

from src.utils.data_processing.os_family import os_list_matches


@pytest.mark.parametrize(
    "entry, family",
    [
        ("Windows", "Windows"),
        ("windows", "Windows"),
        ("  WINDOWS ", "Windows"),
        ("Windows 10", "Windows"),
        ("Windows 11", "Windows"),
        ("Mac OS X", "Mac OS X"),
        ("macOS", "Mac OS X"),
        ("Mac OS", "Mac OS X"),
        ("OS X", "Mac OS X"),
        ("macos", "Mac OS"),
        ("iOS", "iOS"),
        ("iPadOS", "iOS"),
        ("Android", "Android"),
        ("ChromeOS", "Chrome OS"),
        ("Chrome  OS", "Chrome OS"),
        ("Ubuntu", "Ubuntu"),
        ("Linux", "Linux"),
    ],
)
def test_an_entry_matches_the_os_it_names(entry, family):
    assert os_list_matches([entry], family)


@pytest.mark.parametrize(
    "family",
    ["Ubuntu", "Kubuntu", "Fedora", "Debian", "Red Hat", "CentOS", "Linux Mint",
     "Arch Linux", "openSUSE", "Gentoo"],
)
def test_a_linux_entry_covers_the_distributions_browsers_report(family):
    """Firefox on Ubuntu reports Ubuntu, not Linux."""
    assert os_list_matches(["Linux"], family)


@pytest.mark.parametrize("family", ["Android", "Chrome OS", "FreeBSD", "Mac OS X"])
def test_a_linux_entry_does_not_cover_systems_admins_name_separately(family):
    assert not os_list_matches(["Linux"], family)


@pytest.mark.parametrize(
    "entry, family",
    [
        ("Windows", "Windows Phone"),
        ("Windows", "Windows Mobile"),
        ("Mac OS X", "iOS"),
        ("iOS", "Mac OS X"),
        ("Ubuntu", "Fedora"),
        ("Ubuntu", "Linux"),
        ("Android", "Linux"),
    ],
)
def test_an_entry_does_not_match_a_different_os(entry, family):
    assert not os_list_matches([entry], family)


def test_any_entry_of_the_list_can_match():
    assert os_list_matches(["Android", "macOS"], "Mac OS X")


@pytest.mark.parametrize("entries", [None, [], [""], ["   "], [None]])
def test_an_empty_list_or_entry_matches_nothing(entries):
    assert not os_list_matches(entries, "Windows")


@pytest.mark.parametrize("family", [None, ""])
def test_a_login_without_an_os_matches_nothing(family):
    assert not os_list_matches(["Windows", "Linux"], family)
