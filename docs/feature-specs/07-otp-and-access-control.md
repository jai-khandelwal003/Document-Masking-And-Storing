# 07 – OTP & Secure Access Control

## Goal
The masked output is served openly under `/output/<file>`, but retrieving it through the secure path, or the underlying documents, requires proving knowledge of the visible fragment plus a one-time code.

## Flow A – Secure masked-image access (`/access/*`)
1. On masking, `register_job_for_access` stores a verifier for the job. Challenge types:
   - `last4` / `visible_fragment` – the characters left visible after masking
   - `fallback_secret` – used only when everything is masked and `ACCESS_FALLBACK_SECRET` is set
2. `POST /access/request-code` `{jobId, last4 | visibleFragment | fallbackPin}` → 6-digit code (shown in the response only if `ACCESS_SHOW_CODE=true`).
3. `POST /access/verify` `{..., code}` → signed token (`URLSafeTimedSerializer`, salt `aadhaar-output-access`).
4. `GET /output/secure?token=...` returns the file. Token lifetime `ACCESS_TOKEN_TTL_SECONDS` (default 300 s).
5. `GET /output/<file>` is only served to the session that created the file (tracked in `session["owned_outputs"]`, last 50); anyone else gets 403 and must use this flow.

## Flow B – Identity vault unlock (`/identity/*`)
1. `POST /identity/request-otp` `{jobId, recipientEmail}` → OTP via the configured provider:
   - `demo`: OTP returned in the API response
   - `email`: sent over SMTP (STARTTLS + login); recipient must match a basic email regex
2. `POST /identity/unlock` `{jobId, pin, otp}`: PIN must match the vault (`last4` or `first8` mode); OTP required if `IDENTITY_REQUIRE_OTP=true`. Returns a token (salt `identity-doc-access`).
3. `GET /identity/documents?token=` (JSON) or `GET /identity/view?token=` (HTML), and `GET /identity/document-file?token=&file=` to download one file.

## Security properties
- Codes/OTPs/PINs are stored only as HMAC-SHA256 hashes; compared with `hmac.compare_digest`.
- Attempt limits (`ACCESS_MAX_ATTEMPTS`, `IDENTITY_OTP_MAX_ATTEMPTS`), expiry (`*_TTL_SECONDS`), and an OTP resend cooldown (`IDENTITY_OTP_COOLDOWN_SECONDS`, 429 with `retryAfterSec`).
- State is guarded by a lock and persisted to `output/access_state.sqlite3` (`ACCESS_STATE_PERSIST`).
- File downloads must resolve inside `output/identity_docs/`.

## Edge cases
- SMTP failure → OTP is discarded and the API returns 502.
- Demo OTP provider always exposes the OTP; production guardrails forbid it (spec 02).
- Unknown `jobId` → 404.

## Acceptance criteria
- Wrong fragment → 403; wrong/expired code → 401/400; after max attempts → 429.
- A token for job A cannot fetch job B's files.
