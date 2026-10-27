import os
import time
import hmac
import secrets
import threading
import json
import sqlite3
import shutil
from urllib.parse import quote

from flask import current_app, has_app_context
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from werkzeug.utils import secure_filename

from app.utils.hash_utils import hmac_sha256, hash_file_sha256
from app.services.otp_delivery_service import deliver_identity_otp, OtpDeliveryError


_ACCESS_LOCK = threading.Lock()
_JOB_ACCESS = {}
_ACCESS_CODES = {}
_IDENTITY_VAULT = {}
_IDENTITY_OTPS = {}
_PERSON_DOCUMENTS_BY_HASH = {}
_STATE_KEY = "access_state_v1"
_STATE_LOADED = False
_IDENTITY_FILE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}
_IDENTITY_ALLOWED_MIME = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg", "image/jpg"},
    "jpeg": {"image/jpeg", "image/jpg"},
}


def _identity_docs_root():
    return os.path.abspath(os.path.join("output", "identity_docs"))


def _safe_job_segment(job_id):
    safe = "".join(ch for ch in str(job_id or "") if ch.isalnum() or ch in {"-", "_"})
    return safe[:64] or "job"


def _identity_docs_dir(job_id):
    return os.path.join(_identity_docs_root(), _safe_job_segment(job_id))


def _document_file_allowed(filename):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].strip().lower()
    return extension in _IDENTITY_FILE_EXTENSIONS


def _identity_doc_max_bytes():
    try:
        return max(1, int(current_app.config.get("IDENTITY_DOC_MAX_BYTES", 5 * 1024 * 1024)))
    except (TypeError, ValueError):
        return 5 * 1024 * 1024


def _guess_file_type(header):
    sample = bytes(header or b"")
    if sample.startswith(b"%PDF-"):
        return "pdf"
    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if sample[:3] == b"\xff\xd8\xff":
        return "jpg"
    return ""


def _peek_stream(file_storage, size=16):
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return b""

    try:
        current = stream.tell()
        header = stream.read(size)
        stream.seek(current)
        return header
    except Exception:
        return b""


def _file_storage_size(file_storage):
    content_length = getattr(file_storage, "content_length", None)
    if isinstance(content_length, int) and content_length > 0:
        return content_length

    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return -1

    try:
        current = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(current)
        return int(size)
    except Exception:
        return -1


def _safe_file_remove(file_path):
    candidate = os.path.abspath(str(file_path or ""))
    root = _identity_docs_root()
    if not candidate or not candidate.startswith(root + os.sep):
        return
    if os.path.exists(candidate):
        os.remove(candidate)


def _state_persistence_enabled():
    if not has_app_context():
        return False
    return bool(current_app.config.get("ACCESS_STATE_PERSIST", True))


def _state_db_path():
    configured = ""
    if has_app_context():
        configured = str(current_app.config.get("ACCESS_STATE_DB_PATH", "") or "").strip()
    if configured:
        return configured
    return os.path.join("output", "access_state.sqlite3")


def _ensure_state_db():
    db_path = _state_db_path()
    folder = os.path.dirname(db_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _snapshot_state():
    return {
        "job_access": _JOB_ACCESS,
        "access_codes": _ACCESS_CODES,
        "identity_vault": _IDENTITY_VAULT,
        "identity_otps": _IDENTITY_OTPS,
        "person_documents_by_hash": _PERSON_DOCUMENTS_BY_HASH,
    }


def _restore_state(snapshot):
    global _JOB_ACCESS, _ACCESS_CODES, _IDENTITY_VAULT, _IDENTITY_OTPS, _PERSON_DOCUMENTS_BY_HASH

    payload = snapshot if isinstance(snapshot, dict) else {}
    _JOB_ACCESS = payload.get("job_access", {}) if isinstance(payload.get("job_access", {}), dict) else {}
    _ACCESS_CODES = payload.get("access_codes", {}) if isinstance(payload.get("access_codes", {}), dict) else {}
    _IDENTITY_VAULT = payload.get("identity_vault", {}) if isinstance(payload.get("identity_vault", {}), dict) else {}
    _IDENTITY_OTPS = payload.get("identity_otps", {}) if isinstance(payload.get("identity_otps", {}), dict) else {}
    _PERSON_DOCUMENTS_BY_HASH = (
        payload.get("person_documents_by_hash", {})
        if isinstance(payload.get("person_documents_by_hash", {}), dict)
        else {}
    )


def _save_state_locked():
    if not _state_persistence_enabled():
        return

    _ensure_state_db()
    serialized = json.dumps(_snapshot_state())
    with sqlite3.connect(_state_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO kv_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (_STATE_KEY, serialized),
        )
        conn.commit()


def _load_state_locked():
    global _STATE_LOADED

    if _STATE_LOADED:
        return
    _STATE_LOADED = True

    if not _state_persistence_enabled():
        return

    _ensure_state_db()
    with sqlite3.connect(_state_db_path()) as conn:
        row = conn.execute("SELECT value FROM kv_state WHERE key = ?", (_STATE_KEY,)).fetchone()

    if not row:
        return

    try:
        snapshot = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return

    _restore_state(snapshot)


def _clear_persisted_state_locked():
    if not _state_persistence_enabled():
        return
    _ensure_state_db()
    with sqlite3.connect(_state_db_path()) as conn:
        conn.execute("DELETE FROM kv_state WHERE key = ?", (_STATE_KEY,))
        conn.commit()


def _normalize_last4(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 4:
        return ""
    return digits[-4:]


def _normalize_challenge(value, min_len=4, max_len=16):
    normalized = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(normalized) < min_len or len(normalized) > max_len:
        return ""
    return normalized


def _normalize_fallback_pin(value):
    normalized = str(value or "").strip()
    if len(normalized) < 6:
        return ""
    return normalized


def _normalize_pin(pin_mode, value):
    mode = str(pin_mode or "last4").strip().lower()
    normalized = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if mode == "first8":
        if len(normalized) < 8:
            return ""
        return normalized[:8]
    if mode == "last4":
        if len(normalized) < 4:
            return ""
        return normalized[-4:]
    return ""


def _sanitize_documents(documents):
    cleaned = []
    for item in documents or []:
        if not isinstance(item, dict):
            continue
        doc_type = str(item.get("type", "")).strip().lower()
        doc_id = str(item.get("id", "")).strip()
        source = str(item.get("source", "scanner")).strip().lower() or "scanner"
        if not doc_type:
            continue
        cleaned.append(
            {
                "type": doc_type,
                "id": doc_id,
                "source": source,
                "label": str(item.get("label", doc_type.upper())).strip() or doc_type.upper(),
            }
        )
    return cleaned


def _token_payload_for_identity(access_token):
    token_ttl = max(30, int(current_app.config.get("ACCESS_TOKEN_TTL_SECONDS", 300)))
    serializer = URLSafeTimedSerializer(current_app.config.get("SECRET_KEY", ""), salt="identity-doc-access")

    try:
        payload = serializer.loads(str(access_token or ""), max_age=token_ttl)
    except SignatureExpired as exc:
        raise ValueError("Access token expired") from exc
    except BadSignature as exc:
        raise ValueError("Invalid access token") from exc

    if payload.get("scope") != "documents":
        raise ValueError("Invalid token scope")

    job_id = str(payload.get("jobId", "")).strip()
    if not job_id:
        raise ValueError("Invalid token payload")

    return payload


def _merge_documents(primary, secondary):
    merged = []
    seen = set()

    for item in list(primary or []) + list(secondary or []):
        if not isinstance(item, dict):
            continue
        doc_type = str(item.get("type", "")).strip().lower()
        doc_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        file_hash = str(item.get("fileHash", "")).strip().lower()
        if file_hash:
            key = ("fileHash", file_hash)
        elif doc_type and doc_id:
            key = ("doc", doc_type, doc_id)
        else:
            key = ("label", doc_type, label)
        if not doc_type or key in seen:
            continue
        merged.append(item)
        seen.add(key)

    return merged


def register_person_documents(document_number, documents):
    digits = "".join(ch for ch in str(document_number or "") if ch.isdigit())
    if len(digits) < 8:
        return False, {"error": "aadhaarNumber is invalid"}, 400

    docs = _sanitize_documents(documents)
    if not docs:
        return False, {"error": "documents must contain at least one valid document"}, 400

    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))
    lookup_key = hmac_sha256(digits, hash_secret)

    normalized_docs = []
    for item in docs:
        doc_item = dict(item)
        if not doc_item.get("source"):
            doc_item["source"] = "registry"
        normalized_docs.append(doc_item)

    with _ACCESS_LOCK:
        _load_state_locked()
        existing = _PERSON_DOCUMENTS_BY_HASH.get(lookup_key, [])
        _PERSON_DOCUMENTS_BY_HASH[lookup_key] = _merge_documents(existing, normalized_docs)
        _save_state_locked()

    return True, {
        "message": "Person documents registered",
        "documentHash": lookup_key,
        "linkedCount": len(_PERSON_DOCUMENTS_BY_HASH.get(lookup_key, [])),
    }, 200


def get_person_document_profile(document_number):
    normalized_id = "".join(ch for ch in str(document_number or "").upper() if ch.isalnum())
    if len(normalized_id) < 8:
        return {"exists": False, "linkedCount": 0, "documentHash": "", "documents": []}

    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))
    lookup_key = hmac_sha256(normalized_id, hash_secret)

    with _ACCESS_LOCK:
        _load_state_locked()
        docs = list(_PERSON_DOCUMENTS_BY_HASH.get(lookup_key, []))

    return {
        "exists": bool(docs),
        "linkedCount": len(docs),
        "documentHash": lookup_key,
        "documents": docs,
    }


def register_identity_vault(job_id, document_number, pin_mode="last4", linked_documents=None, document_type="aadhaar"):
    if not job_id:
        return False, "jobId is required"

    normalized_id = "".join(ch for ch in str(document_number or "").upper() if ch.isalnum())
    if len(normalized_id) < 8:
        return False, "document number is invalid"

    mode = str(pin_mode or "last4").strip().lower()
    if mode not in {"last4", "first8"}:
        return False, "pinMode must be last4 or first8"

    pin_fragment = _normalize_pin(mode, normalized_id)
    if not pin_fragment:
        return False, "unable to derive PIN fragment"

    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))
    docs = _sanitize_documents(linked_documents)
    if not docs:
        docs = [{"type": str(document_type or "aadhaar").strip().lower(), "id": "", "source": "scanner", "label": "Scanned Document"}]

    with _ACCESS_LOCK:
        _load_state_locked()
        lookup_key = hmac_sha256(normalized_id, hash_secret)
        person_docs = _PERSON_DOCUMENTS_BY_HASH.get(lookup_key, [])
        merged_docs = _merge_documents(docs, person_docs)
        _IDENTITY_VAULT[job_id] = {
            "documentType": str(document_type or "aadhaar").strip().lower(),
            "maskedDocumentId": f"{'X' * max(0, len(normalized_id) - 4)}{normalized_id[-4:]}",
            "documentHash": lookup_key,
            "pinMode": mode,
            "pinHash": hmac_sha256(pin_fragment, hash_secret),
            "linkedDocuments": merged_docs,
            "createdAt": int(time.time()),
            "lastUnlockAt": None,
        }
        _PERSON_DOCUMENTS_BY_HASH[lookup_key] = _merge_documents(_PERSON_DOCUMENTS_BY_HASH.get(lookup_key, []), merged_docs)
        _save_state_locked()

    return True, "registered"


def append_documents_to_identity(job_id, documents):
    docs = _sanitize_documents(documents)
    if not job_id:
        return False, {"error": "jobId is required"}, 400
    if not docs:
        return False, {"error": "documents must contain at least one valid document"}, 400

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
        if not state:
            return False, {"error": "Unknown jobId"}, 404

        existing = {(item.get("type", ""), item.get("id", "")) for item in state.get("linkedDocuments", [])}
        for item in docs:
            key = (item.get("type", ""), item.get("id", ""))
            if key in existing:
                continue
            state.setdefault("linkedDocuments", []).append(item)
            existing.add(key)

        doc_hash = str(state.get("documentHash", "")).strip()
        if doc_hash:
            existing_person_docs = _PERSON_DOCUMENTS_BY_HASH.get(doc_hash, [])
            _PERSON_DOCUMENTS_BY_HASH[doc_hash] = _merge_documents(existing_person_docs, docs)

        _IDENTITY_VAULT[job_id] = state
    _save_state_locked()

    return True, {"message": "Documents linked", "jobId": job_id, "linkedCount": len(state.get("linkedDocuments", []))}, 200


def upload_document_to_identity(job_id, document_type, document_id, label, file_storage):
    job_id = str(job_id or "").strip()
    if not job_id:
        return False, {"error": "jobId is required"}, 400

    if file_storage is None:
        return False, {"error": "file is required"}, 400

    original_name = str(getattr(file_storage, "filename", "") or "").strip()
    if not original_name:
        return False, {"error": "file name is required"}, 400
    if not _document_file_allowed(original_name):
        allowed = ", ".join(sorted(_IDENTITY_FILE_EXTENSIONS))
        return False, {"error": f"Invalid file type. Allowed: {allowed}"}, 400

    extension = original_name.rsplit(".", 1)[1].strip().lower()
    file_size = _file_storage_size(file_storage)
    max_bytes = _identity_doc_max_bytes()
    if file_size > max_bytes:
        max_mb = max(1, max_bytes // (1024 * 1024))
        return False, {"error": f"File too large. Maximum allowed size is {max_mb} MB", "maxBytes": max_bytes}, 413

    header = _peek_stream(file_storage, size=16)
    sniffed_type = _guess_file_type(header)
    if not sniffed_type:
        return False, {"error": "Unsupported or corrupted file content"}, 400
    if extension in {"jpg", "jpeg"} and sniffed_type != "jpg":
        return False, {"error": "File extension and content do not match"}, 400
    if extension == "pdf" and sniffed_type != "pdf":
        return False, {"error": "File extension and content do not match"}, 400
    if extension == "png" and sniffed_type != "png":
        return False, {"error": "File extension and content do not match"}, 400

    incoming_type = str(getattr(file_storage, "content_type", "") or "").strip().lower()
    allowed_mime = _IDENTITY_ALLOWED_MIME.get(extension, set())
    if incoming_type and incoming_type not in allowed_mime and incoming_type != "application/octet-stream":
        return False, {"error": "Unsupported content type for selected file"}, 400

    doc_type = str(document_type or "other").strip().lower() or "other"
    doc_id = str(document_id or "").strip()
    doc_label = str(label or "").strip() or doc_type.replace("_", " ").title()

    filename = secure_filename(original_name)
    if not filename:
        return False, {"error": "Invalid file name"}, 400

    file_key = secrets.token_hex(12)
    stored_name = f"{file_key}_{filename}"
    target_dir = _identity_docs_dir(job_id)
    os.makedirs(target_dir, exist_ok=True)
    absolute_path = os.path.abspath(os.path.join(target_dir, stored_name))

    try:
        file_storage.save(absolute_path)
    except Exception:
        return False, {"error": "Failed to save uploaded file"}, 500

    try:
        persisted_size = os.path.getsize(absolute_path)
    except OSError:
        _safe_file_remove(absolute_path)
        return False, {"error": "Failed to verify uploaded file"}, 500

    try:
        persisted_hash = hash_file_sha256(absolute_path)
    except Exception:
        _safe_file_remove(absolute_path)
        return False, {"error": "Failed to hash uploaded file"}, 500

    if persisted_size > max_bytes:
        _safe_file_remove(absolute_path)
        max_mb = max(1, max_bytes // (1024 * 1024))
        return False, {"error": f"File too large. Maximum allowed size is {max_mb} MB", "maxBytes": max_bytes}, 413

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
        if not state:
            _safe_file_remove(absolute_path)
            return False, {"error": "Unknown jobId"}, 404

        document_entry = {
            "type": doc_type,
            "id": doc_id,
            "label": doc_label,
            "source": "uploaded-file",
            "fileName": filename,
            "fileKey": file_key,
            "filePath": absolute_path,
            "fileHash": persisted_hash,
        }

        existing_docs = list(state.get("linkedDocuments", []))
        for item in existing_docs:
            item_hash = str(item.get("fileHash", "")).strip().lower()
            item_type = str(item.get("type", "")).strip().lower()
            item_id = str(item.get("id", "")).strip()
            if (item_hash and item_hash == persisted_hash) or (doc_type == item_type and bool(doc_id) and item_id == doc_id):
                _safe_file_remove(absolute_path)
                return True, {
                    "message": "Document already linked",
                    "jobId": job_id,
                    "linkedCount": len(existing_docs),
                    "document": {
                        "type": item_type or doc_type,
                        "id": item_id,
                        "label": str(item.get("label", doc_label)).strip() or doc_label,
                        "source": str(item.get("source", "uploaded-file")),
                        "fileName": str(item.get("fileName", "")).strip(),
                        "fileKey": str(item.get("fileKey", "")).strip(),
                        "fileHash": item_hash,
                    },
                }, 200

        state.setdefault("linkedDocuments", []).append(document_entry)
        state["linkedDocuments"] = _merge_documents(state.get("linkedDocuments", []), [])
        doc_hash = str(state.get("documentHash", "")).strip()
        if doc_hash:
            existing_person_docs = _PERSON_DOCUMENTS_BY_HASH.get(doc_hash, [])
            _PERSON_DOCUMENTS_BY_HASH[doc_hash] = _merge_documents(existing_person_docs, [document_entry])
        _IDENTITY_VAULT[job_id] = state
        _save_state_locked()

    return True, {
        "message": "Document uploaded and linked",
        "jobId": job_id,
        "linkedCount": len(state.get("linkedDocuments", [])),
        "document": {
            "type": doc_type,
            "id": doc_id,
            "label": doc_label,
            "source": "uploaded-file",
            "fileName": filename,
            "fileKey": file_key,
        },
    }, 200


def remove_document_from_identity(job_id, document_type, document_id="", label="", file_key=""):
    job_id = str(job_id or "").strip()
    doc_type = str(document_type or "").strip().lower()
    doc_id = str(document_id or "").strip()
    doc_label = str(label or "").strip()
    doc_file_key = str(file_key or "").strip()

    if not job_id:
        return False, {"error": "jobId is required"}, 400
    if not doc_type:
        return False, {"error": "type is required"}, 400

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
        if not state:
            return False, {"error": "Unknown jobId"}, 404

        linked_docs = list(state.get("linkedDocuments", []))
        filtered_docs = []
        removed = 0
        for item in linked_docs:
            item_type = str(item.get("type", "")).strip().lower()
            item_id = str(item.get("id", "")).strip()
            item_label = str(item.get("label", "")).strip()
            item_file_key = str(item.get("fileKey", "")).strip()
            item_file_path = str(item.get("filePath", "")).strip()

            type_match = item_type == doc_type
            id_match = (not doc_id) or item_id == doc_id
            label_match = (not doc_label) or item_label == doc_label
            file_match = (not doc_file_key) or item_file_key == doc_file_key

            if type_match and id_match and label_match and file_match:
                removed += 1
                _safe_file_remove(item_file_path)
                continue
            filtered_docs.append(item)

        if removed == 0:
            return False, {"error": "No matching document found"}, 404

        state["linkedDocuments"] = filtered_docs
        doc_hash = str(state.get("documentHash", "")).strip()
        if doc_hash:
            person_docs = list(_PERSON_DOCUMENTS_BY_HASH.get(doc_hash, []))
            filtered_person_docs = []
            for item in person_docs:
                item_type = str(item.get("type", "")).strip().lower()
                item_id = str(item.get("id", "")).strip()
                item_label = str(item.get("label", "")).strip()
                item_file_key = str(item.get("fileKey", "")).strip()

                type_match = item_type == doc_type
                id_match = (not doc_id) or item_id == doc_id
                label_match = (not doc_label) or item_label == doc_label
                file_match = (not doc_file_key) or item_file_key == doc_file_key

                if type_match and id_match and label_match and file_match:
                    continue
                filtered_person_docs.append(item)

            _PERSON_DOCUMENTS_BY_HASH[doc_hash] = filtered_person_docs
        _IDENTITY_VAULT[job_id] = state
        _save_state_locked()

    return True, {
        "message": "Document removed",
        "jobId": job_id,
        "removedCount": removed,
        "linkedCount": len(filtered_docs),
    }, 200


def issue_identity_otp(job_id, recipient_email=""):
    if not job_id:
        return False, {"error": "jobId is required"}, 400

    otp_ttl = max(30, int(current_app.config.get("IDENTITY_OTP_TTL_SECONDS", 180)))
    max_attempts = max(1, int(current_app.config.get("IDENTITY_OTP_MAX_ATTEMPTS", 5)))
    otp_cooldown = max(0, int(current_app.config.get("IDENTITY_OTP_COOLDOWN_SECONDS", 30)))
    provider = str(current_app.config.get("IDENTITY_OTP_PROVIDER", "demo")).strip().lower() or "demo"
    show_otp = bool(current_app.config.get("IDENTITY_SHOW_OTP", False)) or provider == "demo"
    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
        if not state:
            return False, {"error": "Unknown jobId"}, 404

        existing_otp = _IDENTITY_OTPS.get(job_id)
        if existing_otp:
            issued_at = float(existing_otp.get("issued_at", 0))
            cooldown_left = int((issued_at + otp_cooldown) - time.time())
            if cooldown_left > 0:
                return False, {
                    "error": "OTP recently issued. Please wait before requesting again.",
                    "retryAfterSec": cooldown_left,
                }, 429

        otp = f"{secrets.randbelow(1000000):06d}"
        _IDENTITY_OTPS[job_id] = {
            "otp_hash": hmac_sha256(otp, hash_secret),
            "expires_at": time.time() + otp_ttl,
            "issued_at": time.time(),
            "attempts": 0,
            "max_attempts": max_attempts,
        }
        _save_state_locked()

    try:
        delivery_meta = deliver_identity_otp(job_id, otp, recipient_email=recipient_email)
    except OtpDeliveryError as exc:
        with _ACCESS_LOCK:
            _load_state_locked()
            _IDENTITY_OTPS.pop(job_id, None)
            _save_state_locked()
        return False, {"error": str(exc)}, 502

    payload = {
        "message": "Identity OTP issued",
        "expiresInSec": otp_ttl,
        "delivery": delivery_meta.get("delivery", "unknown"),
        "target": delivery_meta.get("target", ""),
    }
    if show_otp:
        payload["oneTimeOtp"] = otp
    return True, payload, 200


def unlock_identity_documents(job_id, pin, otp=""):
    pin_value = str(pin or "").strip()
    otp_value = str(otp or "").strip()
    if not job_id or not pin_value:
        return False, {"error": "jobId and pin are required"}, 400

    token_ttl = max(30, int(current_app.config.get("ACCESS_TOKEN_TTL_SECONDS", 300)))
    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))
    require_otp = bool(current_app.config.get("IDENTITY_REQUIRE_OTP", True))

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
        if not state:
            return False, {"error": "Unknown jobId"}, 404

        normalized_pin = _normalize_pin(state.get("pinMode", "last4"), pin_value)
        if not normalized_pin:
            return False, {"error": "Invalid pin"}, 401

        expected = str(state.get("pinHash", ""))
        provided = hmac_sha256(normalized_pin, hash_secret)
        if not hmac.compare_digest(expected, provided):
            return False, {"error": "Invalid pin"}, 401

        if require_otp:
            if not otp_value:
                return False, {"error": "otp is required"}, 400

            otp_state = _IDENTITY_OTPS.get(job_id)
            if not otp_state:
                return False, {"error": "No active OTP for this job. Request a new OTP."}, 400

            now = time.time()
            if now > float(otp_state.get("expires_at", 0)):
                _IDENTITY_OTPS.pop(job_id, None)
                _save_state_locked()
                return False, {"error": "OTP expired. Request a new OTP."}, 400

            attempts = int(otp_state.get("attempts", 0))
            max_attempts = int(otp_state.get("max_attempts", 5))
            if attempts >= max_attempts:
                return False, {"error": "Too many invalid OTP attempts. Request a new OTP."}, 429

            otp_expected = str(otp_state.get("otp_hash", ""))
            otp_provided = hmac_sha256(otp_value, hash_secret)
            if not hmac.compare_digest(otp_expected, otp_provided):
                otp_state["attempts"] = attempts + 1
                _IDENTITY_OTPS[job_id] = otp_state
                _save_state_locked()
                return False, {"error": "Invalid otp"}, 401

            _IDENTITY_OTPS.pop(job_id, None)

        state["lastUnlockAt"] = int(time.time())
        _IDENTITY_VAULT[job_id] = state
        _save_state_locked()

    serializer = URLSafeTimedSerializer(current_app.config.get("SECRET_KEY", ""), salt="identity-doc-access")
    token = serializer.dumps({"jobId": job_id, "scope": "documents"})

    return True, {
        "message": "Identity unlock successful",
        "accessToken": token,
        "expiresInSec": token_ttl,
        "pinMode": state.get("pinMode", "last4"),
        "maskedDocumentId": state.get("maskedDocumentId", ""),
        "documentsUrl": f"/identity/documents?token={quote(token)}",
        "documentsViewUrl": f"/identity/view?token={quote(token)}",
    }, 200


def resolve_identity_documents(access_token):
    payload = _token_payload_for_identity(access_token)
    job_id = str(payload.get("jobId", "")).strip()

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)

    if not state:
        raise ValueError("Unknown jobId")

    linked_documents = []
    for item in list(state.get("linkedDocuments", [])):
        if not isinstance(item, dict):
            continue
        doc = dict(item)
        file_key = str(doc.get("fileKey", "")).strip()
        if file_key:
            doc["fileUrl"] = f"/identity/document-file?token={quote(str(access_token or ''))}&file={quote(file_key)}"
        linked_documents.append(doc)

    return {
        "jobId": job_id,
        "documentType": state.get("documentType", "aadhaar"),
        "maskedDocumentId": state.get("maskedDocumentId", ""),
        "pinMode": state.get("pinMode", "last4"),
        "linkedDocuments": linked_documents,
        "lastUnlockAt": state.get("lastUnlockAt"),
    }


def resolve_identity_document_file(access_token, file_key):
    payload = _token_payload_for_identity(access_token)
    job_id = str(payload.get("jobId", "")).strip()
    target_file_key = str(file_key or "").strip()
    if not target_file_key:
        raise ValueError("Missing file key")

    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)

    if not state:
        raise ValueError("Unknown jobId")

    for item in list(state.get("linkedDocuments", [])):
        if not isinstance(item, dict):
            continue
        item_file_key = str(item.get("fileKey", "")).strip()
        if item_file_key != target_file_key:
            continue

        file_path = os.path.abspath(str(item.get("filePath", "")))
        docs_root = _identity_docs_root()
        if not file_path.startswith(docs_root + os.sep):
            raise ValueError("Invalid document path")
        if not os.path.exists(file_path):
            raise ValueError("Document file not found")

        download_name = str(item.get("fileName", "")).strip() or os.path.basename(file_path)
        return file_path, download_name

    raise ValueError("Document not found")


def get_identity_pin_hint(job_id):
    if not job_id:
        return ""
    with _ACCESS_LOCK:
        _load_state_locked()
        state = _IDENTITY_VAULT.get(job_id)
    if not state:
        return ""
    mode = str(state.get("pinMode", "last4"))
    if mode == "first8":
        return "Use first 8 characters as PIN"
    return "Use last 4 characters as PIN"


def register_job_for_access(job_id, challenge_value, output_image_url, challenge_type="last4"):
    normalized_type = str(challenge_type or "last4").strip().lower()
    if normalized_type == "last4":
        verifier = _normalize_last4(challenge_value)
    elif normalized_type == "fallback_secret":
        verifier = _normalize_fallback_pin(challenge_value)
    else:
        verifier = _normalize_challenge(challenge_value)
    if not job_id or not verifier or not output_image_url:
        return

    with _ACCESS_LOCK:
        _load_state_locked()
        _JOB_ACCESS[job_id] = {
            "verifier": verifier,
            "challengeType": normalized_type,
            "output_image_url": output_image_url,
            "created_at": time.time(),
        }
        _save_state_locked()


def issue_access_code(job_id, last4, visible_fragment="", fallback_pin=""):
    if not job_id:
        return False, {"error": "jobId is required"}, 400

    code_ttl = max(30, int(current_app.config.get("ACCESS_CODE_TTL_SECONDS", 300)))
    max_attempts = max(1, int(current_app.config.get("ACCESS_MAX_ATTEMPTS", 5)))
    show_code = bool(current_app.config.get("ACCESS_SHOW_CODE", True))
    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))

    with _ACCESS_LOCK:
        _load_state_locked()
        job = _JOB_ACCESS.get(job_id)
        if not job:
            return False, {"error": "Unknown jobId"}, 404

        job_challenge_type = str(job.get("challengeType", "last4"))
        if job_challenge_type == "fallback_secret":
            normalized = _normalize_fallback_pin(fallback_pin)
            if not normalized:
                return False, {"error": "fallbackPin is required for this job"}, 400
        elif job_challenge_type == "visible_fragment":
            normalized = _normalize_challenge(visible_fragment)
            if not normalized:
                return False, {"error": "visibleFragment is required for this job"}, 400
        else:
            normalized = _normalize_last4(last4)
            if not normalized:
                return False, {"error": "last4 is required for this job"}, 400

        if not hmac.compare_digest(job.get("verifier", ""), normalized):
            return False, {"error": "Provided fragment does not match this job"}, 403

        code = f"{secrets.randbelow(1000000):06d}"
        _ACCESS_CODES[job_id] = {
            "code_hash": hmac_sha256(code, hash_secret),
            "expires_at": time.time() + code_ttl,
            "attempts": 0,
            "max_attempts": max_attempts,
        }
        _save_state_locked()

    payload = {
        "message": "Verification code issued",
        "expiresInSec": code_ttl,
        "challengeType": job.get("challengeType", "last4"),
    }
    if show_code:
        payload["oneTimeCode"] = code
    return True, payload, 200


def verify_access_code(job_id, last4, visible_fragment, fallback_pin, code):
    code = str(code or "").strip()
    if not job_id or not code:
        return False, {"error": "jobId and code are required"}, 400

    token_ttl = max(30, int(current_app.config.get("ACCESS_TOKEN_TTL_SECONDS", 300)))
    hash_secret = current_app.config.get("HASH_SECRET", current_app.config.get("SECRET_KEY", ""))

    with _ACCESS_LOCK:
        _load_state_locked()
        job = _JOB_ACCESS.get(job_id)
        if not job:
            return False, {"error": "Unknown jobId"}, 404

        job_challenge_type = str(job.get("challengeType", "last4"))
        if job_challenge_type == "fallback_secret":
            normalized = _normalize_fallback_pin(fallback_pin)
            if not normalized:
                return False, {"error": "fallbackPin is required for this job"}, 400
        elif job_challenge_type == "visible_fragment":
            normalized = _normalize_challenge(visible_fragment)
            if not normalized:
                return False, {"error": "visibleFragment is required for this job"}, 400
        else:
            normalized = _normalize_last4(last4)
            if not normalized:
                return False, {"error": "last4 is required for this job"}, 400

        if not hmac.compare_digest(job.get("verifier", ""), normalized):
            return False, {"error": "Provided fragment does not match this job"}, 403

        code_state = _ACCESS_CODES.get(job_id)
        if not code_state:
            return False, {"error": "No active code for this job. Request a new code."}, 400

        now = time.time()
        if now > float(code_state.get("expires_at", 0)):
            _ACCESS_CODES.pop(job_id, None)
            _save_state_locked()
            return False, {"error": "Code expired. Request a new code."}, 400

        attempts = int(code_state.get("attempts", 0))
        max_attempts = int(code_state.get("max_attempts", 5))
        if attempts >= max_attempts:
            return False, {"error": "Too many invalid attempts. Request a new code."}, 429

        expected = str(code_state.get("code_hash", ""))
        provided = hmac_sha256(code, hash_secret)
        if not hmac.compare_digest(expected, provided):
            code_state["attempts"] = attempts + 1
            _ACCESS_CODES[job_id] = code_state
            _save_state_locked()
            return False, {"error": "Invalid code"}, 401

        _ACCESS_CODES.pop(job_id, None)
        _save_state_locked()

    serializer = URLSafeTimedSerializer(current_app.config.get("SECRET_KEY", ""), salt="aadhaar-output-access")
    payload = {
        "jobId": job_id,
        "outputImageUrl": job.get("output_image_url", ""),
    }
    token = serializer.dumps(payload)

    return True, {
        "message": "Access granted",
        "accessToken": token,
        "expiresInSec": token_ttl,
        "secureDownloadUrl": f"/output/secure?token={quote(token)}",
    }, 200


def resolve_secure_output_filename(access_token):
    token_ttl = max(30, int(current_app.config.get("ACCESS_TOKEN_TTL_SECONDS", 300)))
    serializer = URLSafeTimedSerializer(current_app.config.get("SECRET_KEY", ""), salt="aadhaar-output-access")

    try:
        payload = serializer.loads(str(access_token or ""), max_age=token_ttl)
    except SignatureExpired as exc:
        raise ValueError("Access token expired") from exc
    except BadSignature as exc:
        raise ValueError("Invalid access token") from exc

    output_image_url = str(payload.get("outputImageUrl", ""))
    if not output_image_url.startswith("/output/"):
        raise ValueError("Invalid token payload")

    filename = os.path.basename(output_image_url)
    if not filename:
        raise ValueError("Invalid output filename")

    return filename


def _reset_access_state_for_tests():
    global _STATE_LOADED
    with _ACCESS_LOCK:
        _STATE_LOADED = True
        _JOB_ACCESS.clear()
        _ACCESS_CODES.clear()
        _IDENTITY_VAULT.clear()
        _IDENTITY_OTPS.clear()
        _PERSON_DOCUMENTS_BY_HASH.clear()
        _clear_persisted_state_locked()
        shutil.rmtree(_identity_docs_root(), ignore_errors=True)
