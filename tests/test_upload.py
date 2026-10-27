from tests import _isolation  # noqa: F401  (must be first: isolates test data)
import unittest
from io import BytesIO
from unittest.mock import patch

from app import create_app
from app.services.mask_service import MaskResponse

from tests._samples import PNG_BYTES  # noqa: E402


class UploadRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, RATE_LIMIT_ENABLED=False, API_KEY_REQUIRED=False)
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"

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
            profile_exists=True,
            profile_linked_documents_count=1,
            profile_linked_documents=[
                {
                    "type": "medical_certificate",
                    "id": "MED-ROUTE-001",
                    "label": "Medical Certificate",
                    "source": "registry",
                    "fileName": "med.pdf",
                    "fileKey": "route-med-1",
                }
            ],
            profile_auto_loaded=True,
        )

    def test_upload_file_success(self):
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_aadhaar_and_mask", return_value=self._fake_response()
        ):
            response = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "test_image.png")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["message"], "ok")

    def test_invalid_file_type(self):
        with patch("app.routes.mask.allowed_file", return_value=False):
            response = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(b"fake text data"), "test_file.txt")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid file type", response.get_json()["error"])

    def test_document_type_pan_uses_multi_document_service(self):
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_document_and_mask", return_value=self._fake_response()
        ) as patched:
            response = self.client.post(
                "/mask/document",
                data={
                    "file": (BytesIO(PNG_BYTES), "test_image.png"),
                    "document_type": "pan",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(patched.called)

    def test_document_route_includes_profile_linked_documents(self):
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_document_and_mask", return_value=self._fake_response()
        ):
            response = self.client.post(
                "/mask/document",
                data={
                    "file": (BytesIO(PNG_BYTES), "test_image.png"),
                    "document_type": "pan",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("profileExists"))
        self.assertTrue(payload.get("profileAutoLoaded"))
        self.assertGreaterEqual(int(payload.get("profileLinkedDocumentsCount", 0)), 1)
        linked = payload.get("profileLinkedDocuments", [])
        self.assertTrue(isinstance(linked, list) and linked)
        self.assertEqual(str(linked[0].get("label", "")), "Medical Certificate")

    def test_legacy_aadhaar_endpoint_still_supported(self):
        with patch("app.routes.mask.allowed_file", return_value=True), patch(
            "app.routes.mask.upload_aadhaar_and_mask", return_value=self._fake_response()
        ):
            response = self.client.post(
                "/mask/aadhaar",
                data={"file": (BytesIO(PNG_BYTES), "x.jpg")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)

    def test_invalid_document_type(self):
        with patch("app.routes.mask.allowed_file", return_value=True):
            response = self.client.post(
                "/mask/aadhaar",
                data={
                    "file": (BytesIO(PNG_BYTES), "test_image.png"),
                    "document_type": "passport",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid document_type", response.get_json()["error"])

    def test_pdf_extension_allowed_by_config(self):
        from app.config import Config

        self.assertIn("pdf", set(getattr(Config, "ALLOWED_EXTENSIONS", set())))


if __name__ == "__main__":
    unittest.main()
