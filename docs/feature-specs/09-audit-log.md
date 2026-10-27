# 09 – Audit Log

## Goal
Keep a tamper-evident-by-convention record of who masked what, without storing any document number.

## Behavior (`app/models/audit_store.py`)
After every successful `/mask/document` call, `log_mask_job` writes:
- a row in SQLite table `audit_entries(timestamp, user, doc_type, job_id, mask_mode, regions_masked)` in `output/access_state.sqlite3`
- a line in `output/audit.log`: `<time> | user=… doc_type=… job_id=… mask_mode=… regions_masked=…`

`mask_mode` is `first8`, `last4` or `both`; `regions_masked` is Aadhaar + QR regions found.

## API
`GET /analytics/audit-log?limit=20` (login required) → `{"entries": [...]}` newest first. `limit` is clamped to 1–200.

## Configuration
`AUDIT_LOG_PATH` (default `output/audit.log`), `ACCESS_STATE_DB_PATH`.

## Edge cases
- The file handler is attached once (checked by path) so repeated calls don't duplicate log lines.
- A non-numeric `limit` returns 400 `{"error": "limit must be an integer"}`.

## Acceptance criteria
- Each masking request adds exactly one DB row and one log line.
- No Aadhaar/PAN/DL value ever appears in either.
