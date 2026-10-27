import os
import tempfile
import importlib.util

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("health", __name__)


def _output_write_check(output_dir):
    try:
        os.makedirs(output_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, delete=True):
            pass
        return True
    except Exception:
        return False


def _ocr_check():
    try:
        import pytesseract

        configured_cmd = str(current_app.config.get("TESSERACT_CMD", os.environ.get("TESSERACT_CMD", "")) or "").strip()
        if configured_cmd:
            pytesseract.pytesseract.tesseract_cmd = configured_cmd

        _ = str(pytesseract.get_tesseract_version())
        return True
    except Exception:
        return False


def _sample_assets_check(samples_dir):
    try:
        files = [name for name in os.listdir(samples_dir) if name.lower().endswith((".png", ".jpg", ".jpeg"))]
        return len(files) >= 3
    except Exception:
        return False


def _qreader_check():
    if bool(current_app.config.get("STRICT_QREADER_IMPORT", False)):
        try:
            from qreader import QReader  # noqa: F401

            return True
        except Exception:
            return False

    return importlib.util.find_spec("qreader") is not None


def _pdf_renderer_check():
    return importlib.util.find_spec("fitz") is not None


def _access_state_health(output_dir):
    configured_path = str(current_app.config.get("ACCESS_STATE_DB_PATH", "") or "").strip()
    db_path = configured_path or os.path.join(output_dir, "access_state.sqlite3")
    return {
        "persistEnabled": bool(current_app.config.get("ACCESS_STATE_PERSIST", True)),
        "dbPath": os.path.abspath(db_path),
    }


def _identity_documents_health():
    configured = current_app.config.get("IDENTITY_DOC_MAX_BYTES", 5 * 1024 * 1024)
    try:
        max_bytes = max(1, int(configured))
    except (TypeError, ValueError):
        max_bytes = 5 * 1024 * 1024

    return {
        "maxBytes": max_bytes,
        "allowedExtensions": ["pdf", "png", "jpg", "jpeg"],
    }


def _directory_usage_stats(path):
    abs_path = os.path.abspath(str(path or ""))
    if not abs_path or not os.path.isdir(abs_path):
        return {
            "path": abs_path,
            "exists": False,
            "fileCount": 0,
            "totalBytes": 0,
        }

    file_count = 0
    total_bytes = 0

    for root, _, files in os.walk(abs_path):
        for filename in files:
            candidate = os.path.join(root, filename)
            try:
                size = os.path.getsize(candidate)
            except OSError:
                continue
            file_count += 1
            total_bytes += int(size)

    return {
        "path": abs_path,
        "exists": True,
        "fileCount": file_count,
        "totalBytes": total_bytes,
    }


def _storage_health(output_dir):
    uploads_dir = os.path.abspath(
        str(current_app.config.get("ORIGINAL_UPLOADS_DIR", os.path.join("output", "uploads")) or "")
    )
    identity_docs_dir = os.path.abspath(os.path.join(output_dir, "identity_docs"))

    try:
        retention_days = max(1, int(current_app.config.get("STORAGE_RETENTION_DAYS", 30)))
    except (TypeError, ValueError):
        retention_days = 30

    return {
        "cleanupEnabled": bool(current_app.config.get("STORAGE_CLEANUP_ENABLED", False)),
        "cleanupAtStartup": bool(current_app.config.get("STORAGE_CLEANUP_AT_STARTUP", True)),
        "retentionDays": retention_days,
        "persistOriginalUploads": bool(current_app.config.get("PERSIST_ORIGINAL_UPLOADS", False)),
        "directories": {
            "output": _directory_usage_stats(output_dir),
            "originalUploads": _directory_usage_stats(uploads_dir),
            "identityDocuments": _directory_usage_stats(identity_docs_dir),
        },
    }


def _runtime_profile_health():
    access_show_code = bool(current_app.config.get("ACCESS_SHOW_CODE", False))
    identity_show_otp = bool(current_app.config.get("IDENTITY_SHOW_OTP", False))
    otp_provider = str(current_app.config.get("IDENTITY_OTP_PROVIDER", "") or "").strip().lower()
    production = bool(current_app.config.get("PRODUCTION", False))

    warnings = []
    if access_show_code:
        warnings.append("ACCESS_SHOW_CODE is enabled")
    if identity_show_otp:
        warnings.append("IDENTITY_SHOW_OTP is enabled")
    if otp_provider == "demo":
        warnings.append("IDENTITY_OTP_PROVIDER is set to demo")

    return {
        "production": production,
        "demoProfileActive": bool(warnings),
        "warnings": warnings,
    }


def _is_details_authorized():
    if bool(current_app.config.get("TESTING", False)):
        return True

    token = str(current_app.config.get("HEALTH_DETAILS_TOKEN", "") or "").strip()
    if token:
        presented = str(request.headers.get("X-Health-Token", "") or "").strip()
        return presented == token

    api_key_required = bool(current_app.config.get("API_KEY_REQUIRED", False))
    api_key = str(current_app.config.get("API_KEY", "") or "").strip()
    if api_key_required and api_key:
        presented = str(request.headers.get("X-API-Key", "") or "").strip()
        return presented == api_key

    # In non-production environments allow unauthenticated details for local diagnostics.
    return not bool(current_app.config.get("PRODUCTION", False))


def _detailed_payload(output_dir, samples_dir):
    return {
        "status": "UP",
        "service": "smart-document-masking",
        "version": "1.1.0",
        "security": {
            "apiKeyRequired": bool(current_app.config.get("API_KEY_REQUIRED", False)),
            "rateLimitEnabled": bool(current_app.config.get("RATE_LIMIT_ENABLED", True)),
            "returnRawAadhaar": bool(current_app.config.get("RETURN_RAW_AADHAAR", False)),
        },
        "system": {
            "ocrReady": _ocr_check(),
            "outputWritable": _output_write_check(output_dir),
            "sampleAssetsReady": _sample_assets_check(samples_dir),
            "qreaderReady": _qreader_check(),
            "pdfRendererReady": _pdf_renderer_check(),
            "accessState": _access_state_health(output_dir),
            "identityDocuments": _identity_documents_health(),
            "storage": _storage_health(output_dir),
        },
        "runtime": _runtime_profile_health(),
    }


def _public_payload():
    return {
        "status": "UP",
        "service": "smart-document-masking",
        "version": "1.1.0",
    }


@bp.route("/health", methods=["GET"])
def health():
    return jsonify(_public_payload())


@bp.route("/health/details", methods=["GET"])
def health_details():
    output_dir = os.path.abspath(os.path.join(current_app.root_path, "..", "output"))
    samples_dir = os.path.join(current_app.root_path, "static", "samples")

    if not _is_details_authorized():
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify(_detailed_payload(output_dir, samples_dir))
