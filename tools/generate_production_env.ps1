param(
  [string]$OutputPath = ".env.prod",
  [string]$SmtpHost = "smtp.gmail.com",
  [int]$SmtpPort = 587,
  [string]$SmtpUseTls = "true",
  [string]$OtpEmailUsername = "",
  [string]$OtpEmailPassword = "",
  [string]$OtpEmailFrom = "",
  [string]$OtpEmailTo = ""
)

$ErrorActionPreference = "Stop"

function New-Secret([int]$bytes = 48) {
  $buffer = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
  return ([Convert]::ToBase64String($buffer)).TrimEnd('=') -replace '\+', '-' -replace '/', '_'
}

$secretKey = New-Secret 48
$hashSecret = New-Secret 48
$apiKey = New-Secret 32
$healthToken = New-Secret 32

$content = @"
APP_ENV=production
PRODUCTION=true
PORT=3000
DEBUG=false

SECRET_KEY=$secretKey
HASH_SECRET=$hashSecret
HASH_ALGORITHM=sha256

API_KEY_REQUIRED=true
API_KEY=$apiKey
APP_API_KEY=$apiKey
HEALTH_DETAILS_TOKEN=$healthToken
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=20
RATE_LIMIT_WINDOW_SECONDS=60
RETURN_RAW_AADHAAR=false

ACCESS_SHOW_CODE=false
ACCESS_CODE_TTL_SECONDS=300
ACCESS_TOKEN_TTL_SECONDS=300
ACCESS_MAX_ATTEMPTS=5
ACCESS_FALLBACK_SECRET=

IDENTITY_REQUIRE_OTP=true
IDENTITY_OTP_TTL_SECONDS=180
IDENTITY_OTP_MAX_ATTEMPTS=5
IDENTITY_OTP_COOLDOWN_SECONDS=30
IDENTITY_SHOW_OTP=false
IDENTITY_OTP_PROVIDER=email
IDENTITY_DOC_MAX_BYTES=5242880

OTP_EMAIL_SMTP_HOST=$SmtpHost
OTP_EMAIL_SMTP_PORT=$SmtpPort
OTP_EMAIL_USE_TLS=$SmtpUseTls
OTP_EMAIL_USERNAME=$OtpEmailUsername
OTP_EMAIL_PASSWORD=$OtpEmailPassword
OTP_EMAIL_FROM=$OtpEmailFrom
OTP_EMAIL_TO=$OtpEmailTo
OTP_EMAIL_SUBJECT_PREFIX=Smart Masking

TESSERACT_CMD=/usr/bin/tesseract
STRICT_QREADER_IMPORT=false
STORAGE_CLEANUP_ENABLED=true
STORAGE_RETENTION_DAYS=30
STORAGE_CLEANUP_AT_STARTUP=true
"@

Set-Content -Path $OutputPath -Value $content -Encoding utf8
Write-Output "Generated $OutputPath with strong secrets."

if ([string]::IsNullOrWhiteSpace($OtpEmailUsername) -or [string]::IsNullOrWhiteSpace($OtpEmailPassword) -or [string]::IsNullOrWhiteSpace($OtpEmailFrom)) {
  Write-Warning "OTP email credentials are incomplete. Set OTP_EMAIL_USERNAME, OTP_EMAIL_PASSWORD, and OTP_EMAIL_FROM before production start."
}
