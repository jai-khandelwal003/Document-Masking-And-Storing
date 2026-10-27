# 01 – Overview & Architecture

## Goal
Smart Document Masking is a Flask service that masks sensitive identifiers (Aadhaar, PAN, Driving Licence, QR codes) in uploaded images/PDFs, and lets the owner later unlock the original documents through a PIN + OTP flow.

## Behavior
1. A logged-in user uploads a file to `POST /mask/document`.
2. The service runs OCR (Tesseract) to find identifier numbers and draws black boxes over them.
3. The masked JPG is saved under `output/` and a `jobId` is returned with an integrity token.
4. The owner can request a verification code / OTP for that `jobId` and receive a short-lived token to download the masked output or the linked identity documents.

## Files involved
| Area | File |
|------|------|
| App factory, guardrails, output routes | `app/__init__.py` |
| Config from env | `app/config.py` |
| Entry point | `main.py` |
| Routes | `app/routes/{auth,mask,access,health}.py` |
| Masking engine | `app/services/mask_service.py`, `app/services/mask_utils/*` |
| Access / OTP / vault | `app/services/access_service.py`, `otp_delivery_service.py` |
| Persistence | `app/models/identity_store.py`, `audit_store.py` |
| Cleanup | `app/services/storage_cleanup.py` |
| UI | `app/templates/*.html`, `app/static/` |

## Request flow
```
client -> before_request (login check) -> blueprint route
       -> mask_service -> OCR + draw boxes -> output/masked_<jobId>.jpg
       -> access_service (register job, vault) -> JSON response
```

## Edge cases
- Production mode refuses to start with unsafe settings (see spec 02).
- `main.py` falls back to the next free port (up to +50) when `PORT` is busy.

## Acceptance criteria
- `python main.py` starts the app and `/health` returns `{"status": "UP"}`.
- Unauthenticated requests to protected routes get 401 (API) or a redirect to `/login` (browser).
