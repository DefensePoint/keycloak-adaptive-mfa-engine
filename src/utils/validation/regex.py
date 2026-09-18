import re

SHA256_REGEX_HEX = re.compile(r"^[A-Fa-f0-9]{64}$")

# Matches what ScreenResolutionChecker._parse_to_pair accepts: digits, the
# letter x, digits -- e.g. "1920x1080". Digit groups are bounded to 5 chars
# (comfortably covers any real display, including 8K+) to reject pathological
# input rather than just very large numbers.
#
# Must be checked with fullmatch(), not match(): `$` (no re.MULTILINE) matches
# just before a single trailing "\n", so match() alone would accept
# "1920x1080\n" -- which _parse_to_pair then rejects anyway (splitting on "x"
# leaves "1080\n", and "1080\n".isdigit() is False), degrading a signal the
# schema was supposed to have already validated instead of cleanly refusing
# it. re.ASCII keeps `\d` to plain 0-9, matching "digits" precisely rather
# than every Unicode decimal digit str.isdigit()/int() would also accept.
SCREEN_RESOLUTION_REGEX = re.compile(r"^\d{1,5}[xX]\d{1,5}$", re.ASCII)
