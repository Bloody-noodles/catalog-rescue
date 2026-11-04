import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from api.auth import OIDCSettings, VerifiedIdentity, get_authenticated_identity


ISSUER = "https://issuer.example/"
AUDIENCE = "https://catalog-rescue.example/api"
JWKS_URL = f"{ISSUER}.well-known/jwks.json"


class FakeJwksClient:
    def __init__(self, keys):
        self.keys = keys

    def get_signing_key_from_jwt(self, token):
        key_id = jwt.get_unverified_header(token)["kid"]
        key = self.keys.get(key_id)
        if key is None:
            raise PyJWKClientError("The signing key was not found.")
        return SimpleNamespace(key=key)


class OIDCAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.settings = patch.dict(
            "os.environ",
            {
                "AUTH0_ISSUER": ISSUER,
                "AUTH0_AUDIENCE": AUDIENCE,
                "AUTH0_JWKS_URL": JWKS_URL,
                "CATALOG_RESCUE_REQUIRED_SCOPE": "catalog:access",
            },
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.jwks = FakeJwksClient(
            {
                "current": self.private_key.public_key(),
                "other": self.other_private_key.public_key(),
            }
        )
        self.jwks_patch = patch("api.auth._jwks_client", return_value=self.jwks)
        self.jwks_patch.start()
        self.addCleanup(self.jwks_patch.stop)

    def make_token(self, **overrides):
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "auth0|catalog-user",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "scope": "catalog:access",
            "email": "user@example.com",
            "email_verified": True,
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "current"},
        )

    def authenticate(self, token):
        return get_authenticated_identity(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    def test_valid_token_returns_verified_identity(self):
        identity = self.authenticate(self.make_token())
        self.assertEqual(identity, VerifiedIdentity(ISSUER, "auth0|catalog-user", "user@example.com"))

    def test_invalid_claims_and_signature_are_rejected(self):
        invalid_tokens = {
            "issuer": self.make_token(iss="https://attacker.example/"),
            "audience": self.make_token(aud="other-api"),
            "expired": self.make_token(exp=int(time.time()) - 1),
            "not-yet-valid": self.make_token(nbf=int(time.time()) + 60),
            "signature": jwt.encode(
                {
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "sub": "auth0|catalog-user",
                    "exp": int(time.time()) + 300,
                    "scope": "catalog:access",
                },
                self.other_private_key,
                algorithm="RS256",
                headers={"kid": "current"},
            ),
            "algorithm": jwt.encode(
                {
                    "iss": ISSUER,
                    "aud": AUDIENCE,
                    "sub": "auth0|catalog-user",
                    "exp": int(time.time()) + 300,
                    "scope": "catalog:access",
                },
                "x" * 32,
                algorithm="HS256",
                headers={"kid": "current"},
            ),
        }
        for label, token in invalid_tokens.items():
            with self.subTest(label=label), self.assertRaises(HTTPException) as raised:
                self.authenticate(token)
            self.assertEqual(raised.exception.status_code, 401)

    def test_malformed_token_missing_claims_and_unknown_key_are_rejected(self):
        base_claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "auth0|catalog-user",
            "exp": int(time.time()) + 300,
            "scope": "catalog:access",
        }
        unknown_key = jwt.encode(
            {
                "iss": ISSUER,
                "aud": AUDIENCE,
                "sub": "auth0|catalog-user",
                "exp": int(time.time()) + 300,
                "scope": "catalog:access",
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": "unknown"},
        )
        invalid_tokens = [("malformed", "not-a-jwt"), ("unknown-kid", unknown_key)]
        for claim in ("exp", "iss", "aud", "sub"):
            claims = dict(base_claims)
            del claims[claim]
            invalid_tokens.append(
                (
                    f"missing-{claim}",
                    jwt.encode(
                        claims,
                        self.private_key,
                        algorithm="RS256",
                        headers={"kid": "current"},
                    ),
                )
            )

        for label, token in invalid_tokens:
            with self.subTest(label=label), self.assertRaises(HTTPException) as raised:
                self.authenticate(token)
            self.assertEqual(raised.exception.status_code, 401)

    def test_missing_scope_is_forbidden(self):
        with self.assertRaises(HTTPException) as raised:
            self.authenticate(self.make_token(scope="profile:read"))
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(
            raised.exception.headers["WWW-Authenticate"],
            'Bearer error="insufficient_scope", scope="catalog:access"',
        )

    def test_missing_bearer_token_is_unauthorized(self):
        with self.assertRaises(HTTPException) as raised:
            get_authenticated_identity(None)
        self.assertEqual(raised.exception.status_code, 401)

    def test_missing_configuration_fails_closed(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as raised:
                get_authenticated_identity(
                    HTTPAuthorizationCredentials(
                        scheme="Bearer",
                        credentials=self.make_token(),
                    )
                )
        self.assertEqual(raised.exception.status_code, 503)

    def test_jwks_network_and_timeout_fail_closed(self):
        failures = (
            PyJWKClientConnectionError("connection refused"),
            PyJWKClientConnectionError("request timed out"),
        )
        for failure in failures:
            with self.subTest(failure=str(failure)):
                client = SimpleNamespace(
                    get_signing_key_from_jwt=lambda _token, exc=failure: (_ for _ in ()).throw(exc)
                )
                with patch("api.auth._jwks_client", return_value=client):
                    with self.assertRaises(HTTPException) as raised:
                        self.authenticate(self.make_token())
                self.assertEqual(raised.exception.status_code, 503)

    def test_jwks_unknown_kid_refreshes_for_key_rotation(self):
        first_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        second_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        first_jwk = json.loads(RSAAlgorithm.to_jwk(first_private_key.public_key()))
        second_jwk = json.loads(RSAAlgorithm.to_jwk(second_private_key.public_key()))
        first_jwk.update({"kid": "first", "use": "sig", "alg": "RS256"})
        second_jwk.update({"kid": "second", "use": "sig", "alg": "RS256"})
        client = PyJWKClient(JWKS_URL, cache_keys=True)
        with patch.object(
            client,
            "fetch_data",
            side_effect=[{"keys": [first_jwk]}, {"keys": [first_jwk, second_jwk]}],
        ) as fetch:
            first_token = jwt.encode(
                {"sub": "one"},
                first_private_key,
                algorithm="RS256",
                headers={"kid": "first"},
            )
            rotated_token = jwt.encode(
                {"sub": "two"},
                second_private_key,
                algorithm="RS256",
                headers={"kid": "second"},
            )
            self.assertEqual(
                client.get_signing_key_from_jwt(first_token).key.public_numbers(),
                first_private_key.public_key().public_numbers(),
            )
            self.assertEqual(
                client.get_signing_key_from_jwt(rotated_token).key.public_numbers(),
                second_private_key.public_key().public_numbers(),
            )
        self.assertEqual(fetch.call_count, 2)

    def test_oidc_settings_require_https_and_audience(self):
        with patch.dict("os.environ", {"AUTH0_ISSUER": "http://issuer.example/"}):
            with self.assertRaises(RuntimeError):
                OIDCSettings.from_environment()


if __name__ == "__main__":
    unittest.main()
