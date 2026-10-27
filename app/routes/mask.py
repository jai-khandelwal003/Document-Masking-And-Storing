import os, threading, time, hmac
from flask import Blueprint, current_app, request, jsonify, session
from app.services.mask_service import upload_aadhaar_and_mask, upload_document_and_mask, verify_integrity_token
from app.utils.file_utils import allowed_file
from app.utils.mime_utils import detect_mime_from_stream, is_allowed_upload_mime
from app.models.audit_store import log_mask_job
from app.services.storage import StorageError

bp = Blueprint("mask", __name__)
_RATE_LIMIT_STATE = {}
_RATE_LIMIT_LOCK = threading.Lock()

def _to_bool(v, d=False): return str(v or "").strip().lower() in {"1", "true", "yes", "on"} if v else d
def _client_ip():
    # X-Forwarded-For is client-controlled unless a trusted proxy (e.g. the bundled nginx) sets it.
    if current_app.config.get("TRUST_PROXY_HEADERS", False):
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if ip:
            return ip
    return request.remote_addr or "unknown"

def _remember_output(result):
    # Only the session that created a masked file may fetch it from /output/<file>;
    # everyone else must go through the OTP-protected /output/secure flow.
    names = [os.path.basename(str(result.get(key, "") or "")) for key in ("outputImageUrl", "outputPdfUrl")]
    names = [n for n in names if n]
    if not names:
        return
    owned = [n for n in session.get("owned_outputs", []) if n not in names]
    owned.extend(names)
    session["owned_outputs"] = owned[-50:]
def _param(name, default="", sources=None):
    sources = sources or [request.form, request.args, request.headers]
    headers = {"document_type": "X-Document-Type", "first8_mask": "X-First8-Mask", "last4_mask": "X-Last4-Mask", "mask_qr": "X-Mask-QR"}
    h_name = headers.get(name, f"X-{name.upper()}")
    return next((s.get(name) or s.get(h_name) for s in sources), default)

def _check_auth():
    if not current_app.config.get("API_KEY_REQUIRED", False): return None
    if not hmac.compare_digest(str(request.headers.get("X-API-Key", "")), str(current_app.config.get("API_KEY", ""))): 
        return jsonify({"error": "Unauthorized: invalid API key"}), 401

def _check_rate_limit():
    if not current_app.config.get("RATE_LIMIT_ENABLED", True): return None
    now = time.time()
    window_sec = max(1, int(current_app.config.get("RATE_LIMIT_WINDOW_SECONDS", 60)))
    max_req = max(1, int(current_app.config.get("RATE_LIMIT_REQUESTS", 20)))
    ip = _client_ip()
    with _RATE_LIMIT_LOCK:
        for ip_key in list(_RATE_LIMIT_STATE.keys()):
            _RATE_LIMIT_STATE[ip_key] = [ts for ts in _RATE_LIMIT_STATE[ip_key] if ts >= now - window_sec]
            if not _RATE_LIMIT_STATE[ip_key]: del _RATE_LIMIT_STATE[ip_key]
        if len(_RATE_LIMIT_STATE) > 10000:
            for old_ip in list(_RATE_LIMIT_STATE.keys())[:-10000]: del _RATE_LIMIT_STATE[old_ip]
        valid = [ts for ts in _RATE_LIMIT_STATE.get(ip, []) if ts >= now - window_sec]
        if len(valid) >= max_req:
            retry = max(1, int(window_sec - (now - min(valid))))
            return jsonify({"error": "Too many requests. Please retry later.", "retryAfterSec": retry}), 429
        _RATE_LIMIT_STATE[ip] = valid + [now]

def _normalize_doc_type(v):
    n = str(v or "aadhaar").strip().lower()
    n = {"driving_license": "dl", "driving-licence": "dl", "driving_licence": "dl"}.get(n, n)
    return n if n in {"aadhaar", "pan", "dl", "all"} else ""

@bp.route("/mask/aadhaar", methods=["POST"])
@bp.route("/mask/document", methods=["POST"])
def mask_aadhaar_route():
    """Mask document endpoint. ---
    consumes: [multipart/form-data]
    parameters:
      - {in: formData, name: file, type: file, required: true}
      - {in: formData, name: document_type, type: string}
      - {in: formData, name: first8_mask, type: boolean}
      - {in: formData, name: last4_mask, type: boolean}
      - {in: formData, name: mask_qr, type: boolean}
    responses: {200: {description: Masking result}}
    """
    if (err := _check_auth()) or (err := _check_rate_limit()): return err
    if "file" not in request.files or not request.files["file"].filename: return jsonify({"error": "No file"}), 400
    
    file = request.files["file"]
    f8 = _to_bool(_param("first8_mask"), True)
    l4 = _to_bool(_param("last4_mask"), False)
    mq = _to_bool(_param("mask_qr"), False)
    dt = _normalize_doc_type(_param("document_type"))
    
    if not dt: return jsonify({"error": "Invalid document_type"}), 400
    if not f8 and not l4: return jsonify({"error": "Enable at least one masking option"}), 400
    if not allowed_file(file.filename): return jsonify({"error": "Invalid file type"}), 400
    if not is_allowed_upload_mime(detect_mime_from_stream(file.stream)): return jsonify({"error": "Invalid file content"}), 400
    
    try:
        resp = (upload_aadhaar_and_mask if dt == "aadhaar" else upload_document_and_mask)(file, f8, l4, mq, document_type=dt)
    except StorageError:
        return jsonify({"error": "Document storage is unavailable. Please try again."}), 502
    result = resp.to_dict()
    _remember_output(result)
    mode = "both" if f8 and l4 else ("first8" if f8 else "last4")
    log_mask_job(str(session.get("auth_user", "authenticated-user")), str(result.get("documentType", dt)), 
                 str(result.get("jobId", "")), mode, int(result.get("noOfAadhaarDetected", 0) or 0) + int(result.get("noOfQrDetected", 0) or 0))
    return jsonify(result), 200

@bp.route("/mask/verify-integrity", methods=["POST"])
def verify_integrity_route():
    """Verify integrity token. ---
    consumes: [application/json]
    responses: {200: {description: Verification result}}
    """
    p = request.get_json(silent=True) or {}
    missing = [f for f in ["jobId", "processedAt", "inputFileHash", "outputFileHash", "integrityToken"] if not p.get(f)]
    if missing: return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    return jsonify({"valid": bool(verify_integrity_token(p.get("jobId"), p.get("processedAt"), p.get("inputFileHash"), p.get("outputFileHash"), p.get("integrityToken")))}), 200
