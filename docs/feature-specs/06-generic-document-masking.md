# 06 – PAN, Driving Licence & QR Masking

## Goal
Mask PAN and Indian Driving Licence numbers, and optionally any QR code.

## PAN / DL (`app/services/mask_utils/document_generic.py`)
- OCR passes: PSM 6 → PSM 11 → binarized PSM 6 (later passes only if nothing found yet).
- Candidates are built from 1–3 adjacent tokens, uppercased and stripped of non-alphanumerics.
- **PAN**: `[A-Z]{5}[0-9]{4}[A-Z]`.
- **DL** patterns: `dl-india-standard` (`XX99 9999 9999999`), `dl-india-legacy`, `dl-india-compact`. Digits after the 2-letter state code are OCR-corrected (`O→0`, `I→1`, …).
- Partial masking is proportional: the box width is split by character count, then the first 8 and/or last 4 characters are blacked out. Both options → whole value.
- Confidence: PAN `min(0.98, 0.62 + 0.1n)`, DL `min(0.97, 0.58 + 0.1n)`.

## `document_type` routing (`mask_service.py`)
| Type | Runs |
|------|------|
| `aadhaar` | Aadhaar only |
| `pan` / `dl` | PAN/DL masker on the output copy |
| `all` | Aadhaar, then PAN + DL on the result |

## QR (`mask_utils/qreader.py`)
- QReader detects QR quads; if none, falls back to OpenCV `QRCodeDetector`.
- Quads are filled black with `cv2.fillPoly`. Engine is reported as `qreader`, `opencv-fallback` or `none`.
- If `qreader` is not installed, masking continues and the message notes that QR was skipped.
- QR-only success returns "QR masked successfully."

## Edge cases
- A DL regex can match random alphanumerics; patterns are strict to limit this.
- Failures inside QR masking are logged and reported as "not detected".

## Acceptance criteria
- `document_type=pan` on a PAN card covers the first 8 of the 10 characters by default.
- `mask_qr=true` on a document with a QR leaves a black polygon and `noOfQrDetected >= 1`.
