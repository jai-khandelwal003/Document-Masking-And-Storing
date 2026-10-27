# 05 – Aadhaar Detection & Masking

## Goal
Find the 12-digit Aadhaar number in a document image and black out the requested part.

## Behavior (`app/services/mask_utils/aadhaar.py`)
1. Enlarge the image and boost contrast (`image_utils`), convert to grayscale.
2. Run Tesseract three times: normal PSM 6, normal PSM 11, binarized PSM 6. Stop at the first pass that finds a hit.
3. `aadhar_helpers.detect_aadhaar_number` looks for 12 digits spread over 1–3 OCR tokens. OCR confusions are corrected first (`O→0`, `I/l/|→1`, `S→5`, `B→8`, …).
   - **Strict**: passes the Verhoeff checksum (`validate_addhar.py`).
   - **Fallback** (only if no strict hit): 12 digits starting with 2–9.
4. The number's box is split into three 4-digit groups. Mask choice:
   - first8 only → groups 1–2, last4 only → group 3, both → all three.
5. A repeat scan masks any other occurrence of the same number on the page.
6. Boxes are scaled back to the original image size and drawn in black.

## Outputs
`(detected: bool, aadhaar_number: str, masked_count: int)`; confidence in the response is `min(0.98, 0.62 + 0.08 × count)`.

## Edge cases
- Duplicate boxes from different OCR passes are de-duplicated on a 25 px grid.
- The fallback pattern can mask a non-Aadhaar 12-digit number (false positive) – acceptable for a masking tool.
- Poor scans may produce no hit; the API returns "Masking failed" instead of an unmasked file.

## Acceptance criteria
- A clear Aadhaar sample with `first8_mask=true` has the first 8 digits covered and the last 4 readable.
- A valid Verhoeff number is always preferred over an unchecked candidate.
