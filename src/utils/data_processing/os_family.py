"""Matching an OS allow or deny list entry against the OS a login reports.

A login's OS is the user-agent parser's family name: Windows, Mac OS X, Linux,
Ubuntu, Android, iOS, Chrome OS and so on. An admin types what they call the system,
and an exact comparison silently missed the obvious spellings: "macOS" never
matched Mac OS X, "windows" never matched Windows, and a "Linux" entry missed every
browser that names its distribution (Firefox on Ubuntu reports Ubuntu). A deny list
that matches nothing leaves the admin believing a control is active when it is not.

So entries compare without regard to case or spacing, the names people commonly
use map to the parser's, and a Linux entry also covers the Linux distributions the
parser can report. Android and Chrome OS are not covered by it: admins treat those
as systems of their own.
"""

from typing import Iterable

# What people call a system -> the parser's family name, both normalised.
_ALIASES = {
    "macos": "mac os x",
    "mac os": "mac os x",
    "os x": "mac os x",
    "osx": "mac os x",
    "windows 10": "windows",
    "windows 11": "windows",
    "ipados": "ios",
    "chromeos": "chrome os",
}

# Families the parser reports for desktop Linux distributions (ua-parser's OS
# patterns), normalised.
_LINUX_DISTRIBUTIONS = {
    "ubuntu",
    "kubuntu",
    "lubuntu",
    "linux mint",
    "fedora",
    "red hat",
    "centos",
    "debian",
    "gentoo",
    "slackware",
    "opensuse",
    "suse",
    "arch linux",
    "mageia",
    "pclinuxos",
    "puppy",
    "backtrack",
}


def _canonical(name) -> str:
    normalised = " ".join(str(name).split()).casefold() if name else ""
    return _ALIASES.get(normalised, normalised)


def _matches(entry: str, family: str) -> bool:
    if entry == family:
        return True
    return entry == "linux" and family in _LINUX_DISTRIBUTIONS


def os_list_matches(entries: Iterable | None, os_family) -> bool:
    """Whether any list entry names the OS family a login reports."""
    family = _canonical(os_family)
    return any(
        _matches(entry, family)
        for entry in (_canonical(e) for e in (entries or ()))
        if entry
    )
