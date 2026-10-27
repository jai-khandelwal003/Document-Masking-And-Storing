# 11 – Health Endpoints

## Goal
Let load balancers and operators check liveness and dependency readiness.

## API
`GET /health` → `{"status": "UP", "service": "smart-document-masking", "version": "1.1.0"}`

`GET /health/details` → the above plus:
- `security`: `apiKeyRequired`, `rateLimitEnabled`, `returnRawAadhaar`
- `system`: `ocrReady` (Tesseract runs), `outputWritable`, `sampleAssetsReady` (≥3 images in `app/static/samples`), `qreaderReady`, `pdfRendererReady` (PyMuPDF), `accessState`, `identityDocuments`, `storage` (per-directory file counts and bytes)
- `runtime`: `production`, `demoProfileActive`, `warnings` (e.g. `ACCESS_SHOW_CODE is enabled`)

## Authorization for `/health/details`
1. Test mode: allowed.
2. If `HEALTH_DETAILS_TOKEN` is set: header `X-Health-Token` must match.
3. Else if the API key is required: header `X-API-Key` must match.
4. Else allowed only outside production.
Otherwise 401.

## Edge cases
- `GET /health` is public (it only returns status, service name and version) so load balancers and uptime monitors work. `/health/details` still requires login plus the token rules above.
- Details expose local paths (`dbPath`, directories); keep the token secret.

## Acceptance criteria
- Production without `HEALTH_DETAILS_TOKEN` does not start (spec 02).
- Stopping Tesseract flips `ocrReady` to false without a 500.
