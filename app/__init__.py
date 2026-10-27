import io
import os

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for

try:
    from flasgger import Swagger
except ModuleNotFoundError:  # pragma: no cover - optional dependency for local/demo runs
    Swagger = None

from app.config import Config
from app.security import init_security
from app.routes import access, auth, health, mask
from app.models.identity_store import init_db as init_identity_db
from app.models.audit_store import init_db as init_audit_db
from app.services.access_service import resolve_secure_output_filename, resolve_identity_documents
from app.services.storage import StorageError, init_storage, remote_storage
from app.services.storage_cleanup import cleanup_storage


def _is_truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _apply_runtime_guardrails(app):
    is_production = bool(app.config.get("PRODUCTION", False))

    # Development and test mode can use generated process-local secrets.
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.urandom(32).hex()
    if not app.config.get("HASH_SECRET"):
        app.config["HASH_SECRET"] = app.config["SECRET_KEY"]

    if not is_production:
        return

    if not os.environ.get("SECRET_KEY", "").strip():
        raise RuntimeError("Production requires SECRET_KEY environment variable")
    if not os.environ.get("HASH_SECRET", "").strip():
        raise RuntimeError("Production requires HASH_SECRET environment variable")

    if not _is_truthy(app.config.get("SESSION_COOKIE_SECURE", False)):
        raise RuntimeError("Production requires SESSION_COOKIE_SECURE=true (serve the app over HTTPS)")

    auth_provider = str(app.config.get("AUTH_PROVIDER", "local")).strip().lower()
    if auth_provider == "clerk":
        if not str(app.config.get("CLERK_PUBLISHABLE_KEY", "") or "").strip() or not str(app.config.get("CLERK_SECRET_KEY", "") or "").strip():
            raise RuntimeError("Production with AUTH_PROVIDER=clerk requires CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY")
        has_allowlist = str(app.config.get("CLERK_ALLOWED_EMAILS", "") or "").strip() or str(app.config.get("CLERK_ALLOWED_DOMAINS", "") or "").strip()
        if not has_allowlist and not _is_truthy(app.config.get("CLERK_ALLOW_ANY_USER", False)):
            raise RuntimeError("Production requires CLERK_ALLOWED_EMAILS or CLERK_ALLOWED_DOMAINS (or CLERK_ALLOW_ANY_USER=true)")
    else:
        password = str(app.config.get("USER_PASSWORD", "") or "")
        if password in {"", "admin123", "change-me"} or len(password) < 10:
            raise RuntimeError("Production requires USER_PASSWORD to be set to a strong value (10+ chars, not the default)")

    if str(app.config.get("STORAGE_BACKEND", "local")).strip().lower() == "s3":
        has_static_keys = str(app.config.get("S3_ACCESS_KEY_ID", "") or "").strip() and str(app.config.get("S3_SECRET_ACCESS_KEY", "") or "").strip()
        if not has_static_keys and not os.environ.get("AWS_ACCESS_KEY_ID") and not os.environ.get("AWS_PROFILE") and not os.environ.get("AWS_ROLE_ARN") and not os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
            raise RuntimeError("Production with STORAGE_BACKEND=s3 requires S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY (or an AWS credential source)")

    api_key_required = _is_truthy(app.config.get("API_KEY_REQUIRED", True))
    if api_key_required and not str(app.config.get("API_KEY", "") or "").strip():
        raise RuntimeError("Production requires API_KEY when API_KEY_REQUIRED=true")

    if not str(app.config.get("HEALTH_DETAILS_TOKEN", "") or "").strip():
        raise RuntimeError("Production requires HEALTH_DETAILS_TOKEN to protect /health/details")

    if _is_truthy(app.config.get("ACCESS_SHOW_CODE", False)):
        raise RuntimeError("Production cannot run with ACCESS_SHOW_CODE=true")
    if _is_truthy(app.config.get("IDENTITY_SHOW_OTP", False)):
        raise RuntimeError("Production cannot run with IDENTITY_SHOW_OTP=true")
    otp_provider = str(app.config.get("IDENTITY_OTP_PROVIDER", "")).strip().lower()
    if otp_provider == "demo":
        raise RuntimeError("Production cannot run with IDENTITY_OTP_PROVIDER=demo")
    if otp_provider == "email":
        smtp_host = str(app.config.get("OTP_EMAIL_SMTP_HOST", "") or "").strip()
        smtp_user = str(app.config.get("OTP_EMAIL_USERNAME", "") or "").strip()
        smtp_password = str(app.config.get("OTP_EMAIL_PASSWORD", "") or "").strip()
        smtp_from = str(app.config.get("OTP_EMAIL_FROM", "") or "").strip()
        if not smtp_host or not smtp_user or not smtp_password or not smtp_from:
            raise RuntimeError(
                "Production with IDENTITY_OTP_PROVIDER=email requires OTP_EMAIL_SMTP_HOST, OTP_EMAIL_USERNAME, OTP_EMAIL_PASSWORD, OTP_EMAIL_FROM"
            )

        placeholder_values = {
            "your-email@gmail.com",
            "your-app-password",
            "change-me",
            "example@example.com",
        }
        candidate_values = {
            smtp_user.lower(),
            smtp_password.lower(),
            smtp_from.lower(),
        }
        if candidate_values & placeholder_values:
            raise RuntimeError("Production OTP email config still contains placeholder values")


def _resolve_output_dir(app: Flask) -> str:
    # Serve from the folder the masking service writes to, so the two can never disagree.
    from app.services import mask_service

    return os.path.abspath(mask_service.OUTPUT_DIR)


def _register_blueprints(app: Flask) -> None:
    auth.init_limiter(app)
    app.register_error_handler(429, auth.rate_limit_handler)
    app.register_blueprint(auth.bp)
    app.register_blueprint(health.bp)
    app.register_blueprint(mask.bp)
    app.register_blueprint(access.bp)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.setdefault(
        "SWAGGER",
        {
            "title": "Smart Document Masking API",
            "uiversion": 3,
            "specs_route": "/docs/",
        },
    )
    _apply_runtime_guardrails(app)
    init_security(app)
    if Swagger is not None:
        Swagger(app)
    init_storage(app)
    # Inside an app context so the configured DB/log paths are used, not the defaults.
    with app.app_context():
        init_identity_db()
        init_audit_db()

    if bool(app.config.get("STORAGE_CLEANUP_AT_STARTUP", True)) and not bool(app.config.get("TESTING", False)):
        cleanup_summary = cleanup_storage(app)
        if cleanup_summary.get("enabled"):
            app.logger.info(
                "Storage cleanup complete: %s files, %s dirs removed (retention=%s days)",
                cleanup_summary.get("deletedFiles", 0),
                cleanup_summary.get("deletedDirs", 0),
                cleanup_summary.get("retentionDays", 0),
            )

    @app.context_processor
    def inject_branding():
        return {
            "branding": {
                "projectTitle": app.config.get("BRAND_PROJECT_TITLE", "Smart Document Masking"),
                "collegeName": app.config.get("BRAND_COLLEGE_NAME", "Your College Name"),
                "department": app.config.get("BRAND_DEPARTMENT", "Department of Computer Science"),
                "guideName": app.config.get("BRAND_GUIDE_NAME", "Project Guide"),
                "studentName": app.config.get("BRAND_STUDENT_NAME", "Final Year Student"),
                "regNo": app.config.get("BRAND_REG_NO", "N/A"),
                "year": app.config.get("BRAND_YEAR", "Final Year"),
                "logoUrl": app.config.get("BRAND_LOGO_URL", ""),
                "appApiKey": app.config.get("APP_API_KEY", ""),
            }
        }

    _register_blueprints(app)

    @app.before_request
    def require_login_for_app_routes():
        return auth.enforce_login()

    # Root route (to avoid 404 on /)
    @app.route("/")
    def home():
        return redirect(url_for("auth.dashboard"))

    def _send_output(filename):
        remote = remote_storage()
        if remote is None:
            return send_from_directory(_resolve_output_dir(app), filename)
        name = os.path.basename(filename)
        try:
            data = remote.get_bytes(remote.key("masked", name))
        except FileNotFoundError:
            return jsonify({"error": "File not found"}), 404
        except StorageError:
            return jsonify({"error": "Storage unavailable"}), 502
        mimetype = "application/pdf" if name.lower().endswith(".pdf") else "image/jpeg"
        return send_file(io.BytesIO(data), mimetype=mimetype, download_name=name)

    @app.route("/output/<path:filename>")
    def output_file(filename):
        if filename not in session.get("owned_outputs", []):
            return jsonify({"error": "Not your file. Use /output/secure with an access token."}), 403
        return _send_output(filename)

    @app.route("/output/secure", methods=["GET"])
    def secure_output_file():
        token = request.args.get("token", "")
        if not token:
            return jsonify({"error": "Missing access token"}), 400

        kind = "pdf" if request.args.get("format") == "pdf" else "image"
        try:
            filename = resolve_secure_output_filename(token, kind)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 401

        return _send_output(filename)

    @app.route("/identity/view", methods=["GET"])
    def identity_documents_view():
        token = request.args.get("token", "")
        if not token:
            return render_template("identity_documents.html", error="Missing access token", payload=None), 400

        try:
            payload = resolve_identity_documents(token)
        except ValueError as exc:
            return render_template("identity_documents.html", error=str(exc), payload=None), 401

        return render_template("identity_documents.html", error="", payload=payload)

    return app
