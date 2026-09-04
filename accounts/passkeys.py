"""Passkeys (WebAuthn): the parts that talk to py_webauthn, and nothing
that talks to a request's body or a response. Views call these; tests
drive them with a software authenticator (tests/soft_authenticator.py)
that mints real responses, so the real verification path runs in every
test.

One challenge at a time lives in the session, spent on first use whether
the response was good or bad. The RP id is the request's host, which is
what binds every passkey to the domain the app is served from — move the
app and every passkey is re-enrolled.
"""

import logging
import time
import uuid

import webauthn
from django.db import IntegrityError, transaction
from django.utils import timezone
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (AttestationConveyancePreference,
                                      AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                      UserVerificationRequirement)

from .models import Passkey

logger = logging.getLogger(__name__)

RP_NAME = "Practice Rota"
SESSION_KEY = "passkey_challenge"
CHALLENGE_TTL = 300          # seconds a minted challenge stays valid
NO_AAGUID = "00000000-0000-0000-0000-000000000000"

# What the library can raise on attacker-chosen bytes. WebAuthnException is
# its own base; the three builtins come from its unguarded parsing of a
# malformed COSE key or attestation object — inside these two calls only,
# so a builtin error is the library's parse failing on the browser's
# bytes, never ours.
LIBRARY_ERRORS = (WebAuthnException, KeyError, TypeError, ValueError)

# Authenticators a person would recognise by name, keyed by AAGUID. From
# the community list at github.com/passkeydeveloper/passkey-authenticator-
# aaguids; a wrong or missing entry only costs the fallback name.
KNOWN_AAGUIDS = {
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
    "fdb141b2-5d84-443e-8a35-4698c205a502": "KeePassXC",
    "50726f74-6f6e-5061-7373-50726f746f6e": "Proton Pass",
}


class PasskeyError(Exception):
    """Something the browser sent that we will not accept. The message is
    safe to show. verify_login sets `.passkey` when the credential was
    known, so the caller can count the failure against that account."""


def rp_id(request):
    return request.get_host().split(":")[0]


def origin(request):
    return f"{request.scheme}://{request.get_host()}"


def _stash(request, challenge):
    request.session[SESSION_KEY] = [bytes_to_base64url(challenge), int(time.time())]


def _spend(request):
    """The challenge minted for this session, once."""
    stored = request.session.pop(SESSION_KEY, None)
    if not stored:
        raise PasskeyError("Start again — no passkey request is in progress.")
    challenge, issued = stored
    if time.time() - issued > CHALLENGE_TTL:
        raise PasskeyError("That took too long — start again.")
    return base64url_to_bytes(challenge)


def _could_not_verify(exc):
    """The library refused the browser's bytes — or, if it raised a builtin,
    tripped over them. The second case gets a line in the journal: it is a
    hostile payload or a library change, and neither should hide behind a
    friendly 400."""
    if not isinstance(exc, WebAuthnException):
        logger.warning("passkey verification raised %s", exc.__class__.__name__, exc_info=True)
    return PasskeyError(f"The passkey could not be verified ({exc.__class__.__name__}: {exc}).")


def registration_options(request, user):
    options = webauthn.generate_registration_options(
        timeout=CHALLENGE_TTL * 1000,      # the browser's own abort, matched to ours
        rp_id=rp_id(request), rp_name=RP_NAME,
        user_id=str(user.pk).encode(), user_name=user.email,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id))
                             for p in user.passkeys.all()],
    )
    _stash(request, options.challenge)
    return options_to_json(options)


def complete_registration(request, user, credential, name):
    """Verify the browser's registration response and keep it."""
    challenge = _spend(request)
    if not isinstance(credential, dict):
        raise PasskeyError("Malformed request.")
    try:
        verified = webauthn.verify_registration_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=rp_id(request), expected_origin=origin(request),
            require_user_verification=True)
    except LIBRARY_ERRORS as exc:
        raise _could_not_verify(exc)
    # WebAuthn caps a credential id at 1023 bytes; the library reads a
    # 2-byte length and SQLite ignores max_length, so refuse it here.
    if len(verified.credential_id) > 1023:
        raise PasskeyError("The passkey could not be verified (credential id too long).")
    aaguid = None if verified.aaguid in (None, NO_AAGUID) else uuid.UUID(verified.aaguid)
    # The library validates everything it verifies; transports it merely
    # echoes, so filter the browser's list ourselves. A bare string is
    # iterable too (and every character passes isinstance(t, str)), so the
    # container itself must be checked, not just its elements.
    raw_transports = credential.get("response", {}).get("transports")
    transports = [t for t in raw_transports if isinstance(t, str)] if isinstance(raw_transports, list) else []
    try:
        # A savepoint, so a refused insert does not poison the caller's
        # transaction (Django's documented way to catch IntegrityError).
        with transaction.atomic():
            return Passkey.objects.create(
                user=user,
                credential_id=bytes_to_base64url(verified.credential_id),
                public_key=bytes_to_base64url(verified.credential_public_key),
                sign_count=verified.sign_count,
                transports=",".join(transports)[:200],
                aaguid=aaguid,
                name=(name or "").strip()[:60] or KNOWN_AAGUIDS.get(str(aaguid), "Passkey"),
            )
    except IntegrityError:
        # excludeCredentials is only a hint to the browser.
        raise PasskeyError("That passkey is already registered here.")


def login_options(request):
    """No allowCredentials: the authenticator offers whichever discoverable
    key it holds for this RP, so nobody types an email."""
    options = webauthn.generate_authentication_options(
        timeout=CHALLENGE_TTL * 1000,
        rp_id=rp_id(request), user_verification=UserVerificationRequirement.REQUIRED)
    _stash(request, options.challenge)
    return options_to_json(options)


def verify_login(request, credential):
    """Verify an assertion; return the Passkey it proves possession of, with
    its counter and last-used time advanced."""
    challenge = _spend(request)
    if not isinstance(credential, dict):
        raise PasskeyError("Malformed request.")
    passkey = Passkey.objects.select_related("user").filter(credential_id=credential.get("id")).first()
    if passkey is None:
        raise PasskeyError("That passkey is not registered here.")
    try:
        verified = webauthn.verify_authentication_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=rp_id(request), expected_origin=origin(request),
            credential_public_key=base64url_to_bytes(passkey.public_key),
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True)
    except LIBRARY_ERRORS as exc:
        error = _could_not_verify(exc)
        error.passkey = passkey
        raise error
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey
