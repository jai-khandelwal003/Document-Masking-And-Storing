"""Browser-facing hardening: security headers, a nonce-based Content-Security-Policy and no-store caching."""
import secrets

from flask import current_app, g, request

from app.services import clerk_service

# Responses that carry (or lead to) personal documents must never be cached by the browser or a proxy.
_NO_STORE_PREFIXES = ("/output/", "/identity/", "/access/", "/mask/", "/auth/", "/dashboard", "/login", "/analytics/")

CLERK_WILDCARD_HOSTS = ("https://*.clerk.accounts.dev", "https://*.clerk.com")


def build_csp(config, nonce):
    script_src = ["'self'", f"'nonce-{nonce}'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"]
    connect_src = ["'self'"]
    img_src = ["'self'", "data:", "blob:"]
    frame_src = ["'none'"]

    if str(config.get("AUTH_PROVIDER", "local")).lower() == "clerk":
        host = clerk_service.frontend_api_host(config.get("CLERK_PUBLISHABLE_KEY", ""))
        if host:
            script_src.append(f"https://{host}")
            connect_src.append(f"https://{host}")
        script_src.append("https://challenges.cloudflare.com")
        connect_src += [*CLERK_WILDCARD_HOSTS, "https://clerk-telemetry.com"]
        img_src += ["https://img.clerk.com"]
        frame_src = ["https://challenges.cloudflare.com"]

    directives = {
        "default-src": ["'self'"],
        "script-src": script_src,
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
        "img-src": img_src,
        "connect-src": connect_src,
        "frame-src": frame_src,
        "worker-src": ["'self'", "blob:"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


def init_security(app):
    @app.before_request
    def _make_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.after_request
    def _apply_headers(response):
        cfg = current_app.config
        if not cfg.get("SECURITY_HEADERS_ENABLED", True):
            return response

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        if str(request.path or "").startswith(_NO_STORE_PREFIXES):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"

        csp_setting = str(cfg.get("SECURITY_CSP", "") or "").strip()
        if csp_setting.lower() != "off":
            policy = csp_setting or build_csp(cfg, getattr(g, "csp_nonce", ""))
            header = "Content-Security-Policy-Report-Only" if cfg.get("SECURITY_CSP_REPORT_ONLY") else "Content-Security-Policy"
            response.headers.setdefault(header, policy)
        return response
