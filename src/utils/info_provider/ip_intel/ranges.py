"""Membership tests over large CIDR lists.

The anonymiser lists are big: the datacenter list alone is ~42,000 CIDRs covering
roughly 8.7% of IPv4. A linear scan per login would be far too slow, and pulling
in a trie library for this would be a dependency for no reason, so the lists are
flattened into sorted integer ranges and searched with ``bisect``. Lookup is
O(log n) against stdlib only.

IPv4 and IPv6 are kept in **separate** tables rather than one unified integer
space. Mixing them makes it impossible to answer "was this address family
actually covered by this list", and that question matters: the Tor and VPN lists
are IPv4-only, so for an IPv6 client only the ASN-backed check can answer. Being
able to report an IPv6 address as *unchecked* rather than *clean* is the whole
point, and a merged table would silently report the latter.
"""

import bisect
import ipaddress


class _VersionTable:
    """Merged, sorted ranges for one address family."""

    __slots__ = ("_starts", "_ends")

    def __init__(self, ranges: list[tuple[int, int]]):
        merged: list[list[int]] = []
        for start, end in sorted(ranges):
            # Adjacent ranges are merged too (start == previous_end + 1), which
            # matters because these lists are full of consecutive /24s.
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        self._starts = [pair[0] for pair in merged]
        self._ends = [pair[1] for pair in merged]

    def __len__(self) -> int:
        return len(self._starts)

    def contains(self, value: int) -> bool:
        index = bisect.bisect_right(self._starts, value) - 1
        return index >= 0 and value <= self._ends[index]


class IpRangeIndex:
    """CIDR membership for one labelled list, per address family."""

    __slots__ = ("_tables",)

    def __init__(self, tables: dict[int, _VersionTable]):
        self._tables = tables

    @classmethod
    def from_lines(cls, lines) -> "IpRangeIndex":
        """Parse CIDRs or bare addresses, one per line.

        Blank lines, comments and unparseable entries are skipped rather than
        raising: these are third-party files refreshed on someone else's
        schedule, and one malformed row must not cost us the whole list.
        """
        collected: dict[int, list[tuple[int, int]]] = {4: [], 6: []}

        for raw in lines:
            entry = raw.strip()
            if not entry or entry.startswith("#"):
                continue
            # Some feeds ship "cidr,country,city" rows; take the first field.
            entry = entry.split(",", 1)[0].strip()
            try:
                network = ipaddress.ip_network(entry, strict=False)
            except ValueError:
                continue
            collected[network.version].append(
                (int(network.network_address), int(network.broadcast_address))
            )

        return cls(
            {
                version: _VersionTable(ranges)
                for version, ranges in collected.items()
                if ranges
            }
        )

    def covers_version(self, version: int) -> bool:
        """Whether this list has any data for the given address family.

        Distinguishing "no match" from "nothing to match against" depends on this.
        """
        return version in self._tables

    def contains(self, address) -> bool:
        table = self._tables.get(address.version)
        if table is None:
            return False
        return table.contains(int(address))

    def size(self, version: int) -> int:
        table = self._tables.get(version)
        return len(table) if table else 0
