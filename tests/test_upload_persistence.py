from tests import _isolation  # noqa: F401  (must be first: isolates test data)
import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from app import create_app
from app.services.mask_service import upload_document_and_mask


class UploadPersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, RATE_LIMIT_ENABLED=False, API_KEY_REQUIRED=False)

    def _make_filestorage(self, name="sample.jpg"):
        return FileStorage(stream=BytesIO(b"fake-image-content"), filename=name, content_type="image/jpeg")

    def test_original_upload_deleted_when_persistence_disabled(self):
        with tempfile.TemporaryDirectory() as upload_dir, tempfile.TemporaryDirectory() as original_dir:
            self.app.config.update(
                PERSIST_ORIGINAL_UPLOADS=False,
                UPLOAD_FOLDER=upload_dir,
                ORIGINAL_UPLOADS_DIR=original_dir,
            )

            with self.app.app_context(), patch(
                "app.services.mask_utils.aadhaar.mask_aadhaar", return_value=(False, "", 0)
            ):
                response = upload_document_and_mask(
                    self._make_filestorage(),
                    mask_first8=True,
                    mask_last4=False,
                    mask_qr=False,
                    document_type="aadhaar",
                )

            self.assertEqual(response.error, "No supported document number detected")
            self.assertEqual(os.listdir(upload_dir), [])

    def test_original_upload_retained_when_persistence_enabled(self):
        with tempfile.TemporaryDirectory() as upload_dir, tempfile.TemporaryDirectory() as original_dir:
            self.app.config.update(
                PERSIST_ORIGINAL_UPLOADS=True,
                UPLOAD_FOLDER=upload_dir,
                ORIGINAL_UPLOADS_DIR=original_dir,
            )

            with self.app.app_context(), patch(
                "app.services.mask_utils.aadhaar.mask_aadhaar", return_value=(False, "", 0)
            ):
                response = upload_document_and_mask(
                    self._make_filestorage(),
                    mask_first8=True,
                    mask_last4=False,
                    mask_qr=False,
                    document_type="aadhaar",
                )

            self.assertEqual(response.error, "No supported document number detected")
            retained = os.listdir(original_dir)
            self.assertEqual(len(retained), 1)
            self.assertTrue(retained[0].endswith("sample.jpg"))


if __name__ == "__main__":
    unittest.main()
