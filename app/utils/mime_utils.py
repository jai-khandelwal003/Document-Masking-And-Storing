import os
from typing import BinaryIO


def _should_use_python_magic() -> bool:
    # python-magic/libmagic can hang or crash on some Windows setups.
    # Keep it opt-in on Windows, opt-out elsewhere.
    env_value = str(os.environ.get("MIME_USE_PYTHON_MAGIC", "")).strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    if env_value in {"0", "false", "no", "off"}:
        return False
    return os.name != "nt"


def detect_mime_from_stream(stream: BinaryIO) -> str:
    try:
        current = stream.tell()
    except Exception:
        current = None

    head = b""
    try:
        head = stream.read(4096)
    finally:
        if current is not None:
            try:
                stream.seek(current)
            except Exception:
                pass

    if not head:
        return ""

    if _should_use_python_magic():
        try:
            import magic  # type: ignore

            mime = str(magic.from_buffer(head, mime=True) or "").strip().lower()
            if mime:
                return mime
        except Exception:
            pass

    # Fallback signatures when libmagic is unavailable
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    return ""


def is_allowed_upload_mime(mime_type: str) -> bool:
    allowed = {
        "application/pdf",
        "image/png",
        "image/jpeg",
    }
    return str(mime_type or "").strip().lower() in allowed
