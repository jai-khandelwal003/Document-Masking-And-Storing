import hashlib
import hmac


def _to_bytes(value):
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def hash_text_sha256(text: str, salt: str = "") -> str:
    """Return SHA-256 hash for a text value with optional salt."""
    payload = _to_bytes(text) + _to_bytes(salt)
    return hashlib.sha256(payload).hexdigest()


def hmac_sha256(text: str, secret: str) -> str:
    """Return HMAC-SHA256 for a text value using a secret key."""
    key = _to_bytes(secret)
    msg = _to_bytes(text)
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def hash_file_sha256(file_path: str, chunk_size: int = 8192) -> str:
    """Return SHA-256 hash for file content by streaming chunks."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()