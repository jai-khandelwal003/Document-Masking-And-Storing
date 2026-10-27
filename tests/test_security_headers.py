from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import base64
import os
import re
import unittest
from unittest.mock import patch

from flask import Flask

from app import _apply_runtime_guardrails, create_app

PUBLISHABLE_KEY = "pk_test_" + base64.b64encode(b"clerk.example.com$").decode()
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>", re.I)


def _nonce_from_csp(csp):
    match = re.search(r"'nonce-([^']+)'", csp)
    return match.group(1) if match else ""


class SecurityTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            AUTH_PROVIDER="local",
            USER_ID="admin",
            USER_PASSWORD="a-long-test-passphrase",
            SESSION_COOKIE_SECURE=False,
        )
        self.client = self.app.test_client()

    def _login(self, client=None):
        client = client or self.client
        with client.session_transaction() as sess:
            sess["auth_user"] = "test-user"

    def assert_inline_scripts_have_nonce(self, response):
        csp = response.headers["Content-Security-Policy"]
        nonce = _nonce_from_csp(csp)
        self.assertTrue(nonce)
        html = response.get_data(as_text=True)
        scripts = INLINE_SCRIPT.findall(html)
        self.assertTrue(scripts, "expected at least one inline script")
        for attrs in scripts:
            self.assertIn(f'nonce="{nonce}"', attrs)


class HeaderTests(SecurityTestBase):
    def test_baseline_headers_on_every_response(self):
        response = self.client.get("/login")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("strict-origin", response.headers["Referrer-Policy"])
        self.assertIn("camera=()", response.headers["Permissions-Policy"])

    def test_csp_blocks_framing_and_plugins_and_has_no_unsafe_inline_for_scripts(self):
        csp = self.client.get("/login").headers["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("base-uri 'self'", csp)
        script_src = [d for d in csp.split("; ") if d.startswith("script-src")][0]
        self.assertNotIn("unsafe-inline", script_src)
        self.assertNotIn("unsafe-eval", csp)

    def test_nonce_changes_on_every_request(self):
        first = _nonce_from_csp(self.client.get("/login").headers["Content-Security-Policy"])
        second = _nonce_from_csp(self.client.get("/login").headers["Content-Security-Policy"])
        self.assertNotEqual(first, second)

    def test_local_policy_does_not_allow_clerk_hosts(self):
        csp = self.client.get("/login").headers["Content-Security-Policy"]
        self.assertNotIn("clerk", csp)

    def test_sensitive_routes_are_not_cached(self):
        self._login()
        for path in ("/dashboard", "/login", "/output/whatever.jpg", "/identity/documents", "/analytics/audit-log"):
            response = self.client.get(path)
            self.assertIn("no-store", response.headers.get("Cache-Control", ""), path)

    def test_static_assets_are_not_forced_no_store(self):
        response = self.client.get("/static/manifest.json")
        self.assertNotIn("no-store", response.headers.get("Cache-Control", ""))

    def test_csp_can_be_disabled_or_report_only(self):
        self.app.config.update(SECURITY_CSP="off")
        self.assertNotIn("Content-Security-Policy", self.client.get("/login").headers)
        self.app.config.update(SECURITY_CSP="", SECURITY_CSP_REPORT_ONLY=True)
        headers = self.client.get("/login").headers
        self.assertIn("Content-Security-Policy-Report-Only", headers)
        self.assertNotIn("Content-Security-Policy", headers)

    def test_custom_policy_is_used_verbatim(self):
        self.app.config.update(SECURITY_CSP="default-src 'none'", SECURITY_CSP_REPORT_ONLY=False)
        self.assertEqual(self.client.get("/login").headers["Content-Security-Policy"], "default-src 'none'")

    def test_all_headers_can_be_switched_off(self):
        self.app.config.update(SECURITY_HEADERS_ENABLED=False)
        headers = self.client.get("/login").headers
        self.assertNotIn("X-Frame-Options", headers)
        self.assertNotIn("Content-Security-Policy", headers)


class NonceCoverageTests(SecurityTestBase):
    """Every inline script must carry the request nonce, otherwise the browser blocks it and the page breaks."""

    def test_local_login_page(self):
        self.assert_inline_scripts_have_nonce(self.client.get("/login"))

    def test_dashboard_page(self):
        self._login()
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assert_inline_scripts_have_nonce(response)

    def test_identity_documents_page(self):
        self._login()
        response = self.client.get("/identity/view")
        self.assertEqual(response.status_code, 400)
        self.assert_inline_scripts_have_nonce(response)

    def test_clerk_login_page_and_clerk_policy(self):
        self.app.config.update(
            AUTH_PROVIDER="clerk", CLERK_PUBLISHABLE_KEY=PUBLISHABLE_KEY, CLERK_SECRET_KEY="sk_test_dummy"
        )
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assert_inline_scripts_have_nonce(response)
        csp = response.headers["Content-Security-Policy"]
        self.assertIn("https://clerk.example.com", csp)
        self.assertIn("https://challenges.cloudflare.com", csp)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_dashboard_cdn_scripts_are_allowed_by_policy(self):
        self._login()
        csp = self.client.get("/dashboard").headers["Content-Security-Policy"]
        html = self.client.get("/dashboard").get_data(as_text=True)
        for host in re.findall(r'<script[^>]*\bsrc="(https://[^/"]+)', html):
            self.assertIn(host, csp)


class SessionCookieTests(SecurityTestBase):
    def _set_cookie(self):
        response = self.client.post("/login", data={"user_id": "admin", "password": "a-long-test-passphrase"})
        self.assertEqual(response.status_code, 302)
        return [h for h in response.headers.getlist("Set-Cookie") if h.startswith("session=")][0]

    def test_cookie_is_httponly_samesite_and_expires(self):
        cookie = self._set_cookie()
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Expires=", cookie)
        self.assertNotIn("Secure", cookie)

    def test_cookie_is_secure_when_configured(self):
        self.app.config.update(SESSION_COOKIE_SECURE=True)
        self.assertIn("Secure", self._set_cookie())

    def test_session_lifetime_is_bounded(self):
        hours = self.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds() / 3600
        self.assertEqual(hours, 8)

    def test_production_requires_secure_cookies(self):
        app = Flask(__name__)
        app.config.update(PRODUCTION=True, SESSION_COOKIE_SECURE=False, SECRET_KEY="s", HASH_SECRET="h")
        with patch.dict(os.environ, {"SECRET_KEY": "s", "HASH_SECRET": "h"}):
            with self.assertRaises(RuntimeError) as ctx:
                _apply_runtime_guardrails(app)
        self.assertIn("SESSION_COOKIE_SECURE", str(ctx.exception))


class ServiceWorkerTests(unittest.TestCase):
    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "sw.js")
        with open(path, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_worker_never_caches_pages_or_documents(self):
        self.assertNotIn("cache.put", self.source)
        self.assertNotIn('"/login"', self.source)
        self.assertNotIn("/output", self.source)
        self.assertNotIn("/identity", self.source)

    def test_cache_version_was_bumped_so_old_caches_are_purged(self):
        self.assertIn('"sdm-shell-v2"', self.source)
        self.assertIn("caches.delete", self.source)

    def test_only_same_origin_static_shell_assets_are_handled(self):
        self.assertIn("self.location.origin", self.source)
        self.assertIn("SHELL_ASSETS.includes", self.source)


if __name__ == "__main__":
    unittest.main()
