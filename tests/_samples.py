"""Small genuine files for upload tests (libmagic on Linux needs real headers, not just a signature)."""
import io

from PIL import Image


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    return buffer.getvalue()


PNG_BYTES = _png()
