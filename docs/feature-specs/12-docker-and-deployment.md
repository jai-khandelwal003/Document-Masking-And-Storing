# 12 – Docker & Deployment

## Goal
Run the service reproducibly locally and in production behind TLS.

## Image (`Dockerfile`)
- `python:3.12-slim-bookworm` + `libgl1`, `libglib2.0-0`, `libzbar0`, `tesseract-ocr`.
- Copies `app`, `main.py`, `resources` (Tesseract traineddata), `requirements.txt`.
- Runs `gunicorn -w 1 --threads 8 -b 0.0.0.0:3000 main:app --timeout 120`. One worker is required because access codes, OTPs and the vault live in process memory.

## Local (`docker-compose.yml`)
Builds the image, reads `.env`, publishes `3000:3000`, mounts `./output` to `/app/output`.

## Production (`docker-compose.production.yml`, see `deployment/README.md`)
1. `tools/generate_production_env.ps1` → `.env.prod` (secrets, SMTP).
2. `tools/set_nginx_domain.ps1` → renders `deployment/nginx/default.conf` from `default.conf.template`.
3. Put `fullchain.pem` and `privkey.pem` in `deployment/certs/` (**never commit these**).
4. `docker compose -f docker-compose.production.yml up -d --build`.
   - `app` is internal-only; `nginx:1.27-alpine` exposes 80/443.
   - Output lives in the named volume `doc_masking_output`.
5. Verify with `/health` and `/health/details` (token header).
6. Back up with `tools/backup_output.ps1`.

## Other tooling
- `Makefile`: `install`, `run`, `test`, `lint`, `clean`, `docker`.
- `.github/workflows/ci.yml` (push and pull request): job **Secret scan** (`tools/scan_secrets.py --all`) and job **Unit tests** on ubuntu with `tesseract-ocr`, `libmagic1`, `libgl1`, `libglib2.0-0`, `libzbar0` installed, pip cache, and `requirements.txt` minus the optional QR/ML stack (torch, torchvision, ultralytics, qreader, qrdet, quadrilateral-fitter), then `python -m unittest discover -s tests`. Read-only token, 20 min timeout, superseded runs cancelled.

## Edge cases
- Tesseract path on Windows defaults to `C:\Program Files\Tesseract-OCR\tesseract.exe`; in Docker it's on `PATH`.
- Do not raise the worker count without moving the in-memory access/OTP/vault state into the database.
- `docker-compose.production.yml` sets `TRUST_PROXY_HEADERS=true` because nginx sets `X-Forwarded-For`.
- CI skips the optional QR/ML packages; the Docker image installs everything in `requirements.txt`, so QR masking works there.

## Acceptance criteria
- `docker compose up --build` serves `/health` on port 3000.
- Production stack refuses to boot with demo OTP/secrets (spec 02).
