from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename
import io
import os
import re
import secrets

from app.services.access_service import (
    issue_access_code,
    verify_access_code,
    append_documents_to_identity,
    remove_document_from_identity,
    upload_document_to_identity,
    issue_identity_otp,
    register_person_documents,
    unlock_identity_documents,
    resolve_identity_documents,
    resolve_identity_document_file,
)
from app.models.identity_store import add_document, get_documents, remove_document, upsert_profile
from app.models.audit_store import get_recent_entries
from app.routes.auth import config_limit
from app.services.storage import StorageError, identity_docs_root, remote_storage
from app.utils.mime_utils import detect_mime_from_stream, is_allowed_upload_mime


bp = Blueprint("access", __name__)

_PROFILE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _valid_profile_key(profile_key):
    return bool(_PROFILE_KEY_RE.fullmatch(str(profile_key or "")))


@bp.route("/access/request-code", methods=["POST"])
@config_limit("RATE_LIMIT_OTP")
def request_access_code_route():
    payload = request.get_json(silent=True) or {}
    ok, body, status = issue_access_code(
        payload.get("jobId", ""),
        payload.get("last4", ""),
        payload.get("visibleFragment", ""),
        payload.get("fallbackPin", ""),
    )
    return jsonify(body), status


@bp.route("/access/verify", methods=["POST"])
@config_limit("RATE_LIMIT_VERIFY")
def verify_access_route():
    payload = request.get_json(silent=True) or {}
    ok, body, status = verify_access_code(
        payload.get("jobId", ""),
        payload.get("last4", ""),
        payload.get("visibleFragment", ""),
        payload.get("fallbackPin", ""),
        payload.get("code", ""),
    )
    return jsonify(body), status


@bp.route("/identity/link-documents", methods=["POST"])
@config_limit("RATE_LIMIT_IDENTITY")
def link_identity_documents_route():
    payload = request.get_json(silent=True) or {}
    profile_key = str(payload.get("profileKey", "") or "").strip()
    documents = payload.get("documents", [])
    job_id = str(payload.get("jobId", "") or "").strip()
    if job_id and not profile_key:
        ok, body, status = append_documents_to_identity(job_id, documents)
        return jsonify(body), status
    if not profile_key:
        return jsonify({"error": "profileKey is required"}), 400
    if not isinstance(documents, list) or not documents:
        return jsonify({"error": "documents must be a non-empty array"}), 400

    upsert_profile(profile_key)
    saved = []
    for item in documents:
        if not isinstance(item, dict):
            continue
        try:
            saved.append(add_document(profile_key, item))
        except ValueError:
            continue

    return jsonify({"message": "Documents linked", "profileKey": profile_key, "linkedCount": len(get_documents(profile_key)), "documents": saved}), 200


@bp.route("/identity/unlink-document", methods=["POST"])
@config_limit("RATE_LIMIT_IDENTITY")
def unlink_identity_document_route():
    payload = request.get_json(silent=True) or {}
    profile_key = str(payload.get("profileKey", "") or "").strip()
    job_id = str(payload.get("jobId", "") or "").strip()
    if job_id and not profile_key:
        ok, body, status = remove_document_from_identity(
            job_id,
            payload.get("type", ""),
            payload.get("id", ""),
            payload.get("label", ""),
            payload.get("fileKey", ""),
        )
        return jsonify(body), status
    removed = remove_document(
        profile_key,
        payload.get("type", ""),
        payload.get("id", ""),
        payload.get("fileKey", ""),
    )
    if removed <= 0:
        return jsonify({"error": "No matching document found"}), 404
    return jsonify({"message": "Document removed", "profileKey": profile_key, "removedCount": removed, "linkedCount": len(get_documents(profile_key))}), 200


@bp.route("/identity/upload-document", methods=["POST"])
@config_limit("RATE_LIMIT_IDENTITY")
def upload_identity_document_route():
    file_obj = request.files.get("file")
    profile_key = str(request.form.get("profileKey", "") or "").strip()
    job_id = str(request.form.get("jobId", "") or "").strip()
    if job_id and not profile_key:
        ok, body, status = upload_document_to_identity(
            job_id,
            request.form.get("type", "other"),
            request.form.get("id", ""),
            request.form.get("label", ""),
            file_obj,
        )
        return jsonify(body), status
    if not profile_key:
        return jsonify({"error": "profileKey is required"}), 400
    if not _valid_profile_key(profile_key):
        return jsonify({"error": "Invalid profileKey"}), 400
    if file_obj is None or not str(file_obj.filename or "").strip():
        return jsonify({"error": "file is required"}), 400

    mime_type = detect_mime_from_stream(file_obj.stream)
    if not is_allowed_upload_mime(mime_type):
        return jsonify({"error": "Unsupported file content"}), 400

    extension = {
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }.get(mime_type, "")

    safe_name = secure_filename(file_obj.filename)
    file_key = secrets.token_hex(12)
    storage_dir = os.path.join(identity_docs_root(), profile_key)
    os.makedirs(storage_dir, exist_ok=True)
    save_path = os.path.join(storage_dir, f"{file_key}_{safe_name or ('document' + extension)}")
    file_obj.save(save_path)

    remote = remote_storage()
    if remote is not None:
        stored_name = os.path.basename(save_path)
        try:
            remote.put_file(save_path, remote.key("identity_docs", profile_key, stored_name))
        except StorageError:
            os.remove(save_path)
            return jsonify({"error": "Document storage is unavailable. Please try again."}), 502
        os.remove(save_path)

    doc = add_document(
        profile_key,
        {
            "type": request.form.get("type", "other"),
            "id": request.form.get("id", ""),
            "label": request.form.get("label", ""),
            "source": "uploaded-file",
            "fileKey": file_key,
        },
    )

    return jsonify({"message": "Document uploaded and linked", "profileKey": profile_key, "linkedCount": len(get_documents(profile_key)), "document": doc}), 200


@bp.route("/identity/register-documents", methods=["POST"])
@config_limit("RATE_LIMIT_IDENTITY")
def register_person_documents_route():
    payload = request.get_json(silent=True) or {}
    ok, body, status = register_person_documents(
        payload.get("aadhaarNumber", ""),
        payload.get("documents", []),
    )
    return jsonify(body), status


@bp.route("/identity/unlock", methods=["POST"])
@config_limit("RATE_LIMIT_VERIFY")
def unlock_identity_route():
    payload = request.get_json(silent=True) or {}
    ok, body, status = unlock_identity_documents(
        payload.get("jobId", ""),
        payload.get("pin", ""),
        payload.get("otp", ""),
    )
    return jsonify(body), status


@bp.route("/identity/request-otp", methods=["POST"])
@config_limit("RATE_LIMIT_OTP")
def request_identity_otp_route():
    payload = request.get_json(silent=True) or {}
    ok, body, status = issue_identity_otp(
        payload.get("jobId", ""),
        payload.get("recipientEmail", ""),
    )
    return jsonify(body), status


@bp.route("/identity/documents", methods=["GET"])
@config_limit("RATE_LIMIT_IDENTITY")
def identity_documents_route():
    profile_key = request.args.get("profileKey", "")
    if profile_key:
        docs = get_documents(profile_key)
        return jsonify({"profileKey": profile_key, "linkedDocuments": docs}), 200

    token = request.args.get("token", "")
    if not token:
        return jsonify({"error": "Missing access token or profileKey"}), 400

    try:
        payload = resolve_identity_documents(token)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 401

    return jsonify(payload), 200


@bp.route("/analytics/audit-log", methods=["GET"])
@config_limit("RATE_LIMIT_IDENTITY")
def audit_log_route():
    try:
        limit = int(request.args.get("limit", 20) or 20)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    return jsonify({"entries": get_recent_entries(limit)}), 200


@bp.route("/identity/document-file", methods=["GET"])
@config_limit("RATE_LIMIT_IDENTITY")
def identity_document_file_route():
    # Support two access modes:
    # 1) token + file - secure token-based access (existing behavior)
    # 2) profileKey + file - local direct access to stored profile uploads (convenience for local/dev)
    token = request.args.get("token", "")
    file_key = request.args.get("file", "")
    profile_key = request.args.get("profileKey", "")

    if profile_key:
        # Directly resolve file from output/identity_docs/<profile_key> by matching file_key prefix
        if not _valid_profile_key(profile_key) or not _PROFILE_KEY_RE.fullmatch(file_key or ""):
            return jsonify({"error": "Invalid profileKey or file"}), 400
        remote = remote_storage()
        if remote is not None:
            try:
                stored_key = remote.find_first_by_prefix(remote.key("identity_docs", profile_key, f"{file_key}_"))
                if not stored_key:
                    return jsonify({"error": "File not found"}), 404
                data = remote.get_bytes(stored_key)
            except FileNotFoundError:
                return jsonify({"error": "File not found"}), 404
            except StorageError:
                return jsonify({"error": "Storage unavailable"}), 502
            stored_name = stored_key.rsplit("/", 1)[-1]
            download_name = stored_name.split("_", 1)[1] if "_" in stored_name else stored_name
            return send_file(io.BytesIO(data), as_attachment=True, download_name=download_name)
        storage_dir = os.path.join(identity_docs_root(), profile_key)
        if not os.path.isdir(storage_dir):
            return jsonify({"error": "Profile directory not found"}), 404
        for name in os.listdir(storage_dir):
            if name.startswith(f"{file_key}_"):
                file_path = os.path.join(storage_dir, name)
                if os.path.isfile(file_path):
                    download_name = name.split("_", 1)[1] if "_" in name else name
                    return send_file(file_path, as_attachment=True, download_name=download_name)
        return jsonify({"error": "File not found"}), 404

    # Fallback to token-based access
    if not token:
        return jsonify({"error": "Missing access token or profileKey"}), 400
    if not file_key:
        return jsonify({"error": "Missing file key"}), 400

    try:
        file_path, download_name = resolve_identity_document_file(token, file_key)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 401

    return send_file(file_path, as_attachment=True, download_name=download_name)
