# 03 – Authentication, API Key & Rate Limiting

## Goal
Protect the UI and the masking API with three layers: session login (local or Clerk), optional API key, and rate limits.

## Behavior
**Session login** (`app/routes/auth.py`)
- `app.before_request` calls `enforce_login()`. Only `auth.login`, `auth.clerk_session`, `health.health` (`GET /health`, liveness only) and `static` are public.
- Unauthenticated API-like requests (`/mask/`, `/access/`, `/identity/`, `/health`, `/output/`, JSON/XHR, non-GET) get `401 {"error": "Authentication required"}`; browser GETs redirect to `/login?next=...`.
- `POST /login` compares `user_id`/`password` with `hmac.compare_digest`. `next` is only honored if it starts with `/` and not `//` (open-redirect guard).
- `POST /auth/change-password` (login required, local provider only) needs the current password and a new one of 6+ chars. It is stored as a hash in `output/access_state.sqlite3` (`app/models/auth_store.py`) and survives restarts.

**Clerk login** (`AUTH_PROVIDER=clerk`, `app/services/clerk_service.py`, `templates/clerk_login.html`)
- `/login` renders Clerk's sign-in widget (script from the frontend host decoded from `CLERK_PUBLISHABLE_KEY`).
- The browser posts Clerk's session JWT to `POST /auth/clerk/session` (public, `20 per 15 minutes`). The server verifies the RS256 signature via JWKS, `exp`/`iat`/`iss`, and `azp` if `CLERK_AUTHORIZED_PARTIES` is set.
- If `CLERK_ALLOWED_EMAILS` / `CLERK_ALLOWED_DOMAINS` is set, the user's *verified* emails are fetched with `CLERK_SECRET_KEY` and must match; with no allow-list everyone is rejected unless `CLERK_ALLOW_ANY_USER=true`.
- On success the Flask session is reset and `auth_user` is set (email or Clerk user id). `next` is accepted only as a relative path.
- `/logout` clears the Flask session and renders a page that calls `Clerk.signOut()`.
- `GET /logout`, `GET /dashboard`.

**Login rate limit**: `5 per 15 minutes` on `POST /login` only (page loads are not counted), via Flask-Limiter (no-op if the package is missing). 429 renders the login page with a retry time.

**API key** (`mask.py::_check_auth`): when `API_KEY_REQUIRED=true`, `/mask/document` requires header `X-API-Key` matching `API_KEY` (constant-time compare).

**Mask rate limit** (`mask.py::_check_rate_limit`): in-memory sliding window per client IP (`X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true`, else the socket address); defaults 20 requests / 60 s; returns 429 with `retryAfterSec`. State is per-process.

## Edge cases
- Local default credentials are `admin` / `admin123` for development only; production refuses to start with them (or a password under 10 chars).
- Production with Clerk refuses to start without keys and an allow-list.
- The app runs a single gunicorn worker (see spec 12), so the in-memory rate limit is effectively global.

## Acceptance criteria
- Wrong password never reveals which field was wrong.
- 6th login attempt within 15 min returns 429.
- Missing/invalid `X-API-Key` returns 401 when required.
- A forged, expired, wrong-issuer or non-allow-listed Clerk token never creates a session.
