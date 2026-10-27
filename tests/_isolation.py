"""Point every writable path at a throwaway folder before the app is imported.

Import this first in each test module. Without it the tests would read and wipe the real
output/ folder (identity documents, access state, audit log) of whoever runs them.
"""
import atexit
import os
import shutil
import tempfile

if not os.environ.get("SDM_TEST_ISOLATED"):
    _root = tempfile.mkdtemp(prefix="sdm-tests-")
    os.environ.update(
        {
            "SDM_TEST_ISOLATED": "1",
            "IDENTITY_DOCS_DIR": os.path.join(_root, "identity_docs"),
            "ACCESS_STATE_DB_PATH": os.path.join(_root, "access_state.sqlite3"),
            "IDENTITY_DB_PATH": os.path.join(_root, "identity_profiles.sqlite3"),
            "AUDIT_LOG_PATH": os.path.join(_root, "audit.log"),
            "ORIGINAL_UPLOADS_DIR": os.path.join(_root, "uploads"),
            "UPLOAD_FOLDER": os.path.join(_root, "uploads_tmp"),
        }
    )
    atexit.register(shutil.rmtree, _root, ignore_errors=True)
