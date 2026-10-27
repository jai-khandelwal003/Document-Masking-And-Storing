# 13 – Testing & Evaluation

## Goal
Automated tests guard behavior and security rules; an evaluation script measures masking accuracy.

## Unit tests (`tests/`, run with `make test` or `python -m unittest discover -s tests`)
| File | Covers |
|------|--------|
| `test_health.py` | `/health`, `/health/details` authorization and payload |
| `test_upload.py` | upload validation and masking responses |
| `test_upload_persistence.py` | `PERSIST_ORIGINAL_UPLOADS` behavior |
| `test_mask_security.py` | API key, rate limit, integrity token, MIME checks |
| `test_access_control.py` | access codes, OTP, tokens, identity unlock/view |
| `test_identity_vault_fullmask.py` | vault behavior when everything is masked |
| `test_auth_clerk.py` | Clerk login page and session exchange, JWT verification (signature/expiry/issuer/azp), allow-list, local password persistence, output ownership, proxy trust, production guardrails |
| `test_storage.py` | S3 backend (fake client): upload/serve/delete, 502 on outage, no leftover local files, retention cleanup, health, config guardrails |
| `test_security_headers.py` | security headers, per-request CSP nonce on every inline script, cache rules, cookie flags, service-worker rules |
| `test_scan_secrets.py` | secret scanner: token patterns, placeholders, blocked files |
| `test.py` | general/legacy checks |

Tests call `_reset_access_state_for_tests()` to clear in-memory and persisted access state.

`tests/_isolation.py` is imported first by every test module and points `IDENTITY_DOCS_DIR`, the SQLite/audit paths and upload folders at a temp directory, so running the tests never reads or deletes real documents in `output/`.

## Accuracy evaluation (`tools/evaluate_metrics.py`)
- Input: a CSV like `evaluation/labels_template.csv` with columns `filename,document_type,expected_detected`.
- It posts each sample to a running service with `requests` and compares the `aadhaarDetected` / `panDetected` / `drivingLicenceDetected` flag per type to the label, then reports metrics per document type.
- `python tools/generate_synthetic_samples.py` creates 42 synthetic images (no real data) and `evaluation/labels_synthetic.csv`; run the evaluation with `--in-process` (no server or login needed), or against a running service with `--cookie` / `--api-key`.
- Measured results and their caveats are in `evaluation/RESULTS.md`. Real identity documents must never be added.

## CI
`.github/workflows/ci.yml` runs the unit tests on every push and pull request.

## Edge cases
- OCR-dependent tests need Tesseract installed (or mocks).
- Never add real identity documents to `tests/` or `evaluation/`.

## Acceptance criteria
- `make test` passes on a clean checkout with `.env.example` defaults.
- A new route must come with a test for its auth and error paths.
