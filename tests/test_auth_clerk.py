from tests import _isolation  # noqa: F401  (must be first: isolates test data)
import base64
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask

from app import _apply_runtime_guardrails, create_app
from app.routes import mask as mask_route
from app.services import clerk_service

HOST = "clerk.example.com"
PUBLISHABLE_KEY = "pk_test_" + base64.b64encode(f"{HOST}$".encode()).decode()


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJwksClient:
    def __init__(self, public_key):
        self._key = _FakeSigningKey(public_key)

    def get_signing_key_from_jwt(self, token):
        return self._key


class ClerkTestBase(unittest.TestCase):
    def setUp(self):
        self._db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self._db.close()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            AUTH_PROVIDER="clerk",
            CLERK_PUBLISHABLE_KEY=PUBLISHABLE_KEY,
            CLERK_SECRET_KEY="sk_test_dummy",
            CLERK_ALLOWED_EMAILS="owner@example.com",
            CLERK_ALLOWED_DOMAINS="",
            CLERK_AUTHORIZED_PARTIES="",
            CLERK_ALLOW_ANY_USER=False,
            ACCESS_STATE_DB_PATH=self._db.name,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            os.remove(self._db.name)
        except OSError:
            pass


class ClerkLoginPageTests(ClerkTestBase):
    def test_login_page_loads_clerk_sdk(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn(f"https://{HOST}/npm/@clerk/clerk-js@5/dist/clerk.browser.js", body)
        self.assertIn(PUBLISHABLE_KEY, body)

    def test_login_page_can_be_loaded_repeatedly(self):
        for _ in range(8):
            self.assertEqual(self.client.get("/login").status_code, 200)

    def test_unconfigured_clerk_shows_message(self):
        self.app.config.update(CLERK_PUBLISHABLE_KEY="", CLERK_SECRET_KEY="")
        body = self.client.get("/login").get_data(as_text=True)
        self.assertIn("Clerk is not configured", body)
        self.assertNotIn("clerk.browser.js", body)

    def test_protected_route_redirects_to_login(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_session_exchange_logs_user_in(self):
        with patch("app.routes.auth.clerk_service.authenticate", return_value="owner@example.com"):
            response = self.client.post("/auth/clerk/session", json={"token": "t", "next": "/dashboard"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["redirect"], "/dashboard")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_session_exchange_rejects_open_redirect(self):
        with patch("app.routes.auth.clerk_service.authenticate", return_value="owner@example.com"):
            response = self.client.post("/auth/clerk/session", json={"token": "t", "next": "//evil.example"})
        self.assertEqual(response.get_json()["redirect"], "/dashboard")

    def test_session_exchange_rejects_bad_token(self):
        with patch(
            "app.routes.auth.clerk_service.authenticate",
            side_effect=clerk_service.ClerkAuthError("Invalid or expired session token"),
        ):
            response = self.client.post("/auth/clerk/session", json={"token": "bad"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_session_exchange_disabled_for_local_provider(self):
        self.app.config.update(AUTH_PROVIDER="local")
        response = self.client.post("/auth/clerk/session", json={"token": "x"})
        self.assertEqual(response.status_code, 404)

    def test_logout_renders_clerk_signout(self):
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "owner@example.com"
        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn("signOut", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/dashboard").status_code, 302)


class ClerkServiceTests(ClerkTestBase):
    def setUp(self):
        super().setUp()
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        super().tearDown()

    def _token(self, **overrides):
        now = int(time.time())
        claims = {"sub": "user_123", "iss": f"https://{HOST}", "iat": now, "exp": now + 60, "azp": "https://app.example.com"}
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "k1"})

    def _verify(self, token):
        with patch.object(clerk_service, "_jwks_client", return_value=_FakeJwksClient(self.public_key)):
            return clerk_service.verify_session_token(token)

    def test_frontend_host_is_decoded_from_publishable_key(self):
        self.assertEqual(clerk_service.frontend_api_host(PUBLISHABLE_KEY), HOST)
        self.assertEqual(clerk_service.frontend_api_host("not-a-key"), "")

    def test_valid_token_is_accepted(self):
        self.assertEqual(self._verify(self._token())["sub"], "user_123")

    def test_expired_token_is_rejected(self):
        with self.assertRaises(clerk_service.ClerkAuthError):
            self._verify(self._token(exp=int(time.time()) - 600, iat=int(time.time()) - 700))

    def test_wrong_issuer_is_rejected(self):
        with self.assertRaises(clerk_service.ClerkAuthError):
            self._verify(self._token(iss="https://evil.example.com"))

    def test_token_signed_by_other_key_is_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = int(time.time())
        forged = jwt.encode(
            {"sub": "user_123", "iss": f"https://{HOST}", "iat": now, "exp": now + 60}, other, algorithm="RS256"
        )
        with self.assertRaises(clerk_service.ClerkAuthError):
            self._verify(forged)

    def test_unauthorized_party_is_rejected(self):
        self.app.config.update(CLERK_AUTHORIZED_PARTIES="https://app.example.com")
        self._verify(self._token())
        with self.assertRaises(clerk_service.ClerkAuthError):
            self._verify(self._token(azp="https://other.example.com"))

    def test_allowlisted_email_is_accepted(self):
        with patch.object(clerk_service, "verify_session_token", return_value={"sub": "user_123"}), patch.object(
            clerk_service, "fetch_user_emails", return_value=["owner@example.com"]
        ):
            self.assertEqual(clerk_service.authenticate("tok"), "owner@example.com")

    def test_non_allowlisted_email_is_rejected(self):
        with patch.object(clerk_service, "verify_session_token", return_value={"sub": "user_123"}), patch.object(
            clerk_service, "fetch_user_emails", return_value=["stranger@example.com"]
        ):
            with self.assertRaises(clerk_service.ClerkAuthError):
                clerk_service.authenticate("tok")

    def test_allowed_domain_is_accepted(self):
        self.app.config.update(CLERK_ALLOWED_EMAILS="", CLERK_ALLOWED_DOMAINS="corp.example.com")
        self.assertTrue(clerk_service.is_email_allowed(["a@corp.example.com"]))
        self.assertFalse(clerk_service.is_email_allowed(["a@corp.example.com.evil.io"]))

    def test_no_allowlist_denies_everyone_unless_explicitly_opened(self):
        self.app.config.update(CLERK_ALLOWED_EMAILS="", CLERK_ALLOWED_DOMAINS="")
        self.assertFalse(clerk_service.is_email_allowed(["anyone@example.com"]))
        self.app.config.update(CLERK_ALLOW_ANY_USER=True)
        self.assertTrue(clerk_service.is_email_allowed(["anyone@example.com"]))


class LocalAuthHardeningTests(unittest.TestCase):
    def setUp(self):
        self._db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        self._db.close()
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            AUTH_PROVIDER="local",
            USER_ID="admin",
            USER_PASSWORD="initial-password",
            ACCESS_STATE_DB_PATH=self._db.name,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            os.remove(self._db.name)
        except OSError:
            pass

    def _login(self, client, password):
        return client.post("/login", data={"user_id": "admin", "password": password})

    def test_changed_password_is_persisted_and_old_one_stops_working(self):
        self.assertEqual(self._login(self.client, "initial-password").status_code, 302)
        response = self.client.post(
            "/auth/change-password", json={"currentPassword": "initial-password", "newPassword": "brand-new-pass"}
        )
        self.assertEqual(response.status_code, 200)

        fresh = self.app.test_client()
        self.assertEqual(self._login(fresh, "initial-password").status_code, 200)
        self.assertEqual(self._login(fresh, "brand-new-pass").status_code, 302)

    def test_login_page_loads_do_not_consume_login_attempts(self):
        for _ in range(10):
            self.assertEqual(self.client.get("/login").status_code, 200)


class OutputAccessTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"
        self.output_dir = os.path.abspath(os.path.join(self.app.root_path, "..", "output"))
        os.makedirs(self.output_dir, exist_ok=True)
        self.name = "masked_test_ownership.jpg"
        self.path = os.path.join(self.output_dir, self.name)
        with open(self.path, "wb") as handle:
            handle.write(b"\xff\xd8\xff\xe0")

    def tearDown(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_other_sessions_cannot_read_masked_output_directly(self):
        self.assertEqual(self.client.get(f"/output/{self.name}").status_code, 403)

    def test_creating_session_can_read_its_own_output(self):
        with self.client.session_transaction() as sess:
            sess["owned_outputs"] = [self.name]
        self.assertEqual(self.client.get(f"/output/{self.name}").status_code, 200)

    def test_traversal_is_not_allowed_even_for_owner(self):
        with self.client.session_transaction() as sess:
            sess["owned_outputs"] = [self.name]
        self.assertIn(self.client.get("/output/../main.py").status_code, {403, 404})

    def test_remember_output_keeps_only_recent_files(self):
        with self.app.test_request_context("/"):
            from flask import session

            for i in range(60):
                mask_route._remember_output({"outputImageUrl": f"/output/masked_{i}.jpg"})
            self.assertEqual(len(session["owned_outputs"]), 50)
            self.assertEqual(session["owned_outputs"][-1], "masked_59.jpg")


class ProxyTrustTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _ip(self, trust):
        self.app.config.update(TRUST_PROXY_HEADERS=trust)
        with self.app.test_request_context(
            "/", headers={"X-Forwarded-For": "203.0.113.9"}, environ_base={"REMOTE_ADDR": "10.0.0.5"}
        ):
            return mask_route._client_ip()

    def test_forwarded_header_ignored_by_default(self):
        self.assertEqual(self._ip(False), "10.0.0.5")

    def test_forwarded_header_used_when_proxy_trusted(self):
        self.assertEqual(self._ip(True), "203.0.113.9")


class ProductionGuardrailTests(unittest.TestCase):
    def _app(self, **config):
        app = Flask(__name__)
        app.config.update(
            PRODUCTION=True,
            SECRET_KEY="s",
            HASH_SECRET="h",
            API_KEY_REQUIRED=False,
            HEALTH_DETAILS_TOKEN="t",
            ACCESS_SHOW_CODE=False,
            IDENTITY_SHOW_OTP=False,
            IDENTITY_OTP_PROVIDER="email",
            OTP_EMAIL_SMTP_HOST="smtp.example.net",
            OTP_EMAIL_USERNAME="mailer@example.net",
            OTP_EMAIL_PASSWORD="real-secret",
            OTP_EMAIL_FROM="mailer@example.net",
        )
        app.config.update(config)
        return app

    def test_default_password_blocked_with_local_provider(self):
        with patch.dict(os.environ, {"SECRET_KEY": "s", "HASH_SECRET": "h"}):
            with self.assertRaises(RuntimeError):
                _apply_runtime_guardrails(self._app(AUTH_PROVIDER="local", USER_PASSWORD="admin123"))

    def test_strong_password_allowed_with_local_provider(self):
        with patch.dict(os.environ, {"SECRET_KEY": "s", "HASH_SECRET": "h"}):
            _apply_runtime_guardrails(self._app(AUTH_PROVIDER="local", USER_PASSWORD="a-long-unique-passphrase"))

    def test_clerk_requires_allowlist_in_production(self):
        base = dict(AUTH_PROVIDER="clerk", CLERK_PUBLISHABLE_KEY=PUBLISHABLE_KEY, CLERK_SECRET_KEY="sk_live_x")
        with patch.dict(os.environ, {"SECRET_KEY": "s", "HASH_SECRET": "h"}):
            with self.assertRaises(RuntimeError):
                _apply_runtime_guardrails(self._app(**base))
            _apply_runtime_guardrails(self._app(CLERK_ALLOWED_EMAILS="owner@example.com", **base))


class HealthPublicTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_health_is_public_without_login(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "UP")

    def test_health_details_still_requires_login(self):
        self.assertEqual(self.client.get("/health/details").status_code, 401)


if __name__ == "__main__":
    unittest.main()
