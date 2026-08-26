"""Resolving the client IP behind the Cloudflare tunnel.

axes rate-limits by address. Behind a tunnel every request arrives from
127.0.0.1, so without this the address is the same for everybody and IP-based
lockout is meaningless — which is why it was username-only before.

The security of the whole arrangement is "which header, and from whom", so
that is what these test.
"""

import pytest
from django.test import RequestFactory, override_settings

from accounts.client_ip import client_ip

REAL = "203.0.113.45"       # what Cloudflare says the client is
TUNNEL = "127.0.0.1"        # where cloudflared connects from
ELSEWHERE = "198.51.100.7"  # some other origin, not a trusted proxy


def _request(remote_addr, **headers):
    return RequestFactory().get("/", REMOTE_ADDR=remote_addr, **headers)


def test_the_forwarded_address_is_used_when_it_comes_from_the_tunnel():
    r = _request(TUNNEL, HTTP_CF_CONNECTING_IP=REAL)
    assert client_ip(r) == REAL


def test_a_forwarded_header_from_anywhere_else_is_ignored():
    """The header is only as trustworthy as the hop that set it. If gunicorn
    is ever reachable directly, believing this would let anyone choose their
    own lockout key and rotate it to evade the limit."""
    r = _request(ELSEWHERE, HTTP_CF_CONNECTING_IP=REAL)
    assert client_ip(r) == ELSEWHERE


def test_x_forwarded_for_is_never_trusted():
    """Cloudflare OVERWRITES CF-Connecting-IP but only APPENDS to
    X-Forwarded-For, so a client that sends its own XFF has the left-most
    entry preserved. Reading it would be attacker-controlled."""
    r = _request(TUNNEL, HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.45")
    assert client_ip(r) == TUNNEL, "X-Forwarded-For must not influence the result"


def test_no_header_falls_back_to_the_peer_address():
    assert client_ip(_request(TUNNEL)) == TUNNEL


@pytest.mark.parametrize("junk", [
    "not-an-ip", "", "   ", "1.2.3.4; DROP TABLE", "999.999.999.999",
    "1.2.3.004",            # ambiguous leading zeros, rejected by Python
    "<script>alert(1)</script>",
    "1.2.3.4, 5.6.7.8",     # a list is XFF's shape, not this header's
])
def test_junk_in_the_header_falls_back_rather_than_being_stored(junk):
    """axes writes this value into a database column, so it must never be
    arbitrary text."""
    r = _request(TUNNEL, HTTP_CF_CONNECTING_IP=junk)
    assert client_ip(r) == TUNNEL


def test_ipv6_is_supported_and_normalised():
    r = _request(TUNNEL, HTTP_CF_CONNECTING_IP="2001:0db8:0000:0000:0000:0000:0000:0001")
    assert client_ip(r) == "2001:db8::1", (
        "an address spelled two ways would count as two lockout keys"
    )


def test_whitespace_is_tolerated():
    r = _request(TUNNEL, HTTP_CF_CONNECTING_IP=f"  {REAL}  ")
    assert client_ip(r) == REAL


@override_settings(TRUSTED_PROXY_IPS=frozenset({"10.0.0.5"}))
def test_the_trusted_set_is_configurable():
    assert client_ip(_request("10.0.0.5", HTTP_CF_CONNECTING_IP=REAL)) == REAL
    assert client_ip(_request(TUNNEL, HTTP_CF_CONNECTING_IP=REAL)) == TUNNEL


def test_axes_is_wired_to_this_resolver():
    """A perfect resolver nothing calls would leave the lockout on
    REMOTE_ADDR, and nothing else would look wrong."""
    from django.conf import settings
    from axes.helpers import get_client_ip_address

    assert settings.AXES_CLIENT_IP_CALLABLE == "accounts.client_ip.client_ip"
    assert "ip_address" in settings.AXES_LOCKOUT_PARAMETERS

    r = _request(TUNNEL, HTTP_CF_CONNECTING_IP=REAL)
    assert get_client_ip_address(r) == REAL, (
        "axes is not resolving through the configured callable"
    )
