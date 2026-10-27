from tests import _isolation  # noqa: F401  (must be first: isolates test data)
import unittest
import tempfile
import os

from app import create_app


class HealthTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"

    def test_health_endpoint_public(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertEqual(payload["status"], "UP")
        self.assertNotIn("security", payload)
        self.assertNotIn("system", payload)

    def test_health_endpoint_details(self):
        response = self.client.get("/health/details")
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertIn("security", payload)
        self.assertIn("system", payload)
        self.assertIn("pdfRendererReady", payload["system"])
        self.assertIn("accessState", payload["system"])
        self.assertIn("persistEnabled", payload["system"]["accessState"])
        self.assertIn("dbPath", payload["system"]["accessState"])
        self.assertIn("runtime", payload)
        self.assertIn("demoProfileActive", payload["runtime"])
        self.assertIn("warnings", payload["runtime"])
        self.assertIn("storage", payload["system"])

    def test_health_details_includes_storage_usage_stats(self):
        with tempfile.TemporaryDirectory() as output_dir, tempfile.TemporaryDirectory() as uploads_dir:
            masked_file = os.path.join(output_dir, "masked_demo.jpg")
            identity_dir = os.path.join(output_dir, "identity_docs")
            os.makedirs(identity_dir, exist_ok=True)
            identity_file = os.path.join(identity_dir, "doc.png")
            upload_file = os.path.join(uploads_dir, "original.jpg")

            with open(masked_file, "wb") as f:
                f.write(b"12345")
            with open(identity_file, "wb") as f:
                f.write(b"123")
            with open(upload_file, "wb") as f:
                f.write(b"1234567")

            self.app.config.update(
                STORAGE_CLEANUP_ENABLED=True,
                STORAGE_CLEANUP_AT_STARTUP=True,
                STORAGE_RETENTION_DAYS=30,
                PERSIST_ORIGINAL_UPLOADS=True,
                ORIGINAL_UPLOADS_DIR=uploads_dir,
            )

            from app.routes.health import _detailed_payload

            with self.app.app_context():
                details = _detailed_payload(output_dir, samples_dir=output_dir)
            storage = details["system"]["storage"]

            self.assertTrue(storage["cleanupEnabled"])
            self.assertTrue(storage["persistOriginalUploads"])
            self.assertEqual(storage["retentionDays"], 30)

            output_stats = storage["directories"]["output"]
            uploads_stats = storage["directories"]["originalUploads"]
            identity_stats = storage["directories"]["identityDocuments"]

            self.assertTrue(output_stats["exists"])
            self.assertTrue(uploads_stats["exists"])
            self.assertTrue(identity_stats["exists"])
            self.assertGreaterEqual(output_stats["fileCount"], 2)
            self.assertGreaterEqual(uploads_stats["fileCount"], 1)
            self.assertGreaterEqual(identity_stats["fileCount"], 1)

    def test_health_runtime_flags_detect_demo_profile(self):
        self.app.config.update(ACCESS_SHOW_CODE=True, IDENTITY_SHOW_OTP=True, IDENTITY_OTP_PROVIDER="demo")

        response = self.client.get("/health/details")
        self.assertEqual(response.status_code, 200)
        runtime = response.get_json()["runtime"]
        self.assertTrue(runtime["demoProfileActive"])
        self.assertGreaterEqual(len(runtime["warnings"]), 1)

    def test_health_endpoint_details_requires_token_in_production(self):
        self.app.config.update(TESTING=False, PRODUCTION=True, HEALTH_DETAILS_TOKEN="health-token")

        denied = self.client.get("/health/details")
        self.assertEqual(denied.status_code, 401)

        allowed = self.client.get("/health/details", headers={"X-Health-Token": "health-token"})
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
