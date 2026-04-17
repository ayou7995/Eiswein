"""Cloudflare IP range validation.

Per E3 in docs/STAFF_REVIEW_DECISIONS.md, rate limiting is keyed by the
`CF-Connecting-IP` header. That header can be trivially spoofed if the
request doesn't actually come from Cloudflare, so we validate the raw
transport peer against the known Cloudflare IP ranges before trusting
the header.

Source of truth for CF ranges:
  https://www.cloudflare.com/ips-v4  /  /ips-v6

For portability (CI, dev, tests), the range list is configuration — we
ship the canonical CF prefixes and `Settings.trusted_proxies` can extend
them. Never trust `CF-Connecting-IP` without passing `is_trusted`.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from typing import Iterable, Sequence

# Cloudflare published ranges (verified 2026-04-17). Kept in code so the
# app defaults are secure; deployment can extend via `trusted_proxies`.
_CLOUDFLARE_IPV4: tuple[str, ...] = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
)
_CLOUDFLARE_IPV6: tuple[str, ...] = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)


def _parse_ranges(ranges: Iterable[str]) -> tuple[list[IPv4Network], list[IPv6Network]]:
    v4: list[IPv4Network] = []
    v6: list[IPv6Network] = []
    for r in ranges:
        net = ip_network(r, strict=False)
        if isinstance(net, IPv4Network):
            v4.append(net)
        else:
            v6.append(net)
    return v4, v6


def cloudflare_networks(extra: Sequence[str] = ()) -> tuple[list[IPv4Network], list[IPv6Network]]:
    return _parse_ranges((*_CLOUDFLARE_IPV4, *_CLOUDFLARE_IPV6, *extra))


def is_trusted(
    client_ip: str,
    *,
    v4_nets: Sequence[IPv4Network],
    v6_nets: Sequence[IPv6Network],
) -> bool:
    try:
        parsed = ip_address(client_ip)
    except ValueError:
        return False
    if isinstance(parsed, IPv4Address):
        return any(parsed in net for net in v4_nets)
    if isinstance(parsed, IPv6Address):
        return any(parsed in net for net in v6_nets)
    return False
