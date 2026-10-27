from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import io
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

from app import create_app
from app.services import mask_service
from app.services.access_service import _reset_access_state_for_tests
from app.services.storage import S3Storage
from tests.test_storage import FakeS3Client

SECRET_TEXT = "AADHAAR 2345 6789 0124"


def make_pdf(pages, encrypt=False):
    doc = fitz.open()
    for number in range(1, pages + 1):
        page = doc.new_page()  # A4: 595 x 842 pt
        page.insert_text((72, 120), f"{SECRET_TEXT} page {number}")
    kwargs = {"encryption": fitz.PDF_ENCRYPT_AES_256, "user_pw": "pw", "owner_pw": "pw"} if encrypt else {}
    data = doc.tobytes(**kwargs)
    doc.close()
    return data


class FakeMasker:
    """Stands in for the OCR masker: 'detects' only on the given call numbers and paints a black box."""

    def __init__(self, detect_on):
        self.detect_on = set(detect_on)
        self.calls = 0

    def __call__(self, image_path, output_path, first8, last4):
        self.calls += 1
        if self.calls not in self.detect_on:
            return False, "", 0
        image = Image.open(image_path).convert("RGB")
        ImageDraw.Draw(image).rectangle([10, 10, 120, 60], fill="black")
        image.save(output_path)
        return True, "234567890124", 1


class PdfTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out_dir = os.path.join(self.tmp, "out")
        os.makedirs(self.out_dir)
        self.uploads = os.path.join(self.tmp, "uploads")

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            RATE_LIMIT_ENABLED=False,
            API_KEY_REQUIRED=False,
            UPLOAD_FOLDER=self.uploads,
            PERSIST_ORIGINAL_UPLOADS=False,
            ACCESS_SHOW_CODE=True,
            MAX_PDF_PAGES=20,
        )
        patcher = patch.object(mask_service, "OUTPUT_DIR", self.out_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"
        _reset_access_state_for_tests()

    def post_pdf(self, data, **fields):
        form = {"file": (io.BytesIO(data), "scan.pdf")}
        form.update(fields)
        return self.client.post("/mask/document", data=form, content_type="multipart/form-data")

    def mask(self, pages, detect_on, **fields):
        masker = FakeMasker(detect_on)
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=masker):
            response = self.post_pdf(make_pdf(pages), **fields)
        return response, masker


class MultiPageMaskingTests(PdfTestBase):
    def test_every_page_is_processed_and_reported(self):
        response, masker = self.mask(3, detect_on={2})
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["error"], "")
        self.assertEqual(masker.calls, 3)
        self.assertEqual(body["pageCount"], 3)
        self.assertEqual(body["maskedPages"], [2])
        self.assertTrue(body["outputPdfUrl"].endswith(".pdf"))
        self.assertTrue(body["outputImageUrl"].endswith(".jpg"))

    def test_masked_pdf_has_all_pages_and_the_mask_on_the_right_page(self):
        body, _ = self.mask(3, detect_on={2})[0].get_json(), None
        pdf_path = os.path.join(self.out_dir, os.path.basename(body["outputPdfUrl"]))
        with fitz.open(pdf_path) as doc:
            self.assertEqual(doc.page_count, 3)
            self.assertAlmostEqual(doc[0].rect.width, 595, delta=2)
            self.assertAlmostEqual(doc[0].rect.height, 842, delta=2)
            darkness = []
            for page in doc:
                pix = page.get_pixmap(dpi=72)
                darkness.append(sum(pix.pixel(20, 15)) / 3)
            self.assertLess(darkness[1], 40, "page 2 should carry the black box")
            self.assertGreater(darkness[0], 200)
            self.assertGreater(darkness[2], 200)

    def test_output_pdf_has_no_text_layer_so_the_number_cannot_be_copied(self):
        body = self.mask(2, detect_on={1})[0].get_json()
        with fitz.open(os.path.join(self.out_dir, os.path.basename(body["outputPdfUrl"]))) as doc:
            for page in doc:
                self.assertEqual(page.get_text().strip(), "")
            self.assertNotIn(SECRET_TEXT, " ".join(page.get_text() for page in doc))
            self.assertFalse(doc.metadata.get("title"))

    def test_page_one_preview_image_is_kept(self):
        body = self.mask(2, detect_on={1})[0].get_json()
        self.assertIn(os.path.basename(body["outputImageUrl"]), os.listdir(self.out_dir))
        self.assertIn(os.path.basename(body["outputPdfUrl"]), os.listdir(self.out_dir))

    def test_temp_files_and_original_upload_are_cleaned_up(self):
        before = set(os.listdir(tempfile.gettempdir()))
        self.mask(3, detect_on={1})
        self.assertEqual(os.listdir(self.uploads), [])
        leaked = [n for n in set(os.listdir(tempfile.gettempdir())) - before if n.startswith("sdm-pages-")]
        self.assertEqual(leaked, [])

    def test_nothing_detected_on_any_page_leaves_no_output(self):
        response, masker = self.mask(3, detect_on=set())
        self.assertEqual(response.get_json()["error"], "No supported document number detected")
        self.assertEqual(masker.calls, 3)
        self.assertEqual(os.listdir(self.out_dir), [])
        self.assertEqual(os.listdir(self.uploads), [])

    def test_detection_only_on_a_later_page_still_succeeds(self):
        body = self.mask(3, detect_on={3})[0].get_json()
        self.assertEqual(body["maskedPages"], [3])
        self.assertTrue(body["outputPdfUrl"])

    def test_counts_are_summed_across_pages(self):
        body = self.mask(3, detect_on={1, 3})[0].get_json()
        self.assertEqual(body["noOfAadhaarDetected"], 2)
        self.assertEqual(body["maskedPages"], [1, 3])
        self.assertEqual(body["maskedRegions"]["aadhaar"], 2)

    def test_integrity_token_verifies_against_the_pdf_hash(self):
        body = self.mask(2, detect_on={1})[0].get_json()
        pdf_path = os.path.join(self.out_dir, os.path.basename(body["outputPdfUrl"]))
        from app.utils.hash_utils import hash_file_sha256

        self.assertEqual(body["outputFileHash"], hash_file_sha256(pdf_path))
        check = self.client.post(
            "/mask/verify-integrity",
            json={k: body[k] for k in ("jobId", "processedAt", "inputFileHash", "outputFileHash", "integrityToken")},
        )
        self.assertTrue(check.get_json()["valid"])


class SinglePageAndLimitsTests(PdfTestBase):
    def test_one_page_pdf_behaves_like_an_image(self):
        body = self.mask(1, detect_on={1})[0].get_json()
        self.assertEqual(body["pageCount"], 1)
        self.assertEqual(body["outputPdfUrl"], "")
        self.assertEqual([n for n in os.listdir(self.out_dir) if n.endswith(".pdf")], [])

    def test_pdf_over_the_page_limit_is_rejected_not_partially_processed(self):
        self.app.config.update(MAX_PDF_PAGES=2)
        response, masker = self.mask(3, detect_on={1, 2, 3})
        body = response.get_json()
        self.assertEqual(body["error"], "pdf-too-many-pages")
        self.assertIn("3 pages", body["message"])
        self.assertEqual(body["pageCount"], 3)
        self.assertEqual(masker.calls, 0)
        self.assertEqual(os.listdir(self.out_dir), [])
        self.assertEqual(os.listdir(self.uploads), [])

    def test_password_protected_pdf_is_rejected(self):
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar") as masker:
            body = self.post_pdf(make_pdf(2, encrypt=True)).get_json()
        self.assertEqual(body["error"], "pdf-conversion-failed")
        self.assertIn("password", body["message"].lower())
        masker.assert_not_called()
        self.assertEqual(os.listdir(self.uploads), [])

    def test_page_limit_is_configurable_and_clamped(self):
        from app.config import Config

        self.assertGreaterEqual(Config.MAX_PDF_PAGES, 1)
        self.assertLessEqual(Config.MAX_PDF_PAGES, 100)

    def test_conversion_helper_cleans_up_when_over_limit(self):
        path = os.path.join(self.tmp, "x.pdf")
        with open(path, "wb") as handle:
            handle.write(make_pdf(4))
        before = set(os.listdir(tempfile.gettempdir()))
        with self.assertRaises(mask_service.PdfPageLimitError) as ctx:
            mask_service._convert_pdf_pages_to_jpgs(path, 3)
        self.assertEqual((ctx.exception.page_count, ctx.exception.max_pages), (4, 3))
        leaked = [n for n in set(os.listdir(tempfile.gettempdir())) - before if n.endswith(".jpg")]
        self.assertEqual(leaked, [])


class PdfAccessControlTests(PdfTestBase):
    def test_owner_can_download_the_pdf_and_strangers_cannot(self):
        body = self.mask(2, detect_on={1})[0].get_json()
        owner = self.client.get(body["outputPdfUrl"])
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.mimetype, "application/pdf")
        self.assertTrue(owner.data.startswith(b"%PDF"))

        stranger = self.app.test_client()
        with stranger.session_transaction() as sess:
            sess["auth_user"] = "someone-else"
        self.assertEqual(stranger.get(body["outputPdfUrl"]).status_code, 403)

    def test_secure_flow_serves_both_the_image_and_the_pdf(self):
        body = self.mask(2, detect_on={1})[0].get_json()
        self.assertTrue(body["accessChallengeAvailable"])
        issued = self.client.post("/access/request-code", json={"jobId": body["jobId"], "last4": "0124"})
        self.assertEqual(issued.status_code, 200)
        verified = self.client.post(
            "/access/verify",
            json={"jobId": body["jobId"], "last4": "0124", "code": issued.get_json()["oneTimeCode"]},
        ).get_json()
        self.assertIn("securePdfDownloadUrl", verified)

        image = self.client.get(verified["secureDownloadUrl"])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.mimetype, "image/jpeg")
        pdf = self.client.get(verified["securePdfDownloadUrl"])
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))

    def test_single_image_jobs_have_no_pdf_link(self):
        masker = FakeMasker({1})
        buffer = io.BytesIO()
        Image.new("RGB", (200, 100), "white").save(buffer, "PNG")
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=masker):
            body = self.client.post(
                "/mask/document",
                data={"file": (io.BytesIO(buffer.getvalue()), "card.png")},
                content_type="multipart/form-data",
            ).get_json()
        issued = self.client.post("/access/request-code", json={"jobId": body["jobId"], "last4": "0124"})
        verified = self.client.post(
            "/access/verify",
            json={"jobId": body["jobId"], "last4": "0124", "code": issued.get_json()["oneTimeCode"]},
        ).get_json()
        self.assertNotIn("securePdfDownloadUrl", verified)
        self.assertEqual(body["pageCount"], 1)

    def test_token_without_pdf_cannot_request_pdf_format(self):
        from app.services.access_service import resolve_secure_output_filename
        from itsdangerous import URLSafeTimedSerializer

        with self.app.app_context():
            token = URLSafeTimedSerializer(self.app.config["SECRET_KEY"], salt="aadhaar-output-access").dumps(
                {"jobId": "j", "outputImageUrl": "/output/masked_j.jpg"}
            )
            with self.assertRaises(ValueError):
                resolve_secure_output_filename(token, "pdf")


class PdfRemoteStorageTests(PdfTestBase):
    def test_pdf_and_preview_go_to_the_bucket_and_are_served_from_it(self):
        fake = FakeS3Client(page_size=3)
        self.app.extensions["remote_storage"] = S3Storage(bucket="b", prefix="t", client=fake)
        body = self.mask(2, detect_on={1})[0].get_json()

        job = body["jobId"]
        self.assertEqual(fake.objects[f"t/masked/masked_{job}.pdf"]["extra"]["ContentType"], "application/pdf")
        self.assertEqual(fake.objects[f"t/masked/masked_{job}.jpg"]["extra"]["ContentType"], "image/jpeg")
        self.assertEqual(os.listdir(self.out_dir), [])

        served = self.client.get(body["outputPdfUrl"])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, "application/pdf")
        self.assertTrue(served.data.startswith(b"%PDF"))

    def test_storage_outage_leaves_nothing_behind(self):
        fake = FakeS3Client()
        fake.fail = True
        self.app.extensions["remote_storage"] = S3Storage(bucket="b", client=fake)
        masker = FakeMasker({1})
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=masker):
            response = self.post_pdf(make_pdf(2))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(os.listdir(self.out_dir), [])


if __name__ == "__main__":
    unittest.main()
