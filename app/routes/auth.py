import hmac
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import auth_store
from app.services import clerk_service

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except ModuleNotFoundError:  # pragma: no cover - optional dependency for local/demo runs
    Limiter = None

    def get_remote_address():
        return request.remote_addr or "unknown"

bp = Blueprint("auth", __name__)


class _NullLimiter:
    def init_app(self, app):
        return None

    def limit(self, *args, **kwargs):
        def _decorator(view_func):
            return view_func

        return _decorator


limiter = Limiter(key_func=get_remote_address, default_limits=[]) if Limiter is not None else _NullLimiter()

_PUBLIC_ENDPOINTS = {
    "auth.login",
    "auth.clerk_session",
    "static",
}


def init_limiter(app):
    limiter.init_app(app)


def _safe_next_path() -> str:
    next_path = request.full_path if request.query_string else request.path
    return str(next_path or "/")


def _clear_auth_session() -> None:
    session.pop("auth_user", None)
    session.pop("show_welcome_toast", None)


def _is_authenticated() -> bool:
    return bool(session.get("auth_user"))


def _is_api_like_request() -> bool:
    path = str(request.path or "")
    if path.startswith(("/mask/", "/access/", "/identity/", "/health", "/output/")):
        return True
    if request.accept_mimetypes.best == "application/json":
        return True
    if request.headers.get("X-Requested-With", "") == "XMLHttpRequest":
        return True
    return request.method != "GET"


def enforce_login():
    endpoint = request.endpoint or ""
    if endpoint in _PUBLIC_ENDPOINTS:
        return None

    if _is_authenticated():
        return None

    if _is_api_like_request():
        return jsonify({"error": "Authentication required"}), 401

    return redirect(url_for("auth.login", next=_safe_next_path()))


def login_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if _is_authenticated():
            return view_func(*args, **kwargs)

        if _is_api_like_request():
            return jsonify({"error": "Authentication required"}), 401

        return redirect(url_for("auth.login", next=_safe_next_path()))

    return _wrapped


def _auth_provider() -> str:
    return str(current_app.config.get("AUTH_PROVIDER", "local") or "local").strip().lower()


def _configured_password() -> str:
    return str(current_app.config.get("USER_PASSWORD", "admin123") or "admin123")


def _password_matches(candidate: str) -> bool:
    stored_hash = auth_store.get_password_hash()
    if stored_hash:
        return check_password_hash(stored_hash, candidate)
    return hmac.compare_digest(candidate, _configured_password())


def _safe_next(value) -> str:
    next_url = str(value or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return ""


def _render_clerk_page(logout=False):
    cfg = current_app.config
    publishable_key = str(cfg.get("CLERK_PUBLISHABLE_KEY", "") or "")
    return render_template(
        "clerk_login.html",
        configured=clerk_service.is_configured(),
        publishable_key=publishable_key,
        frontend_host=clerk_service.frontend_api_host(publishable_key),
        next_url=_safe_next(request.args.get("next")),
        logout=logout,
    )


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes", methods=["POST"])
def login():
    if _is_authenticated():
        return redirect(url_for("auth.dashboard"))

    if _auth_provider() == "clerk":
        return _render_clerk_page()

    error = ""
    configured_user = str(current_app.config.get("USER_ID", "admin") or "admin").strip()
    configured_password = _configured_password()

    if request.method == "POST":
        user_id = str(request.form.get("user_id", "") or "").strip()
        password = str(request.form.get("password", "") or "")

        if hmac.compare_digest(user_id, configured_user) and _password_matches(password):
            session["auth_user"] = user_id
            session["show_welcome_toast"] = True

            next_url = _safe_next(request.args.get("next"))
            if next_url:
                return redirect(next_url)
            return redirect(url_for("auth.dashboard"))

        error = "Invalid User ID or Password"

    return render_template(
        "login.html",
        error=error,
        demo_user=configured_user,
        demo_password=configured_password,
        show_login_hints=bool(current_app.config.get("SHOW_LOGIN_CREDENTIAL_HINTS", False)),
        retry_after=0,
    )


@bp.route("/auth/change-password", methods=["POST"])
@login_required
def change_password():
    payload = request.get_json(silent=True) or {}
    current_password = str(payload.get("currentPassword", "") or "")
    new_password = str(payload.get("newPassword", "") or "")

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    if _auth_provider() != "local":
        return jsonify({"error": "Password is managed by the identity provider"}), 400

    if not _password_matches(current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    auth_store.set_password_hash(generate_password_hash(new_password))
    return jsonify({"message": "Password changed successfully"}), 200


@bp.errorhandler(429)
def rate_limit_handler(error):
    retry_after = int(getattr(error, "retry_after", 0) or 0)
    if request.path == "/login":
        configured_user = str(current_app.config.get("USER_ID", "admin") or "admin").strip()
        configured_password = _configured_password()
        return (
            render_template(
                "login.html",
                error="Too many login attempts. Please wait before retrying.",
                demo_user=configured_user,
                demo_password=configured_password,
                show_login_hints=bool(current_app.config.get("SHOW_LOGIN_CREDENTIAL_HINTS", False)),
                retry_after=retry_after,
            ),
            429,
        )
    return jsonify({"error": "Too many requests", "retryAfterSec": retry_after}), 429


@bp.route("/auth/clerk/session", methods=["POST"])
@limiter.limit("20 per 15 minutes")
def clerk_session():
    if _auth_provider() != "clerk":
        return jsonify({"error": "Clerk login is not enabled"}), 404

    payload = request.get_json(silent=True) or {}
    try:
        identity = clerk_service.authenticate(payload.get("token", ""))
    except clerk_service.ClerkAuthError as exc:
        return jsonify({"error": str(exc)}), 401

    session.clear()
    session["auth_user"] = identity
    session["show_welcome_toast"] = True
    redirect_to = _safe_next(payload.get("next")) or url_for("auth.dashboard")
    return jsonify({"redirect": redirect_to}), 200


@bp.route("/logout", methods=["GET"])
@login_required
def logout():
    _clear_auth_session()
    session.pop("owned_outputs", None)
    if _auth_provider() == "clerk":
        return _render_clerk_page(logout=True)
    return redirect(url_for("auth.login"))


@bp.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    username = str(session.get("auth_user", "User") or "User")
    show_welcome_toast = bool(session.pop("show_welcome_toast", False))
    return render_template("dashboard.html", username=username, show_welcome_toast=show_welcome_toast)
