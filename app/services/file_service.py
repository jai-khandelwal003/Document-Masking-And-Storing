import os
import uuid

from werkzeug.utils import secure_filename
from flask import has_app_context, current_app

from app.config import Config


def _resolve_upload_folder():
    if has_app_context():
        persist = bool(current_app.config.get("PERSIST_ORIGINAL_UPLOADS", False))
        original_dir = str(current_app.config.get("ORIGINAL_UPLOADS_DIR", "") or "").strip()
        default_upload_folder = str(current_app.config.get("UPLOAD_FOLDER", Config.UPLOAD_FOLDER) or Config.UPLOAD_FOLDER)
    else:
        persist = bool(getattr(Config, "PERSIST_ORIGINAL_UPLOADS", False))
        original_dir = str(getattr(Config, "ORIGINAL_UPLOADS_DIR", "") or "").strip()
        default_upload_folder = str(getattr(Config, "UPLOAD_FOLDER", "./.images") or "./.images")

    if persist and original_dir:
        return original_dir
    return default_upload_folder

def handle_file_upload(file):
    # Secure the filename
    filename = secure_filename(file.filename)

    # Create uploads folder if it doesn't exist
    upload_folder = _resolve_upload_folder()
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    # create a random uuid and append it to the filename
    filename = str(uuid.uuid4()) + filename
    # Save the file
    file_path = os.path.join(upload_folder, filename)
    file.save(file_path)

    # Return the file URL (relative path or URL can be adjusted depending on your setup)
    return file_path
