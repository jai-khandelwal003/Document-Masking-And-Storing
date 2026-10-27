import hmac
from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for

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


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes")
def login():
    if _is_authenticated():
        return redirect(url_for("auth.dashboard"))

    error = ""
    configured_user = str(current_app.config.get("USER_ID", "admin") or "admin").strip()
    configured_password = str(
        current_app.config.get("RUNTIME_USER_PASSWORD")
        or current_app.config.get("USER_PASSWORD", "admin123")
        or "admin123"
    )

    if request.method == "POST":
        user_id = str(request.form.get("user_id", "") or "").strip()
        password = str(request.form.get("password", "") or "")

        if hmac.compare_digest(user_id, configured_user) and hmac.compare_digest(password, configured_password):
            session["auth_user"] = user_id
            session["show_welcome_toast"] = True

            next_url = str(request.args.get("next", "") or "").strip()
            if next_url.startswith("/") and not next_url.startswith("//"):
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

    active_password = str(
        current_app.config.get("RUNTIME_USER_PASSWORD")
        or current_app.config.get("USER_PASSWORD", "admin123")
        or "admin123"
    )

    if not hmac.compare_digest(current_password, active_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    current_app.config["RUNTIME_USER_PASSWORD"] = new_password
    return jsonify({"message": "Password changed successfully"}), 200


@bp.errorhandler(429)
def rate_limit_handler(error):
    retry_after = int(getattr(error, "retry_after", 0) or 0)
    if request.path == "/login":
        configured_user = str(current_app.config.get("USER_ID", "admin") or "admin").strip()
        configured_password = str(current_app.config.get("USER_PASSWORD", "admin123") or "admin123")
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


@bp.route("/logout", methods=["GET"])
@login_required
def logout():
    _clear_auth_session()
    return redirect(url_for("auth.login"))


@bp.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    username = str(session.get("auth_user", "User") or "User")
    show_welcome_toast = bool(session.pop("show_welcome_toast", False))
    return render_template("dashboard.html", username=username, show_welcome_toast=show_welcome_toast)
