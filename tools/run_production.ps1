param(
  [int]$Port = 3000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  throw "Virtual environment Python not found at $python. Run setup first."
}

# Enforce production-safe runtime switches.
$env:APP_ENV = "production"
$env:PRODUCTION = "true"
$env:ACCESS_SHOW_CODE = "false"
$env:IDENTITY_SHOW_OTP = "false"
$env:IDENTITY_OTP_PROVIDER = "email"
$env:PORT = "$Port"

# Required production secrets/tokens.
$required = @("SECRET_KEY", "HASH_SECRET", "API_KEY", "HEALTH_DETAILS_TOKEN")
$missing = @()
foreach ($name in $required) {
  if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
    $missing += $name
  }
}

if ($missing.Count -gt 0) {
  $list = $missing -join ", "
  throw "Missing required production env vars: $list. Set them in your shell or deployment environment before running this script."
}

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable("API_KEY_REQUIRED"))) {
  $env:API_KEY_REQUIRED = "true"
}

$otpProvider = [Environment]::GetEnvironmentVariable("IDENTITY_OTP_PROVIDER")
if ([string]::IsNullOrWhiteSpace($otpProvider)) {
  $otpProvider = "email"
}

if ($otpProvider.Trim().ToLower() -eq "email") {
  $otpRequired = @("OTP_EMAIL_SMTP_HOST", "OTP_EMAIL_USERNAME", "OTP_EMAIL_PASSWORD", "OTP_EMAIL_FROM")
  $otpMissing = @()
  foreach ($name in $otpRequired) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
      $otpMissing += $name
    }
  }

  if ($otpMissing.Count -gt 0) {
    $list = $otpMissing -join ", "
    throw "Missing required OTP email env vars for production: $list."
  }

  $placeholderValues = @("your-email@gmail.com", "your-app-password", "change-me", "example@example.com")
  $otpValues = @(
    [Environment]::GetEnvironmentVariable("OTP_EMAIL_USERNAME"),
    [Environment]::GetEnvironmentVariable("OTP_EMAIL_PASSWORD"),
    [Environment]::GetEnvironmentVariable("OTP_EMAIL_FROM")
  )
  foreach ($v in $otpValues) {
    $normalized = ""
    if (-not [string]::IsNullOrWhiteSpace($v)) {
      $normalized = $v.Trim().ToLower()
    }
    if ($placeholderValues -contains $normalized) {
      throw "OTP email credentials contain placeholder values. Set real provider credentials before production start."
    }
  }
}

Set-Location $root
& $python "main.py"
