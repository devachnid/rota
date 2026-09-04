"""Login rate limiting, end to end.

axes was keyed on username alone, because behind the Cloudflare tunnel every
request arrives from 127.0.0.1 and an IP key would have been the same for
everyone. `accounts/client_ip.py` resolves the real address, so IP keying now
means something — and Django's own check used to warn about its absence
(axes.W006: "allows attackers to bypass rate limits by rotating User-Agents or
Cookies").

These exercise the real login view so the whole chain is covered: the header,
the resolver, the axes backend and the lockout. Unit tests for the resolver
itself are in test_client_ip.py.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

User = get_user_model()

TUNNEL = "127.0.0.1"      # cloudflared, the only thing that reaches gunicorn
ATTACKER = "203.0.113.99"
SURGERY = "203.0.113.10"
HOME = "198.51.100.20"
PW = "correct-horse-battery-staple"

# axes is off under pytest generally (the login()/force_login() helpers give it
# no request); these switch it on deliberately. The fast hasher keeps a test
# that performs a dozen real logins from dominating the suite.
axes_on = override_settings(
    AXES_ENABLED=True,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)


def _login(ip, email, password):
    return Client().post(
        "/accounts/login/",
        {"username": email, "password": password},
        REMOTE_ADDR=TUNNEL, HTTP_CF_CONNECTING_IP=ip,
    )


def _make(n):
    return [User.objects.create_user(email=f"gp{i}@example.org", password=PW)
            for i in range(n)]


@pytest.mark.django_db
@axes_on
def test_one_address_spraying_many_accounts_is_locked_out():
    """The attack username-only keying cannot see: five failures against five
    *different* accounts leave every username under its own limit."""
    _make(6)
    for i in range(5):
        _login(ATTACKER, f"gp{i}@example.org", "wrong")

    # correct credentials, for an account that has never had a failure
    blocked = _login(ATTACKER, "gp5@example.org", PW)
    assert blocked.status_code != 302, (
        "an address that just sprayed five accounts can still log in"
    )


@pytest.mark.django_db
@axes_on
def test_an_unrelated_address_is_not_caught_by_someone_elses_lockout():
    _make(6)
    for i in range(5):
        _login(ATTACKER, f"gp{i}@example.org", "wrong")

    assert _login(HOME, "gp5@example.org", PW).status_code == 302, (
        "a clinician at home was locked out by an attacker elsewhere"
    )


@pytest.mark.django_db
@axes_on
def test_a_single_account_is_still_locked_after_repeated_failures():
    """The original protection, unchanged by adding the address key."""
    _make(1)
    for _ in range(5):
        _login(HOME, "gp0@example.org", "wrong")

    assert _login(HOME, "gp0@example.org", PW).status_code != 302


@pytest.mark.django_db
@axes_on
def test_a_success_clears_the_counters_for_that_client():
    """What makes address keying tolerable at a practice, where everyone
    shares one NAT address. Ordinary fumbling does not accumulate towards a
    lockout — only an unbroken run of failures does."""
    _make(4)
    for i in range(4):
        _login(SURGERY, f"gp{i}@example.org", "wrong")

    assert _login(SURGERY, "gp0@example.org", PW).status_code == 302, (
        "four fumbles from the surgery locked the building out"
    )

    for i in range(4):
        _login(SURGERY, f"gp{i}@example.org", "wrong")
    assert _login(SURGERY, "gp1@example.org", PW).status_code == 302, (
        "the earlier failures were not cleared by the successful login"
    )


@pytest.mark.django_db
@axes_on
def test_a_spoofed_header_cannot_be_rotated_to_evade_the_limit():
    """The header is only believed from the tunnel. A request arriving from
    anywhere else keeps its real peer address however it decorates itself, so
    rotating the header does not mint fresh lockout keys."""
    _make(6)
    for i in range(5):
        Client().post(
            "/accounts/login/",
            {"username": f"gp{i}@example.org", "password": "wrong"},
            REMOTE_ADDR=ATTACKER,                    # not a trusted proxy
            HTTP_CF_CONNECTING_IP=f"10.0.0.{i}",     # a different lie each time
        )

    blocked = Client().post(
        "/accounts/login/",
        {"username": "gp5@example.org", "password": PW},
        REMOTE_ADDR=ATTACKER, HTTP_CF_CONNECTING_IP="10.0.0.99",
    )
    assert blocked.status_code != 302, (
        "rotating CF-Connecting-IP from an untrusted peer evaded the lockout"
    )


@pytest.mark.django_db
@axes_on
def test_attempts_are_recorded_against_the_email_for_both_ways_in(gp_user):
    """AXES_USERNAME_FORM_FIELD names the key Django's form and the passkey
    view both send; without it every row carried username=None and the
    username half of AXES_LOCKOUT_PARAMETERS never locked anything."""
    import json
    from axes.models import AccessAttempt
    from tests.soft_authenticator import SoftAuthenticator

    _login(HOME, "gp@example.com", "wrong")
    assert list(AccessAttempt.objects.values_list("username", flat=True)) == ["gp@example.com"]
    AccessAttempt.objects.all().delete()

    gp = Client()
    gp.force_login(gp_user)
    auth = SoftAuthenticator()
    options = gp.post("/accounts/passkeys/register/options/", data="{}",
                      content_type="application/json").json()
    assert gp.post("/accounts/passkeys/register/",
                   data=json.dumps({"credential": auth.create(options), "name": "phone"}),
                   content_type="application/json").status_code == 200
    forger = SoftAuthenticator()
    forger.credential_id = auth.credential_id
    anon = Client()
    options = anon.post("/accounts/passkeys/login/options/", data="{}",
                        content_type="application/json",
                        REMOTE_ADDR=TUNNEL, HTTP_CF_CONNECTING_IP=HOME).json()
    resp = anon.post("/accounts/passkeys/login/",
                     data=json.dumps({"credential": forger.get(options)}),
                     content_type="application/json",
                     REMOTE_ADDR=TUNNEL, HTTP_CF_CONNECTING_IP=HOME)
    assert resp.status_code == 400
    assert list(AccessAttempt.objects.values_list("username", flat=True)) == ["gp@example.com"]


@pytest.mark.django_db
@axes_on
def test_the_failure_log_outlives_the_counter_reset():
    """AccessAttempt is a counter: a later successful login from the same
    address clears it (AXES_RESET_ON_SUCCESS), which is what left "Access
    attempts" empty on staging after real failures. AccessFailureLog is the
    permanent record, and it stays."""
    from axes.models import AccessAttempt, AccessFailureLog
    gp, other = _make(2)
    _login(SURGERY, gp.email, "wrong")
    assert AccessAttempt.objects.filter(username=gp.email).count() == 1
    assert AccessFailureLog.objects.filter(username=gp.email).count() == 1
    assert _login(SURGERY, other.email, PW).status_code == 302     # someone else, same address
    assert not AccessAttempt.objects.filter(username=gp.email).exists()
    assert AccessFailureLog.objects.filter(username=gp.email).count() == 1
