# jg-doc-masking-service

Smart Aadhaar document masking service with OCR-based detection and a presentation-ready web UI.

> **Disclaimer:** this is a learning/portfolio project. OCR-based masking can miss numbers, so a person must check
> every output. It is not certified for, and makes no claim of compliance with, any law or regulation (including
> India's DPDP Act or Aadhaar Act rules). Do not use it on real identity documents without your own legal and security review.

## Authentication

Two login modes, selected by `AUTH_PROVIDER` (`local` or `clerk`; auto-selects `clerk` when both Clerk keys are set).

**Clerk (hosted login)**
1. Create an application at https://dashboard.clerk.com and copy the publishable and secret keys.
2. Set `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` and who may sign in: `CLERK_ALLOWED_EMAILS` and/or `CLERK_ALLOWED_DOMAINS`.
   Anyone can sign up on a Clerk instance, so without an allow-list every sign-in is rejected (set `CLERK_ALLOW_ANY_USER=true` only for demos).
3. Start the app and open `/login`. The page loads Clerk's sign-in widget; after sign-in the browser sends Clerk's session
   token to `POST /auth/clerk/session`, where the server verifies the signature (JWKS), expiry, issuer and optional `azp`,
   checks the allow-list against the user's *verified* email, and only then starts a Flask session.

**Local**: `USER_ID` / `USER_PASSWORD`. A password changed in the UI is stored as a hash in `output/access_state.sqlite3`.
Production refuses to start with the default or a short password.

## Cloud storage (optional)

By default documents live on local disk under `output/`. Set `STORAGE_BACKEND=s3` to keep them in any S3-compatible
bucket instead (AWS S3, Cloudflare R2, Supabase Storage, MinIO):

```
STORAGE_BACKEND=s3
S3_BUCKET=my-private-bucket
S3_PREFIX=docmask
S3_REGION=ap-south-1
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
# S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com   (R2 / MinIO / Supabase)
# S3_SSE=            (empty if your provider rejects the encryption header)
```

- Use a **private** bucket with *Block all public access* on. The app never hands out bucket URLs: masked images, vault
  documents and kept originals are streamed through the app, so the login, session-ownership and OTP checks still apply.
- What moves: masked images (`masked/`), kept originals (`uploads/`, only if `PERSIST_ORIGINAL_UPLOADS=true`) and
  identity-vault documents (`identity_docs/`). Files are written to `output/` only while being processed, then uploaded and deleted locally.
- What stays local: the SQLite databases (access state, identity profiles, audit log). They hold hashes and metadata, not documents.
- Objects are sent with server-side encryption (`S3_SSE=AES256` by default) and `STORAGE_CLEANUP_ENABLED` also deletes old
  bucket objects at startup. For real retention, add a bucket lifecycle rule too.
- Give the access key only `s3:PutObject`, `GetObject`, `DeleteObject`, `ListBucket` on that bucket. If the bucket is
  unreachable, uploads fail with HTTP 502 and nothing is left half-saved.
- Keeping Aadhaar-related documents with a third-party cloud provider has legal consequences. Check your obligations first.

## Known limitations

- **Single worker by design.** Access codes, OTPs and the identity vault are kept in process memory (snapshotted to SQLite),
  so the container runs `gunicorn -w 1 --threads 8`. Do not add workers without moving that state fully into a database.
- **Masked output access.** `/output/<file>` is served only to the session that created it. Anyone else must use the
  fragment + one-time-code flow (`/output/secure`). Lose the session and you need the code flow.
- **Login required everywhere** except `/login` and `GET /health` (liveness only); `/health/details` needs login plus a token.
- **Rate limiting** is per process and uses `X-Forwarded-For` only when `TRUST_PROXY_HEADERS=true` (set for the bundled nginx).
- **OCR accuracy** is modest on noisy images; see `evaluation/RESULTS.md` for measured numbers (synthetic data only).
- **Tests are isolated** from your real `output/` folder (they run against a temp directory), so running them is safe.
- PDFs: only the first page is processed. Original uploads are deleted after processing unless `PERSIST_ORIGINAL_UPLOADS=true`.

## Panel Demo Guide

### 1. Prerequisites

- Python 3.12+
- Tesseract OCR installed on machine
- Windows path typically used: `C:\Program Files\Tesseract-OCR\tesseract.exe`

If Tesseract is installed in a different location, set:

```powershell
$env:TESSERACT_CMD="C:\path\to\tesseract.exe"
```

Optional security variables:

```powershell
$env:HASH_SECRET="your_strong_secret_for_hmac"
$env:HASH_ALGORITHM="sha256"
$env:API_KEY_REQUIRED="true"
$env:API_KEY="panel-demo-key"
$env:RATE_LIMIT_ENABLED="true"
$env:RATE_LIMIT_REQUESTS="20"
$env:RATE_LIMIT_WINDOW_SECONDS="60"
$env:RETURN_RAW_AADHAAR="false"
$env:STRICT_QREADER_IMPORT="false"
$env:APP_ENV="development"
$env:PRODUCTION="false"
```

`STRICT_QREADER_IMPORT=false` is recommended for faster startup in local/dev. Set it to `true` only if you want strict runtime qreader import validation.

Optional branding variables for UI and PDF header:

```powershell
$env:BRAND_PROJECT_TITLE="Smart Document Masking"
$env:BRAND_COLLEGE_NAME="ABC Institute of Technology"
$env:BRAND_DEPARTMENT="Department of Computer Science"
$env:BRAND_GUIDE_NAME="Dr. Your Guide Name"
$env:BRAND_STUDENT_NAME="Your Name"
$env:BRAND_LOGO_URL="https://example.com/college-logo.png"
```

### 2. Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` before demo or deployment, especially:

- `SECRET_KEY`
- `HASH_SECRET`
- `API_KEY_REQUIRED` / `API_KEY`

Production safety notes:

- Set `APP_ENV=production` (or `PRODUCTION=true`) in production deployments.
- Production startup fails fast if `SECRET_KEY` or `HASH_SECRET` is missing.
- Production startup fails fast if demo settings are enabled:
	- `ACCESS_SHOW_CODE=true`
	- `IDENTITY_SHOW_OTP=true`
	- `IDENTITY_OTP_PROVIDER=demo`

This repository includes a CI workflow at `.github/workflows/ci.yml` that runs unit tests on every push and pull request.

### 3. Run Locally

```powershell
python main.py
```

Quick startup tips (PowerShell):

```powershell
# Show registered routes at startup
$env:SHOW_ROUTES="true"
python main.py

# Force a specific free port if default is busy
$env:PORT="3010"
python main.py
```

Open:

- App: `http://localhost:3000/`
- Public Health: `http://localhost:3000/health`
- Detailed Health: `http://localhost:3000/health/details`

`/health` is intentionally minimal for safer public exposure.

`/health/details` includes security and system diagnostics. Access policy:

- If `HEALTH_DETAILS_TOKEN` is set, send header `X-Health-Token`.
- Else if API key protection is enabled, send header `X-API-Key`.
- In non-production local/dev mode, details are available without auth.

### 3.1 One-Command Panel Runbook

Use this PowerShell block to start a reliable demo profile in one go:

```powershell
$env:SHOW_ROUTES="false";
$env:DEBUG="false";
$env:RETURN_RAW_AADHAAR="false";
$env:ACCESS_SHOW_CODE="true";
$env:IDENTITY_SHOW_OTP="true";
$env:IDENTITY_OTP_PROVIDER="demo";
python main.py
```

Notes:

- This profile is for panel demonstration only.
- For production-style behavior, set `ACCESS_SHOW_CODE=false` and `IDENTITY_SHOW_OTP=false`.

### 3.2 Production Runbook (Must)

Set these values before starting the app in production:

```powershell
$env:APP_ENV="production"
$env:PRODUCTION="true"
$env:SECRET_KEY="<long-random-secret>"
$env:HASH_SECRET="<long-random-secret>"
$env:ACCESS_SHOW_CODE="false"
$env:IDENTITY_SHOW_OTP="false"
$env:IDENTITY_OTP_PROVIDER="email"
$env:API_KEY_REQUIRED="true"
$env:API_KEY="<strong-api-key>"
$env:HEALTH_DETAILS_TOKEN="<health-details-token>"
python main.py
```

One-command production launch (PowerShell):

```powershell
./tools/run_production.ps1
```

Custom port:

```powershell
./tools/run_production.ps1 -Port 3010
```

The script enforces production-safe flags, checks required environment variables,
and stops early with a clear error if any required secret/token is missing.

### 3.3 Go-Live Checklist

1. Set strong values for `SECRET_KEY`, `HASH_SECRET`, `API_KEY`, and `HEALTH_DETAILS_TOKEN`.
2. Keep `ACCESS_SHOW_CODE=false`, `IDENTITY_SHOW_OTP=false`, and `IDENTITY_OTP_PROVIDER=email`.
3. Keep `API_KEY_REQUIRED=true` and send `X-API-Key` from trusted clients.
4. Keep `/health` public and restrict `/health/details` using `X-Health-Token`.
5. Verify with tests: `python -m unittest discover -s tests -p "test*.py"`.

### 3.4 Production Deployment (Docker + Nginx + TLS)

This repository includes a complete production stack:

- `docker-compose.production.yml` (app + reverse proxy)
- `deployment/nginx/default.conf` (HTTPS proxy config)
- `deployment/nginx/default.conf.template` (domain-ready hardened template)
- `tools/generate_production_env.ps1` (secure env file generator)
- `tools/set_nginx_domain.ps1` (one-command domain config generator)
- `tools/backup_output.ps1` (output/state backup)

Steps:

1. Generate `.env.prod` with strong secrets:

```powershell
./tools/generate_production_env.ps1 -OutputPath .env.prod -OtpEmailUsername "your-real-email@example.com" -OtpEmailPassword "your-app-password" -OtpEmailFrom "your-real-email@example.com"
```

2. Generate Nginx config for your domain:

```powershell
./tools/set_nginx_domain.ps1 -Domain "api.example.com" -IncludeWww
```

3. Place TLS certificate files under `deployment/certs/`:

- `fullchain.pem`
- `privkey.pem`

4. Start production stack:

```powershell
docker compose -f docker-compose.production.yml up -d --build
```

5. Verify:

```powershell
curl https://<your-domain>/health
curl -H "X-Health-Token: <HEALTH_DETAILS_TOKEN>" https://<your-domain>/health/details
```

6. Create backup archive:

```powershell
./tools/backup_output.ps1
```

Note: `tools/run_production.ps1` now validates required OTP email settings when `IDENTITY_OTP_PROVIDER=email`.

### 4. Presentation Flow (2-3 minutes)

1. Show live API heartbeat chip (`API Online`) at top of page.
2. Upload an Aadhaar image via drag/drop.
3. Choose a quick preset (`Privacy Safe` recommended).
4. Run masking and highlight:
	- workflow steps,
	- processing progress,
	- KPI cards.
5. Demonstrate visual validation:
	- side-by-side before/after,
	- interactive compare slider.
6. Show evidence features:
	- raw API response,
	- export report JSON,
	- export branded audit PDF,
	- copy cURL command.
7. Optionally click `Start Demo Mode` for guided walkthrough overlay.
8. Use `Theme` toggle (light/dark) and show live session analytics chart.
9. Use `Start Panel Pitch` for a live 60-second explanation script and `Project Abstract` for concise project summary.
10. Use `Load Sample 1/2/3` for one-click demo dataset, `Security Posture Score` for live security readiness, and `Generate Highlight Overlay` for visual masking proof.
11. Verify `System Checks` chips (OCR, output write permission, sample assets) are green before starting the panel run.

### 5. API Endpoint

`POST /mask/document` (preferred) and `POST /mask/aadhaar` (legacy-compatible) (multipart form-data)

Fields:

- `file`: image file (`jpg`, `jpeg`, `png`)
- `document_type`: `aadhaar|pan|dl|all` (default: `aadhaar`)
- `first8_mask`: `true/false`
- `last4_mask`: `true/false`
- `mask_qr`: `true/false`

Document behavior:

- `aadhaar`: masks Aadhaar number segments using selected Aadhaar mode.
- `pan`: detects and masks PAN format (`ABCDE1234F`).
- `dl`: detects and masks Driving Licence number formats.
- `all`: attempts Aadhaar, PAN, and Driving Licence masking in one pass.

Response includes:

- `aadhaarDetected`
- `noOfAadhaarDetected`
- `panDetected`
- `noOfPanDetected`
- `drivingLicenceDetected`
- `noOfDrivingLicenceDetected`
- `detectionConfidence` (per document type + overall score)
- `matchedPatterns` (e.g., PAN/DL format matched)
- `maskedRegions` (counts by type + total)
- `noOfQrDetected`
- `outputImageUrl`
- `aadhaarHash` (HMAC-SHA256 of detected Aadhaar)
- `aadhaarPreview` (privacy-safe preview like `XXXXXXXX1234`)
- `inputFileHash` (SHA-256 of uploaded file)
- `outputFileHash` (SHA-256 of masked output)
- `hashAlgorithm`
- `jobId`
- `processedAt`
- `identityVaultEnabled`
- `identityPinMode`
- `identityPinHint`

Security behavior:

- Raw Aadhaar (`aadhaarNumber`) is hidden by default.
- Set `RETURN_RAW_AADHAAR=true` only if your internal policy requires it.
- If `API_KEY_REQUIRED=true`, send header `X-API-Key`.
- Per-IP rate limiting is enabled by default for `/mask/aadhaar`.

### 5.2 Generic Endpoint Example

```bash
curl -X POST "http://localhost:3000/mask/document" \
	-F "file=@sample.jpg" \
	-F "document_type=all" \
	-F "first8_mask=true" \
	-F "last4_mask=false" \
	-F "mask_qr=false"
```

### 5.3 Evaluation Dataset and Metrics (Major Project)

To keep your report fully defensible in viva, generate metrics from your own labeled dataset.

1. Create labels CSV using `evaluation/labels_template.csv` format:

- `filename,document_type,expected_detected`
- `document_type` must be one of `aadhaar`, `pan`, `dl`, `all`
- `expected_detected` should be `1` or `0`

2. Start the API server.

3. Run the evaluator:

PowerShell:

`python tools/evaluate_metrics.py --base-url http://localhost:3000 --images-dir app/static/samples --labels-csv evaluation/labels_template.csv`

The script prints precision, recall, F1, average latency, and overall metrics in a table.

Export panel-ready metrics artifacts:

`python tools/evaluate_metrics.py --base-url http://localhost:3000 --images-dir app/static/samples --labels-csv evaluation/labels_template.csv --out-json evaluation/metrics_summary.json --out-csv evaluation/metrics_summary.csv`

### 5.4 Architecture Flow

Document pipeline (high level):

1. Upload image
2. OCR and token extraction
3. Document matcher (Aadhaar/PAN/DL)
4. Region masking
5. Hash and integrity token generation
6. Optional last4 + one-time code access flow
7. Secure output delivery

Suggested diagram notation for report:

`Client -> Flask API -> OCR Engine -> Detector (Aadhaar/PAN/DL) -> Masker -> Hash/Integrity -> Storage/Output`

### 5.5 Threat Model and Security Notes

Key risks and mitigations included in this project:

1. Brute-force API abuse
- Mitigation: per-IP rate limiting and optional API key enforcement.

2. Sensitive identifier exposure
- Mitigation: raw Aadhaar hidden by default; privacy-safe previews and HMAC hashes returned.

3. Response tampering
- Mitigation: integrity token built from job metadata and file hashes, plus verify-integrity endpoint.

4. Unauthorized output access
- Mitigation: optional last4 + one-time code verification and short-lived secure output token.

5. Environment mismatch failures (demo day)
- Mitigation: startup logs show active Python executable and qreader availability.

Masked files are served from:

- `/output/<filename>`

### 5.1 Secure Access (Visible Fragment + One-Time Code)

This optional flow adds a verification layer before downloading a masked output:

1. Call `POST /access/request-code` with one of these payload styles:

- Last 4 visible digits mode:

```json
{
	"jobId": "<jobId_from_mask_response>",
	"last4": "1234"
}
```

- Visible fragment mode (e.g., when only last4 is masked):

```json
{
	"jobId": "<jobId_from_mask_response>",
	"visibleFragment": "12345678"
}
```

- Full-mask fallback mode (when no Aadhaar characters remain visible):

```json
{
	"jobId": "<jobId_from_mask_response>",
	"fallbackPin": "<your_fallback_secret>"
}
```

2. Call `POST /access/verify` with matching fields + `code`:

```json
{
	"jobId": "<jobId_from_mask_response>",
	"last4": "1234",
	"code": "<one_time_code>"
}
```

3. Use returned `secureDownloadUrl` (`/output/secure?token=...`) to download.

Environment controls:

- `ACCESS_CODE_TTL_SECONDS`
- `ACCESS_TOKEN_TTL_SECONDS`
- `ACCESS_MAX_ATTEMPTS`
- `ACCESS_SHOW_CODE` (set `true` only for demo/testing environments)
- `ACCESS_STATE_PERSIST` (default `true`; keeps OTP/code/access state across app restarts)
- `ACCESS_STATE_DB_PATH` (optional custom sqlite path, default `output/access_state.sqlite3`)
- `ACCESS_FALLBACK_SECRET` (required only for full-mask fallback mode)

### 5.6 PIN Unlock + Linked Document View

This optional flow unlocks linked document metadata using PIN + OTP (2-factor) derived from the scanned identifier (Aadhaar, PAN, or Driving Licence).

PIN mode rules:

- If `first8_mask=true` and `last4_mask=false`, PIN mode becomes `last4`.
- If `first8_mask=false` and `last4_mask=true`, PIN mode becomes `first8`.
- If `first8_mask=true` and `last4_mask=true` (full masking), PIN mode becomes `first8` so OTP unlock still works for PAN/DL/Aadhaar.

After calling `/mask/document`, check these fields in response:

- `identityVaultEnabled`
- `identityPinMode`
- `identityPinHint`

Step 0 (optional but recommended): register important documents against a person identifier in secure registry:

`POST /identity/register-documents`

```json
{
	"aadhaarNumber": "123456781234",
	"documents": [
		{"type": "pan", "id": "ABCDE1234F", "label": "PAN", "source": "vault"},
		{"type": "dl", "id": "DL-REF-001", "label": "Driving Licence", "source": "vault"}
	]
}
```

When the same identifier is scanned later, these documents are auto-linked by identifier hash.

Step 1: request OTP:

`POST /identity/request-otp`

```json
{
	"jobId": "<jobId_from_mask_response>",
	"recipientEmail": "user@example.com"
}
```

`recipientEmail` is optional. If provided, OTP will be targeted to that user for the current request.

Step 2: unlock identity-linked documents:

`POST /identity/unlock`

```json
{
	"jobId": "<jobId_from_mask_response>",
	"pin": "1234",
	"otp": "654321"
}
```

Unlock response also returns `documentsUrl` so frontend can directly navigate user after PIN + OTP verification.

Step 3: fetch linked documents:

`GET /identity/documents?token=<accessToken>`

Optionally add linked documents manually:

`POST /identity/link-documents`

```json
{
	"jobId": "<jobId_from_mask_response>",
	"documents": [
		{"type": "pan", "id": "ABCDE1234F", "label": "PAN", "source": "vault"},
		{"type": "dl", "id": "DL-REF-001", "label": "Driving Licence", "source": "vault"}
	]
}
```

Identity OTP environment controls:

- `IDENTITY_REQUIRE_OTP` (default `true`)
- `IDENTITY_OTP_TTL_SECONDS`
- `IDENTITY_OTP_MAX_ATTEMPTS`
- `IDENTITY_SHOW_OTP` (default `false`; set `true` only for demo/testing)
- `IDENTITY_OTP_PROVIDER` (`demo` or `email`)

For production-like OTP delivery, use email provider:

```powershell
$env:IDENTITY_OTP_PROVIDER="email"
$env:OTP_EMAIL_SMTP_HOST="smtp.gmail.com"
$env:OTP_EMAIL_SMTP_PORT="587"
$env:OTP_EMAIL_USE_TLS="true"
$env:OTP_EMAIL_USERNAME="your-email@domain.com"
$env:OTP_EMAIL_PASSWORD="your-app-password"
$env:OTP_EMAIL_FROM="your-email@domain.com"
$env:OTP_EMAIL_TO="recipient@domain.com"
```

When `IDENTITY_OTP_PROVIDER=email`, OTP is delivered via SMTP and is not returned in API response unless `IDENTITY_SHOW_OTP=true`.

### 6. Panel-Day Checklist

1. Start app and verify `http://localhost:3000/health` returns `UP`.
2. Keep one clean sample Aadhaar image ready.
3. Hard refresh browser once (`Ctrl+F5`) before demo.
4. Keep QR masking off unless explicitly asked.
5. Export one report JSON at the end as proof artifact.

### 7. Troubleshooting

- If page does not load: ensure app is running on port `3000`.
- If OCR is not working: verify Tesseract installation/path.
- If stale UI appears: hard refresh (`Ctrl+F5`).