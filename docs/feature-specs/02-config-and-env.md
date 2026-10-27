# 02 – Configuration & Environment

## Goal
All behavior is controlled by environment variables, read once in `app/config.py`. `.env` is loaded by `main.py` (python-dotenv). Never commit real values; `.env.example` is the template.

## Behavior
- Booleans accept `1/true/yes/on` (case-insensitive).
- `APP_ENV` (or `FLASK_ENV`) in `prod|production`, or `PRODUCTION=true`, enables production mode.
- Dev/test: if `SECRET_KEY` / `HASH_SECRET` are empty, random process-local values are generated.

## Key settings
| Group | Variables |
|-------|-----------|
| Core | `APP_ENV`, `PRODUCTION`, `PORT`, `HOST`, `DEBUG`, `SECRET_KEY`, `HASH_SECRET`, `HASH_ALGORITHM` |
| Login | `AUTH_PROVIDER` (`local`/`clerk`), `USER_ID`, `USER_PASSWORD`, `SHOW_LOGIN_CREDENTIAL_HINTS` |
| Clerk | `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`, `CLERK_AUTHORIZED_PARTIES`, `CLERK_ALLOWED_EMAILS`, `CLERK_ALLOWED_DOMAINS`, `CLERK_ALLOW_ANY_USER` |
| Browser security | `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`, `SESSION_LIFETIME_HOURS`, `SECURITY_HEADERS_ENABLED`, `SECURITY_CSP` (`off` or custom), `SECURITY_CSP_REPORT_ONLY` |
| Proxy / detection | `TRUST_PROXY_HEADERS`, `AADHAAR_ALLOW_UNCHECKED` |
| API | `API_KEY_REQUIRED`, `API_KEY`, `APP_API_KEY`, `RATE_LIMIT_*`, `HEALTH_DETAILS_TOKEN`, `RETURN_RAW_AADHAAR` |
| Access code | `ACCESS_CODE_TTL_SECONDS`, `ACCESS_TOKEN_TTL_SECONDS`, `ACCESS_MAX_ATTEMPTS`, `ACCESS_SHOW_CODE`, `ACCESS_FALLBACK_SECRET` |
| Identity OTP | `IDENTITY_REQUIRE_OTP`, `IDENTITY_OTP_*`, `IDENTITY_SHOW_OTP`, `IDENTITY_OTP_PROVIDER` |
| SMTP | `OTP_EMAIL_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/TO`, `OTP_EMAIL_USE_TLS`, `OTP_EMAIL_SUBJECT_PREFIX` |
| Remote storage | `STORAGE_BACKEND` (`local`/`s3`), `S3_BUCKET`, `S3_PREFIX`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_SSE`, `S3_FORCE_PATH_STYLE` |
| Storage | `IDENTITY_DOCS_DIR`, `UPLOAD_FOLDER`, `PERSIST_ORIGINAL_UPLOADS`, `ORIGINAL_UPLOADS_DIR`, `STORAGE_*`, `IDENTITY_DB_PATH`, `AUDIT_LOG_PATH`, `ACCESS_STATE_*` |
| OCR | `TESSERACT_CMD`, `PDF_RENDER_DPI` (clamped 120–300), `STRICT_QREADER_IMPORT` |

Fixed limits: upload max 10 MB, extensions `png/jpg/jpeg/pdf`.

## Production guardrails (`_apply_runtime_guardrails`)
The app raises `RuntimeError` at startup in production if:
- `SECRET_KEY` or `HASH_SECRET` is missing
- `API_KEY_REQUIRED=true` but `API_KEY` is empty
- `HEALTH_DETAILS_TOKEN` is empty
- `ACCESS_SHOW_CODE` or `IDENTITY_SHOW_OTP` is true, or OTP provider is `demo`
- OTP provider is `email` with missing SMTP values or placeholder values
- `SESSION_COOKIE_SECURE=false` (production must use HTTPS cookies)
- `STORAGE_BACKEND=s3` without credentials (or an AWS credential source)
- `AUTH_PROVIDER=local` with a default or short (under 10 chars) `USER_PASSWORD`
- `AUTH_PROVIDER=clerk` without both keys, or without an allow-list (unless `CLERK_ALLOW_ANY_USER=true`)

## Edge cases
- Defaults are demo-friendly (`ACCESS_SHOW_CODE=true`, `IDENTITY_OTP_PROVIDER=demo`, `USER_PASSWORD=admin123`); production refuses to start until they are overridden.

## Acceptance criteria
- Starting with `APP_ENV=production` and no secrets fails fast with a clear message.
- `.env.example` lists every variable above with placeholder values only.
