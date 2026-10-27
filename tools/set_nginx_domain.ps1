param(
  [Parameter(Mandatory=$true)]
  [string]$Domain,
  [switch]$IncludeWww
)

$ErrorActionPreference = "Stop"

$domainClean = $Domain.Trim().ToLower()
if ([string]::IsNullOrWhiteSpace($domainClean) -or $domainClean -notmatch '^[a-z0-9][a-z0-9.-]*[a-z0-9]$') {
  throw "Provide a valid domain, e.g. api.example.com"
}

$templatePath = Join-Path $PSScriptRoot "..\deployment\nginx\default.conf.template"
$outputPath = Join-Path $PSScriptRoot "..\deployment\nginx\default.conf"

if (-not (Test-Path $templatePath)) {
  throw "Template not found: $templatePath"
}

$template = Get-Content $templatePath -Raw
$wwwDomain = if ($IncludeWww) { "www.$domainClean" } else { $domainClean }

$config = $template.Replace("__DOMAIN__", $domainClean).Replace("__WWW_DOMAIN__", $wwwDomain)
Set-Content -Path $outputPath -Value $config -Encoding utf8

Write-Output "Nginx domain config generated at deployment/nginx/default.conf"
Write-Output "Domain: $domainClean"
if ($IncludeWww) {
  Write-Output "WWW alias enabled: www.$domainClean"
}
Write-Output "Next: place TLS certs in deployment/certs and run docker compose -f docker-compose.production.yml up -d --build"
