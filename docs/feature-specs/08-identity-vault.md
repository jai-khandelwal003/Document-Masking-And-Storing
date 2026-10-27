# 08 – Identity Vault & Linked Documents

## Goal
Let one person (identified by a hash of their primary document number) keep related documents (Aadhaar, PAN, DL, other uploads) linked together, so masking one document can surface the others after unlock.

## Concepts
- **Primary identifier**: Aadhaar if 12 digits, else PAN, else DL (`_identity_primary_identifier`).
- **Profile key**: hash of that identifier (`documentHash`); the raw number is not stored.
- **PIN mode** derived from masking choice: first8-masked → PIN is `last4`; last4-masked → PIN is `first8`; fully masked → PIN is `first8` of the original.
- **Vault**: per-`jobId` record created by `register_identity_vault` (in `access_service.py`).

## Storage (`app/models/identity_store.py`, SQLite `output/identity_profiles.sqlite3`)
- `identity_profiles(profile_key PK, created_at, updated_at)`
- `linked_documents(id, profile_key FK, doc_type, doc_label, doc_id, file_key, source, added_at)` with `UNIQUE(profile_key, doc_type, doc_id, file_key)`; deleting a profile cascades.
- Uploaded files live in `output/identity_docs/<profile>/<fileKey>_<name>`.

## API
| Route | Purpose |
|-------|---------|
| `POST /identity/register-documents` | register documents for a person by `aadhaarNumber` |
| `POST /identity/link-documents` | upsert profile and add metadata records |
| `POST /identity/unlink-document` | remove by `type` + `id` (+ `fileKey`) |
| `POST /identity/upload-document` | upload a pdf/png/jpg (MIME-sniffed) and link it |
| `GET /identity/documents?profileKey=` | list linked documents |

## Edge cases
- Re-adding the same document updates label/source/time instead of duplicating.
- The mask response only returns sanitized metadata (type, id, label, source, fileName, fileKey).
- Max upload size for vault documents: `IDENTITY_DOC_MAX_BYTES` (default 5 MB).

## Acceptance criteria
- Masking a second document of the same person reports `profileExists: true` and the already-linked documents.
- `unlink-document` on a missing record returns 404.
