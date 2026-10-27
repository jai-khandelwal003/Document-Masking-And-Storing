import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from app import create_app
from app.services.access_service import _reset_access_state_for_tests, register_identity_vault
from app.services.mask_service import upload_document_and_mask


class IdentityVaultFullMaskTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            RATE_LIMIT_ENABLED=False,
            API_KEY_REQUIRED=False,
            IDENTITY_REQUIRE_OTP=True,
            IDENTITY_SHOW_OTP=True,
            IDENTITY_OTP_PROVIDER="demo",
        )
        _reset_access_state_for_tests()

        self.temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        self.temp_input.write(b"fake-image-bytes")
        self.temp_input.flush()
        self.temp_input.close()

    def tearDown(self):
        _reset_access_state_for_tests()
        if os.path.exists(self.temp_input.name):
            os.remove(self.temp_input.name)
        output_path = os.path.join("output", "masked_testjobfullmask.jpg")
        if os.path.exists(output_path):
            os.remove(output_path)

    @staticmethod
    def _build_file_storage(filename):
        return FileStorage(stream=BytesIO(b"fake-image-bytes"), filename=filename, content_type="image/jpeg")

    @staticmethod
    def _mock_hash_file_sha256(_):
        return "sha256-dummy"

    def test_pan_full_mask_enables_identity_with_first8_pin(self):
        with self.app.app_context(), patch(
            "app.services.mask_service.handle_file_upload", return_value=self.temp_input.name
        ), patch("app.services.mask_service.hash_file_sha256", side_effect=self._mock_hash_file_sha256), patch(
            "app.services.mask_service.uuid.uuid4"
        ) as patched_uuid, patch(
            "app.services.mask_utils.document_generic.mask_pan_and_driving_licence",
            return_value=(True, False, 1, 0, "ABCDE1234F", "", 0.92, 0.0, "pan-standard", ""),
        ):
            patched_uuid.return_value.hex = "testjobfullmask"
            response = upload_document_and_mask(
                self._build_file_storage("pan.jpg"),
                mask_first8=True,
                mask_last4=True,
                mask_qr=False,
                document_type="pan",
            )

        payload = response.to_dict()
        self.assertTrue(payload["identityVaultEnabled"])
        self.assertEqual(payload["identityPinMode"], "first8")
        self.assertEqual(payload["documentType"], "pan")

    def test_dl_full_mask_enables_identity_with_first8_pin(self):
        with self.app.app_context(), patch(
            "app.services.mask_service.handle_file_upload", return_value=self.temp_input.name
        ), patch("app.services.mask_service.hash_file_sha256", side_effect=self._mock_hash_file_sha256), patch(
            "app.services.mask_service.uuid.uuid4"
        ) as patched_uuid, patch(
            "app.services.mask_utils.document_generic.mask_pan_and_driving_licence",
            return_value=(False, True, 0, 1, "", "DL0420110149646", 0.0, 0.9, "", "dl-india-standard"),
        ):
            patched_uuid.return_value.hex = "testjobfullmask"
            response = upload_document_and_mask(
                self._build_file_storage("dl.jpg"),
                mask_first8=True,
                mask_last4=True,
                mask_qr=False,
                document_type="dl",
            )

        payload = response.to_dict()
        self.assertTrue(payload["identityVaultEnabled"])
        self.assertEqual(payload["identityPinMode"], "first8")
        self.assertEqual(payload["documentType"], "dl")

    def test_pan_last4_mode_registers_visible_fragment_access(self):
        with self.app.app_context(), patch(
            "app.services.mask_service.handle_file_upload", return_value=self.temp_input.name
        ), patch("app.services.mask_service.hash_file_sha256", side_effect=self._mock_hash_file_sha256), patch(
            "app.services.mask_service.uuid.uuid4"
        ) as patched_uuid, patch(
            "app.services.mask_utils.document_generic.mask_pan_and_driving_licence",
            return_value=(True, False, 1, 0, "ABCDE1234F", "", 0.92, 0.0, "pan-standard", ""),
        ):
            patched_uuid.return_value.hex = "testjobpanfragment"
            response = upload_document_and_mask(
                self._build_file_storage("pan.jpg"),
                mask_first8=False,
                mask_last4=True,
                mask_qr=False,
                document_type="pan",
            )

        payload = response.to_dict()
        self.assertTrue(payload["accessChallengeAvailable"])
        self.assertEqual(payload["accessChallengeType"], "visible_fragment")
        self.assertIn("PAN", payload["accessChallengeHint"])

    def test_dl_first8_mode_registers_visible_fragment_access(self):
        with self.app.app_context(), patch(
            "app.services.mask_service.handle_file_upload", return_value=self.temp_input.name
        ), patch("app.services.mask_service.hash_file_sha256", side_effect=self._mock_hash_file_sha256), patch(
            "app.services.mask_service.uuid.uuid4"
        ) as patched_uuid, patch(
            "app.services.mask_utils.document_generic.mask_pan_and_driving_licence",
            return_value=(False, True, 0, 1, "", "DL0420110149646", 0.0, 0.9, "", "dl-india-standard"),
        ):
            patched_uuid.return_value.hex = "testjobdlfragment"
            response = upload_document_and_mask(
                self._build_file_storage("dl.jpg"),
                mask_first8=True,
                mask_last4=False,
                mask_qr=False,
                document_type="dl",
            )

        payload = response.to_dict()
        self.assertTrue(payload["accessChallengeAvailable"])
        self.assertEqual(payload["accessChallengeType"], "visible_fragment")
        self.assertIn("Driving Licence", payload["accessChallengeHint"])

    def test_pan_repeat_person_returns_existing_profile_documents(self):
        with self.app.app_context():
            ok, _ = register_identity_vault(
                "seedpanjob",
                "ABCDE1234F",
                pin_mode="last4",
                linked_documents=[
                    {
                        "type": "medical_certificate",
                        "id": "MED-EXIST-001",
                        "label": "Medical Certificate",
                        "source": "self-declared",
                    }
                ],
                document_type="pan",
            )
            self.assertTrue(ok)

        with self.app.app_context(), patch(
            "app.services.mask_service.handle_file_upload", return_value=self.temp_input.name
        ), patch("app.services.mask_service.hash_file_sha256", side_effect=self._mock_hash_file_sha256), patch(
            "app.services.mask_service.uuid.uuid4"
        ) as patched_uuid, patch(
            "app.services.mask_utils.document_generic.mask_pan_and_driving_licence",
            return_value=(True, False, 1, 0, "ABCDE1234F", "", 0.92, 0.0, "pan-standard", ""),
        ):
            patched_uuid.return_value.hex = "testjobrepeatprofile"
            response = upload_document_and_mask(
                self._build_file_storage("pan.jpg"),
                mask_first8=False,
                mask_last4=True,
                mask_qr=False,
                document_type="pan",
            )

        payload = response.to_dict()
        self.assertTrue(payload["profileExists"])
        self.assertGreaterEqual(int(payload["profileLinkedDocumentsCount"]), 1)
        labels = {str(item.get("label", "")) for item in payload.get("profileLinkedDocuments", [])}
        self.assertIn("Medical Certificate", labels)


if __name__ == "__main__":
    unittest.main()
