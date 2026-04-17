"""Cloudflare IP range validation."""

from __future__ import annotations

from app.security.cf_ip_validation import cloudflare_networks, is_trusted


def test_known_cf_ipv4_trusted() -> None:
    v4, v6 = cloudflare_networks()
    assert is_trusted("173.245.48.1", v4_nets=v4, v6_nets=v6) is True


def test_non_cf_address_rejected() -> None:
    v4, v6 = cloudflare_networks()
    assert is_trusted("8.8.8.8", v4_nets=v4, v6_nets=v6) is False


def test_invalid_address_rejected() -> None:
    v4, v6 = cloudflare_networks()
    assert is_trusted("not-an-ip", v4_nets=v4, v6_nets=v6) is False


def test_extra_trusted_includes_localhost() -> None:
    v4, v6 = cloudflare_networks(extra=["127.0.0.1/32"])
    assert is_trusted("127.0.0.1", v4_nets=v4, v6_nets=v6) is True


def test_ipv6_cf_trusted() -> None:
    v4, v6 = cloudflare_networks()
    assert is_trusted("2400:cb00::1", v4_nets=v4, v6_nets=v6) is True
