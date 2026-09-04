"""accounts/passkeys.py against py_webauthn, driven by a software
authenticator that mints real responses (tests/soft_authenticator.py) —
so every test here runs the real verification path."""

import json
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware

from accounts import passkeys
from accounts.models import Passkey
from tests.soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db
ICLOUD = "fbfc3007-154e-4ecc-8c0b-6e020557d7bd"


@pytest.fixture
def request_for(rf):
    """A request with a session — the challenge lives there."""
    def make(user=None):
        request = rf.post("/accounts/passkeys/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = user or AnonymousUser()
        return request
    return make


def _register(request, user, auth, name=""):
    options = passkeys.registration_options(request, user)
    return passkeys.complete_registration(request, user, auth.create(options), name)


def test_registration_options_name_this_site_and_demand_a_discoverable_verified_key(request_for, gp_user):
    request = request_for(gp_user)
    options = json.loads(passkeys.registration_options(request, gp_user))
    assert options["rp"] == {"id": "testserver", "name": "Practice Rota"}
    assert options["user"]["name"] == "gp@example.com"
    assert options["authenticatorSelection"]["residentKey"] == "required"
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["attestation"] == "none"
    assert request.session[passkeys.SESSION_KEY][0] == options["challenge"]


def test_a_registration_round_trip_stores_the_credential_and_spends_the_challenge(request_for, gp_user):
    request = request_for(gp_user)
    auth = SoftAuthenticator(aaguid=uuid.UUID(ICLOUD).bytes)
    passkey = _register(request, gp_user, auth, name="my iPhone")
    assert passkey.user == gp_user and passkey.name == "my iPhone"
    assert passkey.credential_id == auth.id
    assert passkey.sign_count == 0 and passkey.transports == "internal"
    assert passkey.aaguid == uuid.UUID(ICLOUD) and passkey.last_used_at is None
    assert passkeys.SESSION_KEY not in request.session


def test_the_name_falls_back_to_the_authenticator_then_to_passkey(request_for, gp_user):
    known = _register(request_for(gp_user), gp_user, SoftAuthenticator(aaguid=uuid.UUID(ICLOUD).bytes))
    assert known.name == "iCloud Keychain"
    unknown = _register(request_for(gp_user), gp_user, SoftAuthenticator(aaguid=uuid.uuid4().bytes), name="   ")
    assert unknown.name == "Passkey"
    none = _register(request_for(gp_user), gp_user, SoftAuthenticator())
    assert none.name == "Passkey" and none.aaguid is None


def test_a_typed_name_is_trimmed_and_capped(request_for, gp_user):
    passkey = _register(request_for(gp_user), gp_user, SoftAuthenticator(), name="  " + "x" * 80)
    assert passkey.name == "x" * 60


def test_existing_passkeys_are_excluded_from_a_new_registration(request_for, gp_user):
    first = _register(request_for(gp_user), gp_user, SoftAuthenticator())
    options = json.loads(passkeys.registration_options(request_for(gp_user), gp_user))
    assert [c["id"] for c in options["excludeCredentials"]] == [first.credential_id]


def test_a_challenge_is_single_use(request_for, gp_user):
    request = request_for(gp_user)
    options = passkeys.registration_options(request, gp_user)
    passkeys.complete_registration(request, gp_user, SoftAuthenticator().create(options), "")
    with pytest.raises(passkeys.PasskeyError, match="Start again"):
        passkeys.complete_registration(request, gp_user, SoftAuthenticator().create(options), "")
    assert Passkey.objects.count() == 1


def test_a_stale_challenge_is_refused(request_for, gp_user):
    request = request_for(gp_user)
    options = passkeys.registration_options(request, gp_user)
    request.session[passkeys.SESSION_KEY][1] -= passkeys.CHALLENGE_TTL + 1
    with pytest.raises(passkeys.PasskeyError, match="too long"):
        passkeys.complete_registration(request, gp_user, SoftAuthenticator().create(options), "")
    assert passkeys.SESSION_KEY not in request.session


def test_a_response_for_another_origin_is_refused(request_for, gp_user):
    request = request_for(gp_user)
    options = passkeys.registration_options(request, gp_user)
    with pytest.raises(passkeys.PasskeyError, match="could not be verified"):
        passkeys.complete_registration(
            request, gp_user, SoftAuthenticator(origin="https://evil.example").create(options), "")
    assert Passkey.objects.count() == 0


def test_a_registration_without_user_verification_is_refused(request_for, gp_user):
    request = request_for(gp_user)
    options = passkeys.registration_options(request, gp_user)
    with pytest.raises(passkeys.PasskeyError, match="could not be verified"):
        passkeys.complete_registration(
            request, gp_user, SoftAuthenticator(user_verified=False).create(options), "")


def test_a_login_round_trip_finds_the_account_and_advances_the_counter(request_for, gp_user):
    auth = SoftAuthenticator()
    stored = _register(request_for(gp_user), gp_user, auth)
    request = request_for()
    options = json.loads(passkeys.login_options(request))
    assert options["rpId"] == "testserver" and options["allowCredentials"] == []
    assert options["userVerification"] == "required"
    passkey = passkeys.verify_login(request, auth.get(options))
    assert passkey == stored and passkey.user == gp_user
    passkey.refresh_from_db()
    assert passkey.sign_count == 1 and passkey.last_used_at is not None
    assert passkeys.SESSION_KEY not in request.session


def test_an_unknown_credential_is_refused_and_names_nobody(request_for, gp_user):
    _register(request_for(gp_user), gp_user, SoftAuthenticator())
    request = request_for()
    options = passkeys.login_options(request)
    with pytest.raises(passkeys.PasskeyError, match="not registered") as caught:
        passkeys.verify_login(request, SoftAuthenticator().get(options))
    assert not hasattr(caught.value, "passkey")


def test_a_forged_signature_for_a_known_credential_is_refused_and_names_the_key(request_for, gp_user):
    auth = SoftAuthenticator()
    stored = _register(request_for(gp_user), gp_user, auth)
    forger = SoftAuthenticator()
    forger.credential_id = auth.credential_id
    request = request_for()
    options = passkeys.login_options(request)
    with pytest.raises(passkeys.PasskeyError, match="could not be verified") as caught:
        passkeys.verify_login(request, forger.get(options))
    assert caught.value.passkey == stored
    stored.refresh_from_db()
    assert stored.sign_count == 0 and stored.last_used_at is None


def test_a_replayed_sign_count_is_refused(request_for, gp_user):
    auth = SoftAuthenticator()
    _register(request_for(gp_user), gp_user, auth)
    first = request_for()
    passkeys.verify_login(first, auth.get(passkeys.login_options(first)))        # stored count → 1
    second = request_for()
    options = passkeys.login_options(second)
    with pytest.raises(passkeys.PasskeyError, match="could not be verified"):
        passkeys.verify_login(second, auth.get(options, sign_count=1))


def test_an_assertion_without_user_verification_is_refused(request_for, gp_user):
    auth = SoftAuthenticator()
    _register(request_for(gp_user), gp_user, auth)
    request = request_for()
    options = passkeys.login_options(request)
    auth.user_verified = False
    with pytest.raises(passkeys.PasskeyError, match="could not be verified"):
        passkeys.verify_login(request, auth.get(options))


def test_a_login_with_no_challenge_in_the_session_is_refused(request_for, gp_user):
    auth = SoftAuthenticator()
    _register(request_for(gp_user), gp_user, auth)
    with pytest.raises(passkeys.PasskeyError, match="Start again"):
        passkeys.verify_login(request_for(), auth.get({"challenge": "AAAA", "rpId": "testserver"}))


def test_the_known_aaguid_table_is_uuids_to_names():
    for key, name in passkeys.KNOWN_AAGUIDS.items():
        assert str(uuid.UUID(key)) == key and name
