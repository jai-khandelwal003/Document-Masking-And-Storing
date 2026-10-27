# 12 – Docker & Deployment

## Goal
Run the service reproducibly locally and in production behind TLS.

## Image (`Dockerfile`)
- `python:3.12-slim-bookworm` + `libgl1`, `libglib2.0-0`, `libzbar0`, `tesseract-ocr`.
- Copies `app`, `main.py`, `resources` (Tesseract traineddata), `requirements.txt`.
- Runs `gunicorn -w 5 -t 5 -b 0.0.0.0:3000 main:app --timeout 120`.

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
- `.github/workflows/ci.yml`: Python 3.12, installs requirements, runs `python -m unittest discover -s tests` on push/PR.

## Edge cases
- Tesseract path on Windows defaults to `C:\Program Files\Tesseract-OCR\tesseract.exe`; in Docker it's on `PATH`.
- With 5 workers, the in-memory rate limiter and login limiter are per worker.
- The CI installs the full requirements; heavy packages (e.g. qreader/torch) slow the build.

## Acceptance criteria
- `docker compose up --build` serves `/health` on port 3000.
- Production stack refuses to boot with demo OTP/secrets (spec 02).
