from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import importlib.util
import os
import unittest

_PATH = os.path.join(os.path.dirname(__file__), "..", "tools", "scan_secrets.py")
_spec = importlib.util.spec_from_file_location("scan_secrets", _PATH)
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

# Built at runtime so this file never contains a literal that looks like a real key.
FAKE_CLERK_KEY = "sk_" + "test_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
RANDOM_VALUE = "Xk29fjs8dkQ2zLmN7pRt"


def kinds(path, line):
    return [kind for kind, _ in scan.scan_line(path, line)]


class SpecificTokenTests(unittest.TestCase):
    def test_clerk_secret_key_is_detected(self):
        self.assertIn("Clerk/Stripe secret key", kinds("app/x.py", f'KEY = "{FAKE_CLERK_KEY}"'))

    def test_aws_key_id_is_detected(self):
        self.assertIn("AWS access key id", kinds("app/x.py", f"id={FAKE_AWS_KEY}"))

    def test_private_key_block_is_detected(self):
        self.assertIn("Private key block", kinds("app/x.py", FAKE_PRIVATE_KEY))

    def test_specific_tokens_are_flagged_even_inside_tests(self):
        self.assertTrue(kinds("tests/test_x.py", FAKE_CLERK_KEY))

    def test_publishable_key_is_not_flagged(self):
        self.assertEqual(kinds(".env.example", "CLERK_PUBLISHABLE_KEY=pk_test_Y2xlcmsuZXhhbXBsZS5jb20k"), [])


class GenericAssignmentTests(unittest.TestCase):
    def test_random_looking_password_is_detected(self):
        self.assertTrue(kinds("app/x.py", f"SMTP_PASSWORD = '{RANDOM_VALUE}'"))
        self.assertTrue(kinds("settings.env", f"OTP_EMAIL_PASSWORD={RANDOM_VALUE}"))

    def test_long_hex_secret_is_detected(self):
        self.assertTrue(kinds("settings.env", "HASH_SECRET=" + "ab12" * 10))

    def test_placeholders_are_not_flagged(self):
        for line in (
            "SECRET_KEY=change-me-to-a-long-random-value",
            'S3_SECRET_ACCESS_KEY="your-secret-access-key-1234"',
            "API_KEY=panel-demo-key",
            "TOKEN=<paste-your-token-here-12345>",
            "HASH_SECRET=${HASH_SECRET_VALUE_1234}",
        ):
            self.assertEqual(kinds("README.md", line), [], line)

    def test_ordinary_code_is_not_flagged(self):
        for line in (
            'hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))',
            'password = str(request.form.get("password", "") or "")',
            "integrity_token = _build_integrity_token(job_id, processed_at)",
            "api_key = args.api_key",
            "ACCESS_TOKEN_TTL_SECONDS=300",
            "HEALTH_DETAILS_TOKEN=",
        ):
            self.assertEqual(kinds("app/x.py", line), [], line)

    def test_generic_rule_is_skipped_in_tests_directory(self):
        self.assertEqual(kinds("tests/test_x.py", f"password = '{RANDOM_VALUE}'"), [])

    def test_ignore_marker_allows_a_line(self):
        self.assertEqual(kinds("app/x.py", f"KEY = '{FAKE_CLERK_KEY}'  # secret-scan: ignore"), [])

    def test_findings_are_redacted(self):
        findings = scan.scan_text("app/x.py", f"a = 1\nSMTP_PASSWORD = '{RANDOM_VALUE}'\n")
        self.assertEqual(findings[0][1], 2)
        self.assertNotIn(RANDOM_VALUE, repr(findings))


class BlockedPathTests(unittest.TestCase):
    def test_secret_and_data_files_are_blocked(self):
        for path in (
            ".env", ".env.prod", ".env.local", "deployment/certs/privkey.pem", "keys/server.key",
            "output/identity_profiles.sqlite3", "output/masked_1.jpg", ".images/scan.pdf", "backup/x.bak.zip",
            "data/state.sqlite3", ".venv/Lib/x.py",
        ):
            self.assertTrue(scan.blocked_path(path), path)

    def test_normal_files_are_allowed(self):
        for path in (".env.example", "app/config.py", "README.md", "evaluation/samples/aadhaar_clean_0.png", "docs/feature-specs/01-overview-architecture.md"):
            self.assertFalse(scan.blocked_path(path), path)

    def test_windows_separators_are_handled(self):
        self.assertTrue(scan.blocked_path("deployment\\certs\\fullchain.pem"))


if __name__ == "__main__":
    unittest.main()
