import base64

import jwt
import requests
from flask import current_app

CLERK_API_BASE = "https://api.clerk.com/v1"
_JWKS_CLIENTS = {}


class ClerkAuthError(Exception):
    pass


def _split_csv(value):
    return [item.strip().lower() for item in str(value or "").split(",") if item.strip()]


def frontend_api_host(publishable_key):
    """Decode the Clerk frontend API host from a publishable key (pk_test_/pk_live_ + base64)."""
    key = str(publishable_key or "").strip()
    parts = key.split("_", 2)
    if len(parts) != 3 or parts[0] != "pk":
        return ""
    encoded = parts[2]
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except Exception:
        return ""
    return decoded.rstrip("$")


def is_configured():
    cfg = current_app.config
    return bool(
        str(cfg.get("CLERK_PUBLISHABLE_KEY", "")).strip()
        and str(cfg.get("CLERK_SECRET_KEY", "")).strip()
        and frontend_api_host(cfg.get("CLERK_PUBLISHABLE_KEY", ""))
    )


def _jwks_client(jwks_url):
    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        _JWKS_CLIENTS[jwks_url] = client
    return client


def verify_session_token(token):
    """Verify a Clerk session JWT (signature, expiry, issuer, authorized party) and return its claims."""
    cfg = current_app.config
    host = frontend_api_host(cfg.get("CLERK_PUBLISHABLE_KEY", ""))
    if not host:
        raise ClerkAuthError("Clerk is not configured")

    jwks_url = str(cfg.get("CLERK_JWKS_URL", "") or "").strip() or f"https://{host}/.well-known/jwks.json"
    issuer = f"https://{host}"

    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            leeway=10,
            options={"require": ["exp", "iat", "sub", "iss"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise ClerkAuthError("Invalid or expired session token") from exc

    parties = _split_csv(cfg.get("CLERK_AUTHORIZED_PARTIES", ""))
    if parties and str(claims.get("azp", "")).strip().lower() not in parties:
        raise ClerkAuthError("Session token was issued for a different origin")

    return claims


def fetch_user_emails(user_id):
    secret = str(current_app.config.get("CLERK_SECRET_KEY", "") or "").strip()
    try:
        resp = requests.get(
            f"{CLERK_API_BASE}/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise ClerkAuthError("Unable to look up user in Clerk") from exc

    emails = []
    for item in data.get("email_addresses", []) or []:
        verified = (item.get("verification") or {}).get("status") == "verified"
        address = str(item.get("email_address", "")).strip().lower()
        if verified and address:
            emails.append(address)
    return emails


def is_email_allowed(emails):
    cfg = current_app.config
    allowed_emails = set(_split_csv(cfg.get("CLERK_ALLOWED_EMAILS", "")))
    allowed_domains = set(_split_csv(cfg.get("CLERK_ALLOWED_DOMAINS", "")))
    if not allowed_emails and not allowed_domains:
        return bool(cfg.get("CLERK_ALLOW_ANY_USER", False))

    for address in emails:
        if address in allowed_emails or address.rsplit("@", 1)[-1] in allowed_domains:
            return True
    return False


def authenticate(token):
    """Return the display identity for a valid, allowed Clerk session token."""
    token = str(token or "").strip()
    if not token:
        raise ClerkAuthError("Missing session token")

    claims = verify_session_token(token)
    user_id = str(claims.get("sub", ""))

    cfg = current_app.config
    needs_lookup = bool(
        str(cfg.get("CLERK_ALLOWED_EMAILS", "")).strip() or str(cfg.get("CLERK_ALLOWED_DOMAINS", "")).strip()
    )
    emails = fetch_user_emails(user_id) if needs_lookup else []

    if not is_email_allowed(emails):
        raise ClerkAuthError("This account is not allowed to use this service")

    return emails[0] if emails else user_id
