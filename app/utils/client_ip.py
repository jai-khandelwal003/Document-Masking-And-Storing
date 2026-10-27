from flask import current_app, request


def client_ip():
    """Best-effort client address for rate limiting.

    X-Forwarded-For is only trusted when TRUST_PROXY_HEADERS is on. A client can send its own
    X-Forwarded-For and a proxy appends the real address to it, so the *left* entries are forgeable.
    We take the entry added by our own (last) trusted proxy, counted from the right.
    """
    cfg = current_app.config
    if cfg.get("TRUST_PROXY_HEADERS", False):
        parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
        trusted_hops = max(1, int(cfg.get("TRUSTED_PROXY_COUNT", 1) or 1))
        if len(parts) >= trusted_hops:
            return parts[-trusted_hops]
    return request.remote_addr or "unknown"
