from tests import _isolation  # noqa: F401  (must be first: isolates test data)
import unittest
from io import BytesIO
from unittest.mock import patch

from app import create_app
from app.routes import mask as mask_route
from app.services.mask_service import MaskResponse

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class MaskSecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            API_KEY_REQUIRED=False,
            API_KEY="",
            RATE_LIMIT_ENABLED=False,
            RETURN_RAW_AADHAAR=False,
        )
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"
        mask_route._RATE_LIMIT_STATE.clear()

    @staticmethod
    def _fake_response():
        return MaskResponse(
            error="",
            message="ok",
            aadhaar_detected=True,
            qr_detected=False,
            output_image_path="output/x.jpg",
            output_image_url="/output/x.jpg",
            aadhaar_number="123456781234",
            aadhaar_hash="abc",
            aadhaar_preview="XXXXXXXX1234",
            input_file_hash="in_hash",
            output_file_hash="out_hash",
            no_of_aadhaar_detected=1,
            no_of_qr_detected=0,
        )

    def test_api_key_required_blocks_without_header(self):
        self.app.config.update(API_KEY_REQUIRED=True, API_KEY="demo-key")
        with patch("app.routes.mask.allowed_file", return_value=True):
            response = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "x.jpg")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid API key", response.get_json()["error"])

    def test_api_key_required_allows_with_valid_header(self):
        self.app.config.update(API_KEY_REQUIRED=True, API_KEY="demo-key")
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_aadhaar_and_mask", return_value=self._fake_response()
        ):
            response = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "x.jpg")},
                headers={"X-API-Key": "demo-key"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["message"], "ok")

    def test_rate_limit_blocks_after_threshold(self):
        self.app.config.update(
            RATE_LIMIT_ENABLED=True,
            RATE_LIMIT_REQUESTS=1,
            RATE_LIMIT_WINDOW_SECONDS=60,
        )
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_aadhaar_and_mask", return_value=self._fake_response()
        ):
            first = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "x.jpg")},
                content_type="multipart/form-data",
            )
            second = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "x.jpg")},
                content_type="multipart/form-data",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("retryAfterSec", second.get_json())

    def test_raw_aadhaar_redacted_by_default(self):
        self.app.config.update(RETURN_RAW_AADHAAR=False)
        with self.app.app_context():
            payload = self._fake_response().to_dict()

        self.assertEqual(payload["aadhaarNumber"], "")
        self.assertEqual(payload["aadhaarPreview"], "XXXXXXXX1234")

    def test_raw_aadhaar_can_be_enabled(self):
        self.app.config.update(RETURN_RAW_AADHAAR=True)
        with self.app.app_context():
            payload = self._fake_response().to_dict()

        self.assertEqual(payload["aadhaarNumber"], "123456781234")


if __name__ == "__main__":
    unittest.main()