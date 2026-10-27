from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import io
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask

from app import _apply_runtime_guardrails, create_app
from app.services import mask_service
from app.services.access_service import _reset_access_state_for_tests, register_identity_vault
from app.services.storage import S3Storage, StorageError, init_storage
from app.services.storage_cleanup import cleanup_storage

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"


def _local_files(root):
    return [os.path.join(r, f) for r, _, files in os.walk(root) for f in files]


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3Client:
    """In-memory stand-in for the boto3 S3 client methods the app uses."""

    def __init__(self, page_size=2):
        self.objects = {}
        self.page_size = page_size
        self.fail = False

    def _check(self):
        if self.fail:
            raise FakeClientError("InternalError")

    def put_object(self, Bucket, Key, Body, **extra):
        self._check()
        self.objects[Key] = {"body": Body, "extra": extra, "modified": datetime.now(timezone.utc)}

    def get_object(self, Bucket, Key):
        self._check()
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Key]["body"])}

    def delete_object(self, Bucket, Key):
        self._check()
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        self._check()
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + self.page_size]
        more = start + self.page_size < len(keys)
        return {
            "Contents": [
                {"Key": k, "Size": len(self.objects[k]["body"]), "LastModified": self.objects[k]["modified"]} for k in page
            ],
            "IsTruncated": more,
            "NextContinuationToken": str(start + self.page_size) if more else None,
        }

    def head_bucket(self, Bucket):
        self._check()


class S3StorageUnitTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeS3Client()
        self.store = S3Storage(bucket="b", prefix="/docmask/", client=self.client)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _file(self, data=b"hello"):
        path = os.path.join(self.tmp, "f.bin")
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_key_joins_prefix_and_parts(self):
        self.assertEqual(self.store.key("masked", "a.jpg"), "docmask/masked/a.jpg")
        self.assertEqual(S3Storage(bucket="b", client=self.client).key("/x/", "y"), "x/y")

    def test_put_and_get_round_trip_with_encryption_header(self):
        self.store.put_file(self._file(b"secret"), "docmask/k", "image/jpeg")
        self.assertEqual(self.store.get_bytes("docmask/k"), b"secret")
        extra = self.client.objects["docmask/k"]["extra"]
        self.assertEqual(extra["ServerSideEncryption"], "AES256")
        self.assertEqual(extra["ContentType"], "image/jpeg")

    def test_encryption_header_can_be_disabled(self):
        store = S3Storage(bucket="b", sse="", client=self.client)
        store.put_file(self._file(), "k")
        self.assertNotIn("ServerSideEncryption", self.client.objects["k"]["extra"])

    def test_missing_object_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.store.get_bytes("nope")

    def test_backend_errors_become_storage_error(self):
        self.client.fail = True
        with self.assertRaises(StorageError):
            self.store.put_file(self._file(), "k")
        with self.assertRaises(StorageError):
            self.store.get_bytes("k")
        with self.assertRaises(StorageError):
            self.store.delete("k")
        with self.assertRaises(StorageError):
            self.store.find_first_by_prefix("k")

    def test_missing_local_file_is_a_storage_error(self):
        with self.assertRaises(StorageError):
            self.store.put_file(os.path.join(self.tmp, "absent"), "k")

    def test_delete_and_ping(self):
        self.store.put_file(self._file(), "k")
        self.store.delete("k")
        self.assertNotIn("k", self.client.objects)
        self.assertTrue(self.store.ping())
        self.client.fail = True
        self.assertFalse(self.store.ping())

    def test_listing_handles_pagination(self):
        for i in range(5):
            self.store.put_file(self._file(b"x" * (i + 1)), f"docmask/masked/{i}.jpg")
        self.store.put_file(self._file(), "docmask/other/z")
        self.assertEqual(self.store.usage("docmask/masked/"), (5, 15))
        self.assertTrue(self.store.find_first_by_prefix("docmask/masked/3").endswith("3.jpg"))
        self.assertEqual(self.store.find_first_by_prefix("docmask/nothing"), "")

    def test_delete_older_than_only_removes_old_objects(self):
        self.store.put_file(self._file(), "p/old1")
        self.store.put_file(self._file(), "p/old2")
        self.store.put_file(self._file(), "p/new")
        old = datetime.now(timezone.utc) - timedelta(days=40)
        self.client.objects["p/old1"]["modified"] = old
        self.client.objects["p/old2"]["modified"] = old
        removed = self.store.delete_older_than("p/", time.time() - 30 * 86400)
        self.assertEqual(removed, 2)
        self.assertEqual(sorted(self.client.objects), ["p/new"])


class RemoteStorageAppTestBase(unittest.TestCase):
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
            IDENTITY_REQUIRE_OTP=True,
            IDENTITY_SHOW_OTP=True,
            IDENTITY_OTP_PROVIDER="demo",
            IDENTITY_OTP_COOLDOWN_SECONDS=0,
        )
        self.fake = FakeS3Client(page_size=3)
        self.app.extensions["remote_storage"] = S3Storage(bucket="b", prefix="t", client=self.fake)
        patcher = patch.object(mask_service, "OUTPUT_DIR", self.out_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess["auth_user"] = "test-user"
        _reset_access_state_for_tests()

    def _post_mask(self, **fields):
        data = {"file": (io.BytesIO(PNG_BYTES), "card.png")}
        data.update(fields)
        return self.client.post("/mask/document", data=data, content_type="multipart/form-data")

    @staticmethod
    def _fake_aadhaar_mask(image_path, output_path, first8, last4):
        shutil.copy(image_path, output_path)
        return True, "234567890124", 1


class MaskedOutputStorageTests(RemoteStorageAppTestBase):
    def test_masked_output_moves_to_bucket_and_is_served_to_owner_only(self):
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=self._fake_aadhaar_mask):
            response = self._post_mask()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        name = os.path.basename(body["outputImageUrl"])
        self.assertIn(f"t/masked/{name}", self.fake.objects)
        self.assertEqual(self.fake.objects[f"t/masked/{name}"]["extra"]["ContentType"], "image/jpeg")
        self.assertEqual(os.listdir(self.out_dir), [])

        owner = self.client.get(body["outputImageUrl"])
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.data, PNG_BYTES)

        stranger = self.app.test_client()
        with stranger.session_transaction() as sess:
            sess["auth_user"] = "someone-else"
        self.assertEqual(stranger.get(body["outputImageUrl"]).status_code, 403)

    def test_secure_token_flow_streams_from_bucket(self):
        from app.services.access_service import register_job_for_access

        self.fake.put_object("b", "t/masked/masked_job1.jpg", b"jpegdata")
        with self.app.app_context():
            register_job_for_access("job1", "XXXXXXXX1234", "/output/masked_job1.jpg")
        issued = self.client.post("/access/request-code", json={"jobId": "job1", "last4": "1234"})
        self.assertEqual(issued.status_code, 200)
        verified = self.client.post(
            "/access/verify", json={"jobId": "job1", "last4": "1234", "code": issued.get_json()["oneTimeCode"]}
        )
        self.assertEqual(verified.status_code, 200)
        fetched = self.client.get(verified.get_json()["secureDownloadUrl"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.data, b"jpegdata")

    def test_missing_object_is_404(self):
        with self.client.session_transaction() as sess:
            sess["owned_outputs"] = ["masked_gone.jpg"]
        self.assertEqual(self.client.get("/output/masked_gone.jpg").status_code, 404)

    def test_storage_outage_returns_502_and_leaves_no_local_copy(self):
        self.fake.fail = True
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=self._fake_aadhaar_mask):
            response = self._post_mask()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(os.listdir(self.out_dir), [])
        self.assertEqual(self.fake.objects, {})

    def test_nothing_detected_leaves_no_unmasked_copy_remote(self):
        not_found = (False, False, 0, 0, "", "", 0.0, 0.0, "", "")
        with patch("app.services.mask_utils.document_generic.mask_pan_and_driving_licence", return_value=not_found):
            response = self._post_mask(document_type="pan")
        self.assertEqual(response.get_json()["error"], "No supported document number detected")
        self.assertEqual(os.listdir(self.out_dir), [])
        self.assertEqual(self.fake.objects, {})

    def test_nothing_detected_leaves_no_unmasked_copy_local(self):
        self.app.extensions["remote_storage"] = None
        not_found = (False, False, 0, 0, "", "", 0.0, 0.0, "", "")
        with patch("app.services.mask_utils.document_generic.mask_pan_and_driving_licence", return_value=not_found):
            self._post_mask(document_type="pan")
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_local_mode_keeps_masked_file_on_disk(self):
        self.app.extensions["remote_storage"] = None
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", side_effect=self._fake_aadhaar_mask):
            response = self._post_mask()
        name = os.path.basename(response.get_json()["outputImageUrl"])
        self.assertEqual(os.listdir(self.out_dir), [name])

    def test_failed_pdf_conversion_deletes_the_uploaded_original(self):
        with patch.object(mask_service, "_convert_pdf_first_page_to_jpg", side_effect=RuntimeError("bad pdf")):
            response = self.client.post(
                "/mask/document",
                data={"file": (io.BytesIO(PDF_BYTES), "scan.pdf")},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.get_json()["error"], "pdf-conversion-failed")
        self.assertEqual(os.listdir(self.uploads), [])

    def test_persisted_original_is_moved_to_bucket(self):
        self.app.config.update(PERSIST_ORIGINAL_UPLOADS=True, ORIGINAL_UPLOADS_DIR=self.uploads)
        with patch("app.services.mask_utils.aadhaar.mask_aadhaar", return_value=(False, "", 0)):
            self._post_mask()
        keys = [k for k in self.fake.objects if k.startswith("t/uploads/")]
        self.assertEqual(len(keys), 1)
        self.assertEqual(os.listdir(self.uploads), [])


class VaultDocumentStorageTests(RemoteStorageAppTestBase):
    def _unlock(self, job_id):
        otp = self.client.post("/identity/request-otp", json={"jobId": job_id}).get_json()["oneTimeOtp"]
        response = self.client.post("/identity/unlock", json={"jobId": job_id, "pin": "1234", "otp": otp})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["accessToken"]

    def test_job_flow_upload_download_and_delete_use_the_bucket(self):
        with self.app.app_context():
            register_identity_vault("job_vault", "123456781234", pin_mode="last4", linked_documents=[])
        upload = self.client.post(
            "/identity/upload-document",
            data={"jobId": "job_vault", "type": "medical", "id": "M-1", "file": (io.BytesIO(PDF_BYTES), "med.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)
        keys = [k for k in self.fake.objects if k.startswith("t/identity_docs/job_vault/")]
        self.assertEqual(len(keys), 1)
        self.assertEqual(self.fake.objects[keys[0]]["extra"]["ServerSideEncryption"], "AES256")
        self.assertEqual(_local_files(self.app.config["IDENTITY_DOCS_DIR"]), [])

        token = self._unlock("job_vault")
        listing = self.client.get(f"/identity/documents?token={token}").get_json()
        uploaded = [d for d in listing["linkedDocuments"] if d.get("id") == "M-1"][0]
        self.assertNotIn("filePath", uploaded)
        self.assertNotIn("storageKey", uploaded)

        download = self.client.get(uploaded["fileUrl"])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, PDF_BYTES)

        removed = self.client.post(
            "/identity/unlink-document", json={"jobId": "job_vault", "type": "medical", "id": "M-1"}
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual([k for k in self.fake.objects if k.startswith("t/identity_docs/")], [])

    def test_duplicate_upload_does_not_leave_an_orphan_object(self):
        with self.app.app_context():
            register_identity_vault("job_dupe", "123456781234", pin_mode="last4", linked_documents=[])
        for name in ("a.pdf", "b.pdf"):
            self.client.post(
                "/identity/upload-document",
                data={"jobId": "job_dupe", "type": "medical", "id": "M-2", "file": (io.BytesIO(PDF_BYTES), name)},
                content_type="multipart/form-data",
            )
        self.assertEqual(len([k for k in self.fake.objects if k.startswith("t/identity_docs/job_dupe/")]), 1)

    def test_upload_failure_when_storage_is_down_returns_502(self):
        with self.app.app_context():
            register_identity_vault("job_down", "123456781234", pin_mode="last4", linked_documents=[])
        self.fake.fail = True
        upload = self.client.post(
            "/identity/upload-document",
            data={"jobId": "job_down", "type": "medical", "id": "M-3", "file": (io.BytesIO(PDF_BYTES), "m.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 502)

    def test_profile_flow_upload_and_download(self):
        upload = self.client.post(
            "/identity/upload-document",
            data={"profileKey": "prof_1", "type": "pan", "id": "P1", "file": (io.BytesIO(PDF_BYTES), "pan.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 200)
        file_key = upload.get_json()["document"]["fileKey"]
        self.assertTrue(any(k.startswith(f"t/identity_docs/prof_1/{file_key}_") for k in self.fake.objects))
        self.assertEqual(_local_files(self.app.config["IDENTITY_DOCS_DIR"]), [])

        download = self.client.get(f"/identity/document-file?profileKey=prof_1&file={file_key}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, PDF_BYTES)
        self.assertEqual(self.client.get("/identity/document-file?profileKey=prof_1&file=unknownkey").status_code, 404)

    def test_profile_key_path_traversal_is_rejected(self):
        upload = self.client.post(
            "/identity/upload-document",
            data={"profileKey": "../evil", "type": "pan", "file": (io.BytesIO(PDF_BYTES), "pan.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(upload.status_code, 400)
        self.assertEqual(self.fake.objects, {})


class CleanupAndHealthTests(RemoteStorageAppTestBase):
    def test_cleanup_removes_only_old_remote_objects(self):
        tmp_app = Flask(__name__, root_path=os.path.join(self.tmp, "app"))
        tmp_app.config.update(
            STORAGE_CLEANUP_ENABLED=True,
            STORAGE_RETENTION_DAYS=30,
            ORIGINAL_UPLOADS_DIR=os.path.join(self.tmp, "u"),
            IDENTITY_DOCS_DIR=os.path.join(self.tmp, "i"),
        )
        store = S3Storage(bucket="b", prefix="t", client=self.fake)
        tmp_app.extensions["remote_storage"] = store
        for key in ("t/masked/old.jpg", "t/identity_docs/p/old", "t/uploads/old", "t/masked/new.jpg"):
            self.fake.put_object("b", key, b"x")
        long_ago = datetime.now(timezone.utc) - timedelta(days=45)
        for key in ("t/masked/old.jpg", "t/identity_docs/p/old", "t/uploads/old"):
            self.fake.objects[key]["modified"] = long_ago

        with tmp_app.app_context():
            summary = cleanup_storage(tmp_app)
        self.assertEqual(summary["deletedFiles"], 3)
        self.assertEqual(sorted(self.fake.objects), ["t/masked/new.jpg"])

    def test_cleanup_survives_storage_errors(self):
        tmp_app = Flask(__name__, root_path=os.path.join(self.tmp, "app"))
        tmp_app.config.update(
            STORAGE_CLEANUP_ENABLED=True,
            ORIGINAL_UPLOADS_DIR=os.path.join(self.tmp, "u"),
            IDENTITY_DOCS_DIR=os.path.join(self.tmp, "i"),
        )
        tmp_app.extensions["remote_storage"] = S3Storage(bucket="b", client=self.fake)
        self.fake.fail = True
        with tmp_app.app_context():
            self.assertTrue(cleanup_storage(tmp_app)["enabled"])

    def test_health_details_reports_remote_backend(self):
        storage = self.client.get("/health/details").get_json()["system"]["storage"]
        self.assertEqual(storage["backend"], "s3")
        self.assertEqual(storage["remote"], {"bucket": "b", "reachable": True, "encryption": "AES256"})
        self.fake.fail = True
        storage = self.client.get("/health/details").get_json()["system"]["storage"]
        self.assertFalse(storage["remote"]["reachable"])

    def test_health_details_for_local_backend(self):
        self.app.extensions["remote_storage"] = None
        storage = self.client.get("/health/details").get_json()["system"]["storage"]
        self.assertEqual(storage["backend"], "local")
        self.assertIsNone(storage["remote"])


class StorageConfigTests(unittest.TestCase):
    def test_local_backend_has_no_remote(self):
        app = Flask(__name__)
        app.config.update(STORAGE_BACKEND="local")
        init_storage(app)
        self.assertIsNone(app.extensions["remote_storage"])

    def test_unknown_backend_is_rejected(self):
        app = Flask(__name__)
        app.config.update(STORAGE_BACKEND="ftp")
        with self.assertRaises(RuntimeError):
            init_storage(app)

    def test_s3_requires_bucket(self):
        app = Flask(__name__)
        app.config.update(STORAGE_BACKEND="s3", S3_BUCKET="")
        with self.assertRaises(RuntimeError):
            init_storage(app)

    def test_s3_backend_is_built_from_config(self):
        app = Flask(__name__)
        app.config.update(STORAGE_BACKEND="s3", S3_BUCKET="docs", S3_PREFIX="x", S3_SSE="", S3_ENDPOINT_URL="https://r2.example.com")
        init_storage(app)
        store = app.extensions["remote_storage"]
        self.assertEqual((store.bucket, store.prefix, store.sse, store.endpoint_url), ("docs", "x", "", "https://r2.example.com"))

    def test_real_client_is_built_lazily_without_network(self):
        store = S3Storage(bucket="b", region="us-east-1", endpoint_url="https://r2.example.com", access_key_id="k", secret_access_key="s", force_path_style=True)
        self.assertIsNotNone(store.client)

    def _prod_app(self, **config):
        app = Flask(__name__)
        app.config.update(
            PRODUCTION=True, SECRET_KEY="s", HASH_SECRET="h", AUTH_PROVIDER="local", USER_PASSWORD="a-long-unique-passphrase",
            API_KEY_REQUIRED=False, HEALTH_DETAILS_TOKEN="t", ACCESS_SHOW_CODE=False, IDENTITY_SHOW_OTP=False,
            IDENTITY_OTP_PROVIDER="email", OTP_EMAIL_SMTP_HOST="smtp.example.net", OTP_EMAIL_USERNAME="m@example.net",
            OTP_EMAIL_PASSWORD="real-secret", OTP_EMAIL_FROM="m@example.net",
        )
        app.config.update(config)
        return app

    def test_production_s3_requires_credentials(self):
        env = {"SECRET_KEY": "s", "HASH_SECRET": "h"}
        with patch.dict(os.environ, env), patch.dict(os.environ, {}, clear=False):
            for name in ("AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_ROLE_ARN", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
                os.environ.pop(name, None)
            with self.assertRaises(RuntimeError):
                _apply_runtime_guardrails(self._prod_app(STORAGE_BACKEND="s3", S3_BUCKET="b"))
            _apply_runtime_guardrails(
                self._prod_app(STORAGE_BACKEND="s3", S3_BUCKET="b", S3_ACCESS_KEY_ID="k", S3_SECRET_ACCESS_KEY="s")
            )


if __name__ == "__main__":
    unittest.main()
