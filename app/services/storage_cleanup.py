import os
import time


def _iter_old_files(root_dir, cutoff_epoch):
    if not root_dir or not os.path.isdir(root_dir):
        return

    for current_root, _, files in os.walk(root_dir):
        for name in files:
            full_path = os.path.join(current_root, name)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            if mtime <= cutoff_epoch:
                yield full_path


def _remove_file(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _prune_empty_dirs(root_dir):
    if not root_dir or not os.path.isdir(root_dir):
        return 0

    removed = 0
    for current_root, dirs, _ in os.walk(root_dir, topdown=False):
        for dirname in dirs:
            candidate = os.path.join(current_root, dirname)
            try:
                if not os.listdir(candidate):
                    os.rmdir(candidate)
                    removed += 1
            except OSError:
                continue
    return removed


def cleanup_storage(app):
    if not bool(app.config.get("STORAGE_CLEANUP_ENABLED", False)):
        return {"enabled": False, "deletedFiles": 0, "deletedDirs": 0, "retentionDays": 0}

    retention_days = max(1, int(app.config.get("STORAGE_RETENTION_DAYS", 30)))
    cutoff_epoch = time.time() - (retention_days * 24 * 60 * 60)

    output_root = os.path.abspath(os.path.join(app.root_path, "..", "output"))
    uploads_root = os.path.abspath(str(app.config.get("ORIGINAL_UPLOADS_DIR", os.path.join("output", "uploads"))))
    identity_root = os.path.abspath(os.path.join(output_root, "identity_docs"))

    deleted_files = 0
    deleted_dirs = 0

    # Prune old original uploads.
    for file_path in _iter_old_files(uploads_root, cutoff_epoch):
        if _remove_file(file_path):
            deleted_files += 1

    # Prune old identity vault documents.
    for file_path in _iter_old_files(identity_root, cutoff_epoch):
        if _remove_file(file_path):
            deleted_files += 1

    # Prune old generated masked images only (keep DB/state files intact).
    if os.path.isdir(output_root):
        for name in os.listdir(output_root):
            if not name.startswith("masked_"):
                continue
            full_path = os.path.join(output_root, name)
            if not os.path.isfile(full_path):
                continue
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            if mtime <= cutoff_epoch and _remove_file(full_path):
                deleted_files += 1

    deleted_dirs += _prune_empty_dirs(identity_root)
    if os.path.abspath(uploads_root) != os.path.abspath(identity_root):
        deleted_dirs += _prune_empty_dirs(uploads_root)

    return {
        "enabled": True,
        "deletedFiles": deleted_files,
        "deletedDirs": deleted_dirs,
        "retentionDays": retention_days,
    }
