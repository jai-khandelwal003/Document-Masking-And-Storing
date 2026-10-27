# 10 – Storage & Retention Cleanup

## Goal
Sensitive files must not live forever. A cleanup job deletes old data by age.

## Behavior (`app/services/storage_cleanup.py`)
Runs at startup when `STORAGE_CLEANUP_ENABLED=true` and `STORAGE_CLEANUP_AT_STARTUP=true` (skipped in tests). Files with an mtime older than `STORAGE_RETENTION_DAYS` (min 1, default 30) are removed from:
1. `ORIGINAL_UPLOADS_DIR` (saved originals)
2. `output/identity_docs/` (vault uploads)
3. `output/masked_*` (generated masked images only)

Then empty sub-directories are pruned. SQLite databases and `audit.log` are never touched. The summary (`deletedFiles`, `deletedDirs`, `retentionDays`) is logged.

## Related settings
- `PERSIST_ORIGINAL_UPLOADS` (default false): when false, the uploaded original is deleted right after processing.
- `tools/backup_output.ps1` creates a zip of `output/` under `backup/` (do not commit it).

## Edge cases
- Cleanup is disabled by default (`STORAGE_CLEANUP_ENABLED=false`).
- A file removed from disk may still be referenced by a vault record; downloads then fail with "Document file not found".
- Cleanup only runs at startup; long-running instances need a restart or an external scheduler.

## Acceptance criteria
- With retention 1 day, a 2-day-old `masked_*.jpg` is deleted and `access_state.sqlite3` is kept.
- `/health/details` reports file counts and bytes for each storage directory.
