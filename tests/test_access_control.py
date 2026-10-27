import os
import shutil
import unittest
from io import BytesIO

from app import create_app
from app.services.access_service import (
    register_job_for_access,
    register_identity_vault,
    register_person_documents,
    _reset_access_state_for_tests,
)


class AccessControlTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            ACCESS_SHOW_CODE=True,
            ACCESS_CODE_TTL_SECONDS=120,
            ACCESS_TOKEN_TTL_SECONDS=120,
            ACCESS_MAX_ATTEMPTS=3,
            ACCESS_FALLBACK_SECRET="panel-fallback-123",
            IDENTITY_REQUIRE_OTP=True,
            IDENTITY_SHOW_OTP=True,
            IDENTITY_OTP_TTL_SECONDS=120,
            IDENTITY_OTP_MAX_ATTEMPTS=3,
            IDENTITY_OTP_COOLDOWN_SECONDS=0,
            IDENTITY_OTP_PROVIDER="demo",
        )
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"
        _reset_access_state_for_tests()

        with self.app.app_context():
            register_person_documents(
                "123456781234",
                [
                    {"type": "dl", "id": "DL-REF-001", "label": "Driving Licence", "source": "vault"},
                ],
            )
            register_job_for_access("job_demo", "XXXXXXXX1234", "/output/masked_job_demo.jpg")
            register_job_for_access(
                "job_fragment",
                "AB12CD34",
                "/output/masked_job_fragment.jpg",
                challenge_type="visible_fragment",
            )
            register_job_for_access(
                "job_fullmask",
                "panel-fallback-123",
                "/output/masked_job_fullmask.jpg",
                challenge_type="fallback_secret",
            )
            register_identity_vault(
                "job_identity",
                "123456781234",
                pin_mode="last4",
                linked_documents=[
                    {"type": "aadhaar", "id": "masked_aadhaar_ref", "label": "Aadhaar"},
                    {"type": "pan", "id": "ABCDE1234F", "label": "PAN"},
                ],
            )
            register_identity_vault(
                "job_identity_pan",
                "ABCDE1234F",
                pin_mode="first8",
                linked_documents=[
                    {"type": "pan", "id": "ABCDE1234F", "label": "PAN"},
                ],
                document_type="pan",
            )

        self.output_dir = os.path.abspath("output")
        os.makedirs(self.output_dir, exist_ok=True)
        self.output_file = os.path.join(self.output_dir, "masked_job_demo.jpg")
        with open(self.output_file, "wb") as file_obj:
            file_obj.write(b"demo")
        self.output_file_fragment = os.path.join(self.output_dir, "masked_job_fragment.jpg")
        with open(self.output_file_fragment, "wb") as file_obj:
            file_obj.write(b"fragment")
        self.output_file_fullmask = os.path.join(self.output_dir, "masked_job_fullmask.jpg")
        with open(self.output_file_fullmask, "wb") as file_obj:
            file_obj.write(b"fullmask")

    def tearDown(self):
        _reset_access_state_for_tests()
        if os.path.exists(self.output_file):
            os.remove(self.output_file)
        if os.path.exists(self.output_file_fragment):
            os.remove(self.output_file_fragment)
        if os.path.exists(self.output_file_fullmask):
            os.remove(self.output_file_fullmask)
        shutil.rmtree(os.path.join("output", "identity_docs"), ignore_errors=True)

    def test_request_and_verify_access_code_flow(self):
        issue = self.client.post(
            "/access/request-code",
            json={"jobId": "job_demo", "last4": "1234"},
        )
        self.assertEqual(issue.status_code, 200)
        issue_payload = issue.get_json()
        self.assertIn("oneTimeCode", issue_payload)

        verify = self.client.post(
            "/access/verify",
            json={
                "jobId": "job_demo",
                "last4": "1234",
                "code": issue_payload["oneTimeCode"],
            },
        )
        self.assertEqual(verify.status_code, 200)
        verify_payload = verify.get_json()
        self.assertIn("accessToken", verify_payload)
        self.assertIn("secureDownloadUrl", verify_payload)

        download = self.client.get(verify_payload["secureDownloadUrl"])
        self.assertEqual(download.status_code, 200)
        download.close()

    def test_request_code_with_wrong_last4_denied(self):
        issue = self.client.post(
            "/access/request-code",
            json={"jobId": "job_demo", "last4": "9999"},
        )
        self.assertEqual(issue.status_code, 403)

    def test_request_and_verify_visible_fragment_flow(self):
        issue = self.client.post(
            "/access/request-code",
            json={"jobId": "job_fragment", "visibleFragment": "AB12CD34"},
        )
        self.assertEqual(issue.status_code, 200)
        issue_payload = issue.get_json()
        self.assertIn("oneTimeCode", issue_payload)

        verify = self.client.post(
            "/access/verify",
            json={
                "jobId": "job_fragment",
                "visibleFragment": "AB12CD34",
                "code": issue_payload["oneTimeCode"],
            },
        )
        self.assertEqual(verify.status_code, 200)
        verify_payload = verify.get_json()
        self.assertIn("secureDownloadUrl", verify_payload)

    def test_request_and_verify_fallback_secret_flow(self):
        issue = self.client.post(
            "/access/request-code",
            json={"jobId": "job_fullmask", "fallbackPin": "panel-fallback-123"},
        )
        self.assertEqual(issue.status_code, 200)
        issue_payload = issue.get_json()
        self.assertIn("oneTimeCode", issue_payload)

        verify = self.client.post(
            "/access/verify",
            json={
                "jobId": "job_fullmask",
                "fallbackPin": "panel-fallback-123",
                "code": issue_payload["oneTimeCode"],
            },
        )
        self.assertEqual(verify.status_code, 200)

    def test_identity_unlock_and_retrieve_documents(self):
        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()
        self.assertIn("oneTimeOtp", otp_payload)

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity", "pin": "1234", "otp": otp_payload["oneTimeOtp"]},
        )
        self.assertEqual(unlock.status_code, 200)
        unlock_payload = unlock.get_json()
        self.assertIn("accessToken", unlock_payload)
        self.assertIn("documentsUrl", unlock_payload)

        documents = self.client.get(f"/identity/documents?token={unlock_payload['accessToken']}")
        self.assertEqual(documents.status_code, 200)
        documents_payload = documents.get_json()
        self.assertEqual(documents_payload["jobId"], "job_identity")
        self.assertGreaterEqual(len(documents_payload.get("linkedDocuments", [])), 3)

    def test_register_documents_endpoint(self):
        response = self.client.post(
            "/identity/register-documents",
            json={
                "aadhaarNumber": "555566667777",
                "documents": [
                    {"type": "pan", "id": "ABCDE1234F", "label": "PAN", "source": "vault"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_unlink_identity_document_endpoint(self):
        link_response = self.client.post(
            "/identity/link-documents",
            json={
                "jobId": "job_identity",
                "documents": [
                    {"type": "medical_certificate", "id": "MED-001", "label": "Medical Certificate", "source": "self-declared"},
                ],
            },
        )
        self.assertEqual(link_response.status_code, 200)

        unlink_response = self.client.post(
            "/identity/unlink-document",
            json={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-001",
                "label": "Medical Certificate",
            },
        )
        self.assertEqual(unlink_response.status_code, 200)
        payload = unlink_response.get_json()
        self.assertGreaterEqual(int(payload.get("removedCount", 0)), 1)

    def test_upload_identity_document_and_fetch_file(self):
        upload = self.client.post(
            "/identity/upload-document",
            data={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-UP-001",
                "label": "Medical Upload",
                "file": (BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"), "medical.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)
        upload_payload = upload.get_json()
        self.assertIn("document", upload_payload)
        self.assertTrue(upload_payload["document"].get("fileKey"))

        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity", "pin": "1234", "otp": otp_payload["oneTimeOtp"]},
        )
        self.assertEqual(unlock.status_code, 200)
        unlock_payload = unlock.get_json()

        documents = self.client.get(f"/identity/documents?token={unlock_payload['accessToken']}")
        self.assertEqual(documents.status_code, 200)
        docs_payload = documents.get_json()
        uploaded_docs = [
            item for item in docs_payload.get("linkedDocuments", []) if str(item.get("id", "")) == "MED-UP-001"
        ]
        self.assertTrue(uploaded_docs)
        self.assertIn("fileUrl", uploaded_docs[0])

        download = self.client.get(uploaded_docs[0]["fileUrl"])
        self.assertEqual(download.status_code, 200)
        download.close()

    def test_upload_identity_document_deduplicates_same_file(self):
        first = self.client.post(
            "/identity/upload-document",
            data={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-DUPE-001",
                "label": "Medical Duplicate",
                "file": (BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"), "dupe.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(first.status_code, 200)
        first_payload = first.get_json()

        second = self.client.post(
            "/identity/upload-document",
            data={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-DUPE-001",
                "label": "Medical Duplicate",
                "file": (BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"), "dupe_again.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(second.status_code, 200)
        second_payload = second.get_json()
        self.assertEqual(second_payload.get("message"), "Document already linked")
        self.assertEqual(int(second_payload.get("linkedCount", -1)), int(first_payload.get("linkedCount", -2)))

    def test_upload_identity_document_rejects_oversize_file(self):
        self.app.config.update(IDENTITY_DOC_MAX_BYTES=16)
        upload = self.client.post(
            "/identity/upload-document",
            data={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-BIG-001",
                "label": "Big Upload",
                "file": (BytesIO(b"%PDF-1.4\n0123456789ABCDEFZZZ"), "too_big.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 413)

    def test_upload_identity_document_rejects_extension_content_mismatch(self):
        upload = self.client.post(
            "/identity/upload-document",
            data={
                "jobId": "job_identity",
                "type": "medical_certificate",
                "id": "MED-MISMATCH-001",
                "label": "Mismatch Upload",
                "file": (BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"), "not_a_pdf.pdf"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 400)

    def test_identity_request_otp_respects_cooldown(self):
        self.app.config.update(IDENTITY_OTP_COOLDOWN_SECONDS=60)

        first = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(second.status_code, 429)
        payload = second.get_json()
        self.assertIn("retryAfterSec", payload)

    def test_linked_documents_recognized_on_new_job_same_person(self):
        with self.app.app_context():
            register_identity_vault(
                "job_seed_person",
                "123456781234",
                pin_mode="last4",
                linked_documents=[
                    {"type": "medical_certificate", "id": "MED-REUSE-001", "label": "Medical Certificate", "source": "self-declared"},
                ],
            )
            register_identity_vault(
                "job_identity_fresh",
                "123456781234",
                pin_mode="last4",
                linked_documents=[
                    {"type": "aadhaar", "id": "", "label": "Aadhaar", "source": "scanner"},
                ],
            )

        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity_fresh"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity_fresh", "pin": "1234", "otp": otp_payload["oneTimeOtp"]},
        )
        self.assertEqual(unlock.status_code, 200)
        unlock_payload = unlock.get_json()

        documents = self.client.get(f"/identity/documents?token={unlock_payload['accessToken']}")
        self.assertEqual(documents.status_code, 200)
        docs_payload = documents.get_json()
        labels = {str(item.get("label", "")) for item in docs_payload.get("linkedDocuments", [])}
        self.assertIn("Medical Certificate", labels)

    def test_identity_unlock_rejects_wrong_pin(self):
        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity", "pin": "9999", "otp": otp_payload["oneTimeOtp"]},
        )
        self.assertEqual(unlock.status_code, 401)

    def test_identity_unlock_rejects_wrong_otp(self):
        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity"},
        )
        self.assertEqual(otp_issue.status_code, 200)

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity", "pin": "1234", "otp": "000000"},
        )
        self.assertEqual(unlock.status_code, 401)

    def test_identity_request_otp_accepts_dynamic_recipient(self):
        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity", "recipientEmail": "user@example.com"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()
        self.assertEqual(otp_payload.get("target"), "user@example.com")

    def test_identity_request_otp_invalid_recipient_for_email_provider(self):
        self.app.config.update(IDENTITY_OTP_PROVIDER="email")

        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity", "recipientEmail": "bad-email"},
        )
        self.assertEqual(otp_issue.status_code, 502)

    def test_identity_unlock_pan_with_alphanumeric_pin(self):
        otp_issue = self.client.post(
            "/identity/request-otp",
            json={"jobId": "job_identity_pan"},
        )
        self.assertEqual(otp_issue.status_code, 200)
        otp_payload = otp_issue.get_json()
        self.assertIn("oneTimeOtp", otp_payload)

        unlock = self.client.post(
            "/identity/unlock",
            json={"jobId": "job_identity_pan", "pin": "ABCDE123", "otp": otp_payload["oneTimeOtp"]},
        )
        self.assertEqual(unlock.status_code, 200)


if __name__ == "__main__":
    unittest.main()
