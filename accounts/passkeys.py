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

import time
import uuid

import webauthn
from django.utils import timezone
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.exceptions import (InvalidAuthenticationResponse, InvalidJSONStructure,
                                         InvalidRegistrationResponse)
from webauthn.helpers.structs import (AttestationConveyancePreference,
                                      AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                      UserVerificationRequirement)

from .models import Passkey

RP_NAME = "Practice Rota"
SESSION_KEY = "passkey_challenge"
CHALLENGE_TTL = 300          # seconds a minted challenge stays valid
NO_AAGUID = "00000000-0000-0000-0000-000000000000"

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


def registration_options(request, user):
    options = webauthn.generate_registration_options(
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
    try:
        verified = webauthn.verify_registration_response(
            credential=credential, expected_challenge=challenge,
            expected_rp_id=rp_id(request), expected_origin=origin(request),
            require_user_verification=True)
    except (InvalidRegistrationResponse, InvalidJSONStructure) as exc:
        raise PasskeyError(f"The passkey could not be verified ({exc}).")
    aaguid = None if verified.aaguid in (None, NO_AAGUID) else uuid.UUID(verified.aaguid)
    transports = credential.get("response", {}).get("transports") or []
    return Passkey.objects.create(
        user=user,
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=bytes_to_base64url(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=",".join(transports),
        aaguid=aaguid,
        name=(name or "").strip()[:60] or KNOWN_AAGUIDS.get(str(aaguid), "Passkey"),
    )


def login_options(request):
    """No allowCredentials: the authenticator offers whichever discoverable
    key it holds for this RP, so nobody types an email."""
    options = webauthn.generate_authentication_options(
        rp_id=rp_id(request), user_verification=UserVerificationRequirement.REQUIRED)
    _stash(request, options.challenge)
    return options_to_json(options)


def verify_login(request, credential):
    """Verify an assertion; return the Passkey it proves possession of, with
    its counter and last-used time advanced."""
    challenge = _spend(request)
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
    except (InvalidAuthenticationResponse, InvalidJSONStructure) as exc:
        error = PasskeyError(f"The passkey could not be verified ({exc}).")
        error.passkey = passkey
        raise error
    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=["sign_count", "last_used_at"])
    return passkey
