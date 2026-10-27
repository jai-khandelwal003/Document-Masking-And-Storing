from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import unittest

from app import create_app
from app.routes import auth
from app.utils.client_ip import client_ip


class RateLimitTestBase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            RATE_LIMIT_FORCE=True,
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_OTP="2 per minute",
            RATE_LIMIT_VERIFY="3 per minute",
            RATE_LIMIT_IDENTITY="4 per minute",
            TRUST_PROXY_HEADERS=False,
            AUTH_PROVIDER="local",
            USER_PASSWORD="a-long-test-passphrase",
        )
        auth.limiter.reset()
        self.addCleanup(auth.limiter.reset)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"

    def hits(self, method, url, n, **kwargs):
        return [getattr(self.client, method)(url, **kwargs).status_code for _ in range(n)]


class CodeAndOtpLimitTests(RateLimitTestBase):
    def test_access_code_requests_are_limited(self):
        codes = self.hits("post", "/access/request-code", 4, json={"jobId": "nope", "last4": "1234"})
        self.assertEqual(codes, [404, 404, 429, 429])

    def test_identity_otp_requests_are_limited(self):
        codes = self.hits("post", "/identity/request-otp", 3, json={"jobId": "nope"})
        self.assertEqual(codes, [404, 404, 429])

    def test_verify_and_unlock_have_their_own_limits(self):
        self.assertEqual(self.hits("post", "/access/verify", 4, json={"jobId": "nope", "code": "000000"}), [404, 404, 404, 429])
        self.assertEqual(self.hits("post", "/identity/unlock", 4, json={"jobId": "nope", "pin": "1234"}), [404, 404, 404, 429])

    def test_each_endpoint_has_its_own_bucket(self):
        self.hits("post", "/access/request-code", 3, json={"jobId": "nope", "last4": "1234"})
        self.assertEqual(self.client.post("/identity/request-otp", json={"jobId": "nope"}).status_code, 404)

    def test_identity_endpoints_use_the_general_limit(self):
        self.assertEqual(self.hits("get", "/identity/documents?profileKey=p1", 5), [200, 200, 200, 200, 429])
        self.assertEqual(self.hits("get", "/analytics/audit-log", 5), [200, 200, 200, 200, 429])

    def test_limited_response_is_json_with_retry_hint(self):
        self.hits("post", "/access/request-code", 2, json={"jobId": "nope", "last4": "1234"})
        response = self.client.post("/access/request-code", json={"jobId": "nope", "last4": "1234"})
        self.assertEqual(response.status_code, 429)
        body = response.get_json()
        self.assertEqual(body["error"], "Too many requests")
        self.assertGreater(body["retryAfterSec"], 0)

    def test_limits_can_be_switched_off(self):
        self.app.config.update(RATE_LIMIT_ENABLED=False)
        self.assertEqual(set(self.hits("post", "/access/request-code", 8, json={"jobId": "nope", "last4": "1234"})), {404})

    def test_unit_tests_are_not_limited_unless_forced(self):
        self.app.config.update(RATE_LIMIT_FORCE=False)
        self.assertEqual(set(self.hits("post", "/access/request-code", 8, json={"jobId": "nope", "last4": "1234"})), {404})

    def test_limits_are_read_from_config_per_request(self):
        self.app.config.update(RATE_LIMIT_OTP="1 per minute")
        self.assertEqual(self.hits("post", "/identity/request-otp", 2, json={"jobId": "nope"}), [404, 429])


class LoginLimitTests(RateLimitTestBase):
    def test_sixth_failed_login_is_blocked_with_a_login_page(self):
        anon = self.app.test_client()
        statuses = [anon.post("/login", data={"user_id": "admin", "password": "wrong"}).status_code for _ in range(6)]
        self.assertEqual(statuses[:5], [200] * 5)
        last = anon.post("/login", data={"user_id": "admin", "password": "wrong"})
        self.assertEqual(statuses[5], 429)
        self.assertIn("Too many login attempts", last.get_data(as_text=True))

    def test_page_loads_do_not_count(self):
        anon = self.app.test_client()
        self.assertEqual({anon.get("/login").status_code for _ in range(10)}, {200})


class ClientAddressTests(RateLimitTestBase):
    def _ip(self, header=None, **config):
        self.app.config.update(config)
        headers = {"X-Forwarded-For": header} if header else {}
        with self.app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": "10.0.0.5"}):
            return client_ip()

    def test_header_ignored_unless_proxy_is_trusted(self):
        self.assertEqual(self._ip("203.0.113.9", TRUST_PROXY_HEADERS=False), "10.0.0.5")

    def test_trusted_proxy_uses_the_address_it_appended(self):
        self.assertEqual(self._ip("203.0.113.9", TRUST_PROXY_HEADERS=True), "203.0.113.9")

    def test_forged_left_entries_are_ignored(self):
        self.assertEqual(self._ip("1.1.1.1, 203.0.113.9", TRUST_PROXY_HEADERS=True), "203.0.113.9")

    def test_two_trusted_hops_take_the_second_from_the_right(self):
        self.assertEqual(self._ip("forged, 203.0.113.9, 10.1.1.1", TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_COUNT=2), "203.0.113.9")

    def test_missing_or_short_header_falls_back_to_socket_address(self):
        self.assertEqual(self._ip(None, TRUST_PROXY_HEADERS=True), "10.0.0.5")
        self.assertEqual(self._ip("203.0.113.9", TRUST_PROXY_HEADERS=True, TRUSTED_PROXY_COUNT=3), "10.0.0.5")

    def test_different_clients_behind_the_proxy_get_separate_quotas(self):
        self.app.config.update(TRUST_PROXY_HEADERS=True)

        def call(ip):
            return self.client.post(
                "/access/request-code", json={"jobId": "nope", "last4": "1234"}, headers={"X-Forwarded-For": ip}
            ).status_code

        self.assertEqual([call("203.0.113.1"), call("203.0.113.1"), call("203.0.113.1")], [404, 404, 429])
        self.assertEqual(call("203.0.113.2"), 404)

    def test_forging_the_header_does_not_dodge_the_limit(self):
        self.app.config.update(TRUST_PROXY_HEADERS=True)
        results = [
            self.client.post(
                "/access/request-code",
                json={"jobId": "nope", "last4": "1234"},
                headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"},
            ).status_code
            for i in range(3)
        ]
        self.assertEqual(results, [404, 404, 429])


if __name__ == "__main__":
    unittest.main()
