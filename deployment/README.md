# Production Deployment (Docker + Nginx)

## 1) Generate production env file

Run this once and then fill SMTP values if missing:

```powershell
./tools/generate_production_env.ps1 -OutputPath .env.prod -OtpEmailUsername "your-real-email@example.com" -OtpEmailPassword "your-app-password" -OtpEmailFrom "your-real-email@example.com"
```

## 2) Set your deployment domain in Nginx config

Generate `deployment/nginx/default.conf` from the hardened template:

```powershell
./tools/set_nginx_domain.ps1 -Domain "api.example.com" -IncludeWww
```

## 3) Add TLS certificate files

Place certificate files in `deployment/certs/`:

- `deployment/certs/fullchain.pem`
- `deployment/certs/privkey.pem`

## 4) Build and start stack

```powershell
docker compose -f docker-compose.production.yml up -d --build
```

This starts:

- `doc-masking-app` (internal only)
- `doc-masking-nginx` (public 80/443)

## 5) Verify health

```powershell
curl https://<your-domain>/health
curl -H "X-Health-Token: <HEALTH_DETAILS_TOKEN>" https://<your-domain>/health/details
```

## 6) Backup output data

```powershell
./tools/backup_output.ps1
```

The archive is created under `backup/`.

## 7) Update / rollback

```powershell
docker compose -f docker-compose.production.yml pull
docker compose -f docker-compose.production.yml up -d --build
```
