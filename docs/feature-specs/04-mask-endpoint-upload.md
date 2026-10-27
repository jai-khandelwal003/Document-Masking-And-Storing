# 04 – Mask Endpoint & Upload Handling

## Goal
Accept one image/PDF and return a masked image plus metadata.

## API
`POST /mask/document` (alias `POST /mask/aadhaar`), `multipart/form-data`

| Field | Default | Notes |
|-------|---------|-------|
| `file` | required | png / jpg / jpeg / pdf, max 10 MB |
| `document_type` | `aadhaar` | `aadhaar`, `pan`, `dl` (aliases `driving_license`, `driving_licence`), `all` |
| `first8_mask` | true | mask first 8 chars |
| `last4_mask` | false | mask last 4 chars |
| `mask_qr` | false | also black out QR codes |

Parameters can also come from query string or headers (`X-Document-Type`, `X-First8-Mask`, `X-Last4-Mask`, `X-Mask-QR`).

`POST /mask/verify-integrity` takes `jobId, processedAt, inputFileHash, outputFileHash, integrityToken` and returns `{"valid": true|false}`.

## Behavior
1. API key check, then rate limit (spec 03).
2. Validation: file present → valid `document_type` → at least one mask option → allowed extension → MIME sniffed from content (`mime_utils`), not just the filename.
3. `file_service.handle_file_upload` saves to `.images/` (or `ORIGINAL_UPLOADS_DIR` when persisting) as `<uuid><secure_filename>`.
4. PDFs: **every page** is rendered to JPG (PyMuPDF) at `PDF_RENDER_DPI`. More than `MAX_PDF_PAGES` (default 20) pages -> `pdf-too-many-pages`; password-protected or corrupt -> `pdf-conversion-failed`. Nothing is processed partially.
5. Masked output: `output/masked_<jobId>.jpg` (page 1 / the image). For PDFs with 2+ pages the masked pages are also assembled into `output/masked_<jobId>.pdf` (image-only, no text layer, empty metadata). Original upload is deleted afterwards unless `PERSIST_ORIGINAL_UPLOADS=true`.
6. Response includes `jobId`, `outputImageUrl`, `outputPdfUrl` (multi-page only), `pageCount`, `maskedPages` (1-based), counts, confidence, hashes, `integrityToken`, challenge/vault info.
7. An audit entry is written (spec 09).

## Integrity token
`HMAC(HASH_SECRET, "jobId|processedAt|inputHash|outputHash")`; for multi-page PDFs `outputHash` is the hash of the masked PDF. Lets a client prove a masked file came from this service unchanged.

## Edge cases
- Nothing detected → `error: "No supported document number detected"`, `message: "Masking failed"`.
- Password-protected or corrupt PDF → `error: "pdf-conversion-failed"`; too many pages → `error: "pdf-too-many-pages"`.
- Pages where nothing was detected are still included in the PDF (as rendered); a missed number stays visible, so always review the output.
- `aadhaarNumber` is empty in responses unless `RETURN_RAW_AADHAAR=true`.

## Acceptance criteria
- Renamed `.exe` → `.png` is rejected (`Invalid file content`).
- Both mask options off → 400.
- `verify-integrity` returns `valid: true` for an untouched response and `false` if any field changes.
