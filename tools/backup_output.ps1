param(
  [string]$OutputDir = "output",
  [string]$BackupDir = "backup"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OutputDir)) {
  throw "Output directory '$OutputDir' not found."
}

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$archiveName = "output_backup_$timestamp.bak.zip"
$archivePath = Join-Path $BackupDir $archiveName

$itemsToBackup = @()
$itemsToBackup += (Join-Path $OutputDir "*")

if (-not (Get-ChildItem -Path $OutputDir -Force -ErrorAction SilentlyContinue)) {
  throw "Output directory '$OutputDir' is empty; nothing to back up."
}

Compress-Archive -Path $itemsToBackup -DestinationPath $archivePath -CompressionLevel Optimal
Write-Output "Backup created: $archivePath"
