"""A software authenticator: mints real WebAuthn registration and
assertion responses for py_webauthn to verify, so tests exercise the whole
path — options → browser → verify → row — with no browser. The byte layouts
are WebAuthn's (authenticator data, a COSE EC2 P-256 key, "none"
attestation); signatures are real ES256 over authData || sha256(clientData).
Not a test file: pytest collects test_*.py only."""

import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

UP, UV, AT = 0x01, 0x04, 0x40   # user present, user verified, attested credential data


class SoftAuthenticator:
    def __init__(self, origin="http://testserver", aaguid=bytes(16), user_verified=True):
        self.origin = origin
        self.aaguid = aaguid
        self.user_verified = user_verified
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = secrets.token_bytes(16)
        self.sign_count = 0

    @property
    def id(self):
        return bytes_to_base64url(self.credential_id)

    def _cose_key(self):
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1,
                            -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def _auth_data(self, rp_id, attested):
        flags = UP | (UV if self.user_verified else 0) | (AT if attested else 0)
        data = (hashlib.sha256(rp_id.encode()).digest() + bytes([flags])
                + self.sign_count.to_bytes(4, "big"))
        if attested:
            data += (self.aaguid + len(self.credential_id).to_bytes(2, "big")
                     + self.credential_id + self._cose_key())
        return data

    def _client_data(self, kind, challenge):
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin}).encode()

    def create(self, options):
        """navigator.credentials.create(), as credential.toJSON() would give it."""
        if isinstance(options, str):
            options = json.loads(options)
        client_data = self._client_data("webauthn.create", options["challenge"])
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {},
                                   "authData": self._auth_data(options["rp"]["id"], attested=True)})
        return {"id": self.id, "rawId": self.id, "type": "public-key",
                "authenticatorAttachment": "platform", "clientExtensionResults": {},
                "response": {"clientDataJSON": bytes_to_base64url(client_data),
                             "attestationObject": bytes_to_base64url(attestation),
                             "transports": ["internal"]}}

    def get(self, options, user_handle=b"", sign_count=None):
        """navigator.credentials.get(). sign_count overrides the counter, to
        replay a stale one."""
        if isinstance(options, str):
            options = json.loads(options)
        self.sign_count = self.sign_count + 1 if sign_count is None else sign_count
        client_data = self._client_data("webauthn.get", options["challenge"])
        auth_data = self._auth_data(options["rpId"], attested=False)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(),
                                  ec.ECDSA(hashes.SHA256()))
        response = {"clientDataJSON": bytes_to_base64url(client_data),
                    "authenticatorData": bytes_to_base64url(auth_data),
                    "signature": bytes_to_base64url(signature)}
        if user_handle:
            response["userHandle"] = bytes_to_base64url(user_handle)
        return {"id": self.id, "rawId": self.id, "type": "public-key",
                "clientExtensionResults": {}, "response": response}
