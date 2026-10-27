"""Optional remote (S3-compatible) object storage for documents.

Local disk stays the default. With STORAGE_BACKEND=s3 the app still writes temporary files under
output/ while it works, then moves the result to the bucket and deletes the local copy.
Works with AWS S3, Cloudflare R2, Supabase Storage, MinIO and other S3-compatible services.
"""
import logging
import os

from flask import current_app, has_app_context

log = logging.getLogger(__name__)


class StorageError(Exception):
    pass


def _is_missing(exc):
    code = str(((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code", ""))
    return code in {"NoSuchKey", "404", "NotFound"}


class S3Storage:
    is_remote = True

    def __init__(
        self,
        bucket,
        prefix="",
        region="",
        endpoint_url="",
        access_key_id="",
        secret_access_key="",
        sse="AES256",
        force_path_style=False,
        client=None,
    ):
        self.bucket = str(bucket or "").strip()
        self.prefix = str(prefix or "").strip().strip("/")
        self.region = str(region or "").strip()
        self.endpoint_url = str(endpoint_url or "").strip()
        self.access_key_id = str(access_key_id or "").strip()
        self.secret_access_key = str(secret_access_key or "").strip()
        self.sse = str(sse or "").strip()
        self.force_path_style = bool(force_path_style)
        self._client = client

    @classmethod
    def from_config(cls, config):
        return cls(
            bucket=config.get("S3_BUCKET", ""),
            prefix=config.get("S3_PREFIX", ""),
            region=config.get("S3_REGION", ""),
            endpoint_url=config.get("S3_ENDPOINT_URL", ""),
            access_key_id=config.get("S3_ACCESS_KEY_ID", ""),
            secret_access_key=config.get("S3_SECRET_ACCESS_KEY", ""),
            sse=config.get("S3_SSE", "AES256"),
            force_path_style=config.get("S3_FORCE_PATH_STYLE", False),
        )

    def key(self, *parts):
        clean = [str(p).strip("/") for p in parts if str(p).strip("/")]
        return "/".join(([self.prefix] if self.prefix else []) + clean)

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            kwargs = {}
            if self.region:
                kwargs["region_name"] = self.region
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.access_key_id and self.secret_access_key:
                kwargs["aws_access_key_id"] = self.access_key_id
                kwargs["aws_secret_access_key"] = self.secret_access_key
            cfg = Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=30,
                s3={"addressing_style": "path"} if self.force_path_style else {},
            )
            self._client = boto3.client("s3", config=cfg, **kwargs)
        return self._client

    def put_file(self, local_path, key, content_type=""):
        extra = {}
        if self.sse:
            extra["ServerSideEncryption"] = self.sse
        if content_type:
            extra["ContentType"] = content_type
        try:
            with open(local_path, "rb") as handle:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=handle.read(), **extra)
        except OSError as exc:
            raise StorageError(f"Cannot read local file for upload: {exc}") from exc
        except Exception as exc:
            raise StorageError(f"Upload failed: {type(exc).__name__}") from exc

    def get_bytes(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            if _is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise StorageError(f"Download failed: {type(exc).__name__}") from exc

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise StorageError(f"Delete failed: {type(exc).__name__}") from exc

    def _iter_objects(self, prefix):
        token = None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            try:
                page = self.client.list_objects_v2(**kwargs)
            except Exception as exc:
                raise StorageError(f"List failed: {type(exc).__name__}") from exc
            for obj in page.get("Contents", []) or []:
                yield obj
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")

    def find_first_by_prefix(self, prefix):
        for obj in self._iter_objects(prefix):
            return obj["Key"]
        return ""

    def delete_older_than(self, prefix, cutoff_epoch):
        removed = 0
        for obj in list(self._iter_objects(prefix)):
            if obj["LastModified"].timestamp() <= cutoff_epoch:
                self.delete(obj["Key"])
                removed += 1
        return removed

    def usage(self, prefix):
        count = total = 0
        for obj in self._iter_objects(prefix):
            count += 1
            total += int(obj.get("Size", 0))
        return count, total

    def ping(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def identity_docs_root():
    """Local folder for identity-vault uploads (configurable so tests never touch real data)."""
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("IDENTITY_DOCS_DIR", "") or "").strip()
    else:
        configured = str(os.environ.get("IDENTITY_DOCS_DIR", "") or "").strip()
    return os.path.abspath(configured or os.path.join("output", "identity_docs"))


def init_storage(app):
    backend = str(app.config.get("STORAGE_BACKEND", "local") or "local").strip().lower()
    if backend == "local":
        app.extensions["remote_storage"] = None
        return
    if backend != "s3":
        raise RuntimeError("STORAGE_BACKEND must be 'local' or 's3'")
    if not str(app.config.get("S3_BUCKET", "") or "").strip():
        raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
    app.extensions["remote_storage"] = S3Storage.from_config(app.config)


def remote_storage():
    """Return the configured remote backend, or None when files stay on local disk."""
    if not has_app_context():
        return None
    return current_app.extensions.get("remote_storage")
