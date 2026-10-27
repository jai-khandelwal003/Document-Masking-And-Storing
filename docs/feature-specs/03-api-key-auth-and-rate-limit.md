# 03 – Authentication, API Key & Rate Limiting

## Goal
Protect the UI and the masking API with three layers: session login, optional API key, and rate limits.

## Behavior
**Session login** (`app/routes/auth.py`)
- `app.before_request` calls `enforce_login()`. Only `auth.login` and `static` are public.
- Unauthenticated API-like requests (`/mask/`, `/access/`, `/identity/`, `/health`, `/output/`, JSON/XHR, non-GET) get `401 {"error": "Authentication required"}`; browser GETs redirect to `/login?next=...`.
- `POST /login` compares `user_id`/`password` with `hmac.compare_digest`. `next` is only honored if it starts with `/` and not `//` (open-redirect guard).
- `POST /auth/change-password` (login required) needs the current password and a new one of 6+ chars. The new password is held in memory (`RUNTIME_USER_PASSWORD`) and is lost on restart.
- `GET /logout`, `GET /dashboard`.

**Login rate limit**: `5 per 15 minutes` via Flask-Limiter (no-op if the package is missing). 429 renders the login page with a retry time.

**API key** (`mask.py::_check_auth`): when `API_KEY_REQUIRED=true`, `/mask/document` requires header `X-API-Key` matching `API_KEY` (constant-time compare).

**Mask rate limit** (`mask.py::_check_rate_limit`): in-memory sliding window per client IP (`X-Forwarded-For` first, else remote addr); defaults 20 requests / 60 s; returns 429 with `retryAfterSec`. State is per-process.

## Edge cases
- Default credentials are `admin` / `admin123` unless `USER_ID` / `USER_PASSWORD` are set.
- With several gunicorn workers, the in-memory rate limit is per worker.
- `X-Forwarded-For` is trusted as-is; it should only be exposed behind the bundled nginx.

## Acceptance criteria
- Wrong password never reveals which field was wrong.
- 6th login attempt within 15 min returns 429.
- Missing/invalid `X-API-Key` returns 401 when required.
