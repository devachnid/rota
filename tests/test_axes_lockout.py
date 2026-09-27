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
def test_fumbles_at_the_surgery_do_not_lock_the_building_out():
    """What makes address keying tolerable at a practice, where everyone
    shares one NAT address. The address counts accounts with outstanding
    failures, and each person's own success clears their own: four people
    fumbling once each, one of them then getting in, leaves the address
    well short of a lockout."""
    _make(4)
    for i in range(4):
        _login(SURGERY, f"gp{i}@example.org", "wrong")

    assert _login(SURGERY, "gp0@example.org", PW).status_code == 302, (
        "four fumbles from the surgery locked the building out"
    )

    for i in range(4):
        _login(SURGERY, f"gp{i}@example.org", "wrong")
    assert _login(SURGERY, "gp1@example.org", PW).status_code == 302, (
        "four people with outstanding fumbles locked the building out"
    )


@pytest.mark.django_db
@axes_on
def test_one_person_fumbling_counts_once_against_the_address():
    """Five wrong passwords lock that account; they do not lock everyone
    else behind the same address."""
    _make(2)
    for _ in range(5):
        _login(SURGERY, "gp0@example.org", "wrong")
    assert _login(SURGERY, "gp0@example.org", PW).status_code == 429
    assert _login(SURGERY, "gp1@example.org", PW).status_code == 302


@pytest.mark.django_db
@axes_on
def test_an_account_holder_cannot_reset_a_colleagues_counter():
    """The hole axes' own reset left: four guesses at a colleague, a login to
    your own account from the same address — which deleted every failure
    recorded there, the colleague's included — and round again, for ever.
    A success now clears only the signed-in person's own failures."""
    insider, victim = _make(2)
    for g in range(4):
        assert _login(ATTACKER, victim.email, f"guess-{g}").status_code == 200
    assert _login(ATTACKER, insider.email, PW).status_code == 302
    # The fifth guess is the fifth failure: the account locks, and the right
    # password is refused too, from anywhere.
    assert _login(ATTACKER, victim.email, "guess-4").status_code == 429
    assert _login(ATTACKER, victim.email, PW).status_code == 429
    assert _login(HOME, victim.email, PW).status_code == 429


@pytest.mark.django_db
@axes_on
def test_a_success_clears_the_signed_in_persons_own_failures_everywhere():
    from axes.models import AccessAttempt
    gp, other = _make(2)
    _login(HOME, gp.email, "wrong")
    _login(SURGERY, gp.email, "wrong")
    _login(SURGERY, other.email, "wrong")
    assert _login(SURGERY, gp.email, PW).status_code == 302
    assert not AccessAttempt.objects.filter(username=gp.email).exists()
    assert AccessAttempt.objects.filter(username=other.email).count() == 1


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
    """AccessAttempt is a counter: the person's own later success clears it.
    AccessFailureLog is the permanent record, and it stays."""
    from axes.models import AccessAttempt, AccessFailureLog
    gp, other = _make(2)
    _login(SURGERY, gp.email, "wrong")
    assert AccessAttempt.objects.filter(username=gp.email).count() == 1
    assert AccessFailureLog.objects.filter(username=gp.email).count() == 1
    assert _login(SURGERY, other.email, PW).status_code == 302     # someone else, same address
    assert AccessAttempt.objects.filter(username=gp.email).count() == 1
    assert _login(SURGERY, gp.email, PW).status_code == 302
    assert not AccessAttempt.objects.filter(username=gp.email).exists()
    assert AccessFailureLog.objects.filter(username=gp.email).count() == 1


@pytest.mark.django_db
@axes_on
def test_a_passkey_sign_in_clears_only_its_own_account(gp_user):
    """A passkey gets past a password lockout by design (possession of the
    device is the stronger proof), but it clears only its own account's
    counter, not the address's."""
    import json
    from axes.models import AccessAttempt
    from tests.soft_authenticator import SoftAuthenticator

    gp = Client()
    gp.force_login(gp_user)
    auth = SoftAuthenticator()
    options = gp.post("/accounts/passkeys/register/options/", data="{}",
                      content_type="application/json").json()
    assert gp.post("/accounts/passkeys/register/",
                   data=json.dumps({"credential": auth.create(options), "name": "phone"}),
                   content_type="application/json").status_code == 200
    victim, *_ = _make(1)
    for g in range(4):
        _login(ATTACKER, victim.email, f"guess-{g}")
    anon = Client()
    options = anon.post("/accounts/passkeys/login/options/", data="{}",
                        content_type="application/json",
                        REMOTE_ADDR=TUNNEL, HTTP_CF_CONNECTING_IP=ATTACKER).json()
    assert anon.post("/accounts/passkeys/login/",
                     data=json.dumps({"credential": auth.get(options)}),
                     content_type="application/json",
                     REMOTE_ADDR=TUNNEL, HTTP_CF_CONNECTING_IP=ATTACKER).status_code == 200
    assert AccessAttempt.objects.get(username=victim.email).failures_since_start == 4


# ----------------------------------------------------------- the lockout ---

@pytest.mark.django_db
@axes_on
def test_attempts_during_a_lockout_do_not_extend_it():
    """axes' default restarted the hour on every attempt made while locked,
    so anyone who knew an address could keep its owner out indefinitely
    with one request an hour. Now the hour runs from the lockout."""
    from datetime import timedelta
    from django.utils import timezone
    from axes.models import AccessAttempt
    gp, *_ = _make(1)
    for _ in range(5):
        _login(ATTACKER, gp.email, "wrong")
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=59))
    assert _login("192.0.2.77", gp.email, "again").status_code == 429
    newest = AccessAttempt.objects.order_by("-attempt_time").first().attempt_time
    assert timezone.now() - newest > timedelta(minutes=58), "the attempt restarted the hour"
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=61))
    assert _login(HOME, gp.email, PW).status_code == 302


@pytest.mark.django_db
@axes_on
def test_the_lockout_page_offers_the_ways_in_that_still_work():
    gp, *_ = _make(1)
    for _ in range(5):
        _login(ATTACKER, gp.email, "wrong")
    resp = _login(HOME, gp.email, PW)
    assert resp.status_code == 429
    html = resp.content.decode()
    assert "Too many attempts" in html
    assert 'href="/accounts/login/"' in html and "passkey" in html
    assert 'href="/accounts/password_reset/"' in html
