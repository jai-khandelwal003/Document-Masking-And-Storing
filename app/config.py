import os


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name, default=""):
    value = os.environ.get(name)
    if value is None:
        return str(default)
    return str(value).strip()


def _is_production_env() -> bool:
    app_env = _env_text("APP_ENV", _env_text("FLASK_ENV", "development")).lower()
    return app_env in {"prod", "production"} or _env_bool("PRODUCTION", False)

def _default_auth_provider() -> str:
    explicit = _env_text('AUTH_PROVIDER', '').lower()
    if explicit in {'local', 'clerk'}:
        return explicit
    if _env_text('CLERK_PUBLISHABLE_KEY') and _env_text('CLERK_SECRET_KEY'):
        return 'clerk'
    return 'local'


class Config:
    APP_ENV = _env_text('APP_ENV', _env_text('FLASK_ENV', 'development')).lower()
    PRODUCTION = _is_production_env()
    SECRET_KEY = _env_text('SECRET_KEY', '')
    HASH_ALGORITHM = os.environ.get('HASH_ALGORITHM', 'sha256')
    HASH_SECRET = _env_text('HASH_SECRET', '')
    BRAND_PROJECT_TITLE = os.environ.get('BRAND_PROJECT_TITLE', 'Smart Document Masking')
    BRAND_COLLEGE_NAME = os.environ.get('BRAND_COLLEGE_NAME', 'Your College Name')
    BRAND_DEPARTMENT = os.environ.get('BRAND_DEPARTMENT', 'Department of Computer Science')
    BRAND_GUIDE_NAME = os.environ.get('BRAND_GUIDE_NAME', 'Project Guide')
    BRAND_STUDENT_NAME = os.environ.get('BRAND_STUDENT_NAME', 'Student Name')
    BRAND_REG_NO = os.environ.get('BRAND_REG_NO', 'N/A')
    BRAND_YEAR = os.environ.get('BRAND_YEAR', 'Final Year')
    BRAND_LOGO_URL = os.environ.get('BRAND_LOGO_URL', '')
    RETURN_RAW_AADHAAR = _env_bool('RETURN_RAW_AADHAAR', False)
    API_KEY_REQUIRED = _env_bool('API_KEY_REQUIRED', False)
    API_KEY = os.environ.get('API_KEY', '')
    APP_API_KEY = _env_text('APP_API_KEY', os.environ.get('API_KEY', ''))
    USER_ID = _env_text('USER_ID', 'admin')
    USER_PASSWORD = _env_text('USER_PASSWORD', 'admin123')
    SHOW_LOGIN_CREDENTIAL_HINTS = _env_bool('SHOW_LOGIN_CREDENTIAL_HINTS', False)
    AUTH_PROVIDER = _default_auth_provider()
    CLERK_PUBLISHABLE_KEY = _env_text('CLERK_PUBLISHABLE_KEY')
    CLERK_SECRET_KEY = _env_text('CLERK_SECRET_KEY')
    CLERK_JWKS_URL = _env_text('CLERK_JWKS_URL')
    CLERK_AUTHORIZED_PARTIES = _env_text('CLERK_AUTHORIZED_PARTIES')
    CLERK_ALLOWED_EMAILS = _env_text('CLERK_ALLOWED_EMAILS')
    CLERK_ALLOWED_DOMAINS = _env_text('CLERK_ALLOWED_DOMAINS')
    CLERK_ALLOW_ANY_USER = _env_bool('CLERK_ALLOW_ANY_USER', False)
    TRUST_PROXY_HEADERS = _env_bool('TRUST_PROXY_HEADERS', False)
    RATE_LIMIT_ENABLED = _env_bool('RATE_LIMIT_ENABLED', True)
    RATE_LIMIT_REQUESTS = int(os.environ.get('RATE_LIMIT_REQUESTS', 20))
    RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', 60))
    STRICT_QREADER_IMPORT = _env_bool('STRICT_QREADER_IMPORT', False)
    ACCESS_CODE_TTL_SECONDS = int(os.environ.get('ACCESS_CODE_TTL_SECONDS', 300))
    ACCESS_TOKEN_TTL_SECONDS = int(os.environ.get('ACCESS_TOKEN_TTL_SECONDS', 300))
    ACCESS_MAX_ATTEMPTS = int(os.environ.get('ACCESS_MAX_ATTEMPTS', 5))
    ACCESS_SHOW_CODE = _env_bool('ACCESS_SHOW_CODE', True)
    ACCESS_STATE_PERSIST = _env_bool('ACCESS_STATE_PERSIST', True)
    ACCESS_STATE_DB_PATH = os.environ.get('ACCESS_STATE_DB_PATH', '')
    ACCESS_FALLBACK_SECRET = os.environ.get('ACCESS_FALLBACK_SECRET', '')
    IDENTITY_REQUIRE_OTP = _env_bool('IDENTITY_REQUIRE_OTP', True)
    IDENTITY_OTP_TTL_SECONDS = int(os.environ.get('IDENTITY_OTP_TTL_SECONDS', 180))
    IDENTITY_OTP_MAX_ATTEMPTS = int(os.environ.get('IDENTITY_OTP_MAX_ATTEMPTS', 5))
    IDENTITY_OTP_COOLDOWN_SECONDS = int(os.environ.get('IDENTITY_OTP_COOLDOWN_SECONDS', 30))
    IDENTITY_SHOW_OTP = _env_bool('IDENTITY_SHOW_OTP', False)
    IDENTITY_OTP_PROVIDER = os.environ.get('IDENTITY_OTP_PROVIDER', 'demo')
    OTP_EMAIL_SMTP_HOST = os.environ.get('OTP_EMAIL_SMTP_HOST', '')
    OTP_EMAIL_SMTP_PORT = int(os.environ.get('OTP_EMAIL_SMTP_PORT', 587))
    OTP_EMAIL_USE_TLS = _env_bool('OTP_EMAIL_USE_TLS', True)
    OTP_EMAIL_USERNAME = os.environ.get('OTP_EMAIL_USERNAME', '')
    OTP_EMAIL_PASSWORD = os.environ.get('OTP_EMAIL_PASSWORD', '')
    OTP_EMAIL_FROM = os.environ.get('OTP_EMAIL_FROM', '')
    OTP_EMAIL_TO = os.environ.get('OTP_EMAIL_TO', '')
    OTP_EMAIL_SUBJECT_PREFIX = os.environ.get('OTP_EMAIL_SUBJECT_PREFIX', 'Smart Masking')
    HEALTH_DETAILS_TOKEN = _env_text('HEALTH_DETAILS_TOKEN', '')
    IDENTITY_DB_PATH = _env_text('IDENTITY_DB_PATH', os.path.join('output', 'identity_profiles.sqlite3'))
    AUDIT_LOG_PATH = _env_text('AUDIT_LOG_PATH', os.path.join('output', 'audit.log'))
    IDENTITY_DOC_MAX_BYTES = int(os.environ.get('IDENTITY_DOC_MAX_BYTES', 5 * 1024 * 1024))
    UPLOAD_FOLDER = './.images'
    PERSIST_ORIGINAL_UPLOADS = _env_bool('PERSIST_ORIGINAL_UPLOADS', False)
    ORIGINAL_UPLOADS_DIR = _env_text('ORIGINAL_UPLOADS_DIR', os.path.join('output', 'uploads'))
    STORAGE_CLEANUP_ENABLED = _env_bool('STORAGE_CLEANUP_ENABLED', False)
    STORAGE_RETENTION_DAYS = max(1, int(os.environ.get('STORAGE_RETENTION_DAYS', 30)))
    STORAGE_CLEANUP_AT_STARTUP = _env_bool('STORAGE_CLEANUP_AT_STARTUP', True)
    TESSERACT_CMD = _env_text('TESSERACT_CMD', r'C:\Program Files\Tesseract-OCR\tesseract.exe')
    PDF_RENDER_DPI = max(120, min(300, int(os.environ.get('PDF_RENDER_DPI', 180))))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # Max file size is 10 MB
