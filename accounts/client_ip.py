"""Resolve the real client IP behind the Cloudflare tunnel.

django-axes asks this for every login attempt so it can rate-limit by address.
Without it axes falls back to ``REMOTE_ADDR``, which behind a tunnel is always
``127.0.0.1`` — every clinician in the country shares one key, so an IP-based
lockout would either never fire or lock out the whole practice at once. That is
why ``AXES_LOCKOUT_PARAMETERS`` was username-only until this existed.

**CF-Connecting-IP, not X-Forwarded-For.** The distinction is the whole
security of this module. Cloudflare *overwrites* ``CF-Connecting-IP`` with the
address that actually opened the connection, discarding anything the client
sent under that name. It *appends* to ``X-Forwarded-For``, so a client that
sends its own ``X-Forwarded-For: 1.2.3.4`` gets that value preserved and
Cloudflare's entry added after it — the left-most entry is attacker-controlled,
and an attacker who can choose their own key can evade a lockout by rotating
it.

**And only from the tunnel.** A header is only as trustworthy as the hop that
set it. This trusts ``CF-Connecting-IP`` only when the request arrived from an
address in ``TRUSTED_PROXY_IPS`` — loopback, where cloudflared connects. If
gunicorn is ever exposed directly, the header stops being believed rather than
silently becoming a way to forge an identity. That is the same assumption
``SECURE_PROXY_SSL_HEADER`` already rests on, and the reason the systemd unit
binds to 127.0.0.1.
"""

import ipaddress
from typing import Optional

from django.conf import settings
from django.http import HttpRequest

# Cloudflare sets this and overwrites any client-supplied value.
CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"


def client_ip(request: HttpRequest) -> Optional[str]:
    """The client's address, for axes rate limiting."""
    remote_addr = (request.META.get("REMOTE_ADDR") or "").strip()

    forwarded = request.META.get(CLIENT_IP_HEADER)
    if forwarded and remote_addr in settings.TRUSTED_PROXY_IPS:
        try:
            # Parsing also normalises, so 1.2.3.4 cannot be spelled several
            # ways to get several lockout keys. Python rejects leading zeros
            # and other ambiguous forms outright.
            return str(ipaddress.ip_address(forwarded.strip()))
        except ValueError:
            # Junk in the header is not a reason to fail the login; fall
            # through to the address we can actually see. axes writes this
            # value to the database, so it must not be arbitrary text.
            pass

    return remote_addr or None
