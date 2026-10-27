# Technical Document: Smart Document Masking Service

**Project Title:** Smart Aadhaar Document Masking Service with OCR-Based Detection  
**Version:** 1.0  
**Last Updated:** May 2026

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Technology Stack](#technology-stack)
4. [Core Features](#core-features)
5. [API Reference](#api-reference)
6. [Configuration Guide](#configuration-guide)
7. [Deployment](#deployment)
8. [Security Architecture](#security-architecture)
9. [Development Guide](#development-guide)
10. [Troubleshooting](#troubleshooting)

---

## Executive Summary

The **Smart Document Masking Service** is a Flask-based web application designed to securely detect, mask, and manage sensitive personal identity documents (particularly Aadhaar cards). The system employs OCR-based detection to identify sensitive regions within documents and applies intelligent masking to protect personally identifiable information (PII).

### Key Objectives
- Automated detection and masking of sensitive identity document information
- Secure identity verification with OTP-based authentication
- Access control with token-based authorization
- Persistent audit logging and state management
- Production-ready deployment with Docker and Nginx

---

## System Architecture

### High-Level Architecture Diagram

```
┌──────────────────────────────────────────────────────────┐
│                    Client Layer (Web UI)                 │
│         (HTML/CSS/JavaScript with Service Workers)       │
└────────────────┬─────────────────────────────────────────┘
                 │ HTTP/HTTPS
┌────────────────▼─────────────────────────────────────────┐
│              Flask Web Application                        │
│  ┌──────────────┬──────────────┬──────────────┐          │
│  │ Access       │ Auth         │ Mask         │          │
│  │ Control      │ Management   │ Service      │          │
│  │ Routes       │ Routes       │ Routes       │          │
│  └──────────────┴──────────────┴──────────────┘          │
│  ┌──────────────────────────────────────────────┐        │
│  │         Core Service Layer                    │        │
│  ├──────────────┬──────────────┬────────────────┤        │
│  │ Mask Service │ File Service │ OTP Delivery   │        │
│  ├──────────────┼──────────────┼────────────────┤        │
│  │ Access Svc.  │ Storage      │ OCR Processing │        │
│  │              │ Cleanup      │ (Tesseract)    │        │
│  └──────────────┴──────────────┴────────────────┘        │
└────────────────┬─────────────────────────────────────────┘
                 │
     ┌───────────┼───────────┐
     │           │           │
┌────▼──────┐ ┌──▼────────┐ ┌─▼──────────────┐
│ SQLite    │ │ File      │ │ External       │
│ Databases │ │ Storage   │ │ SMTP (Email)   │
│           │ │ (uploads) │ │                │
└───────────┘ └──────────┘ └────────────────┘
```

### Module Structure

```
app/
├── routes/              # HTTP endpoints
│   ├── access.py       # Access control & authorization
│   ├── auth.py         # User authentication
│   ├── health.py       # Health check endpoints
│   └── mask.py         # Document upload & masking
├── services/           # Business logic
│   ├── access_service.py       # Access token management
│   ├── file_service.py         # File I/O operations
│   ├── mask_service.py         # Masking orchestration
│   ├── otp_delivery_service.py # OTP generation & delivery
│   ├── storage_cleanup.py      # Retention management
│   └── mask_utils/             # Specialized masking
│       ├── aadhaar.py          # Aadhaar-specific logic
│       ├── aadhar_helpers.py   # Helper utilities
│       ├── document_generic.py # Generic document support
│       └── qreader.py          # QR code detection
├── models/             # Data persistence
│   ├── audit_store.py  # Audit log management
│   └── identity_store.py # Identity profile storage
├── utils/              # Utility functions
│   ├── file_utils.py
│   ├── hash_utils.py
│   ├── image_utils.py
│   ├── mime_utils.py
│   └── validate_addhar.py
├── static/             # Web assets
│   ├── manifest.json
│   ├── sw.js          # Service Worker
│   └── samples/
└── templates/          # HTML templates
    ├── dashboard.html
    ├── identity_documents.html
    ├── login.html
```

---

## Technology Stack

### Backend
- **Framework:** Flask 3.1.0
- **Authentication:** Flask-Login 0.6.3
- **Rate Limiting:** Flask-Limiter 3.8.0
- **API Documentation:** Flasgger 0.9.7.1
- **WSGI Server:** Gunicorn 23.0.0

### Data Processing & OCR
- **OCR Engine:** Tesseract (via pytesseract 0.3.13)
- **QR Detection:** QReader 3.14
- **Image Processing:** OpenCV 4.10.0, Pillow 11.0.0
- **PDF Handling:** PyMuPDF 1.24.14
- **Barcode Reading:** pyzbar 0.1.9

### Machine Learning & Analytics
- **ML Framework:** PyTorch 2.5.1, TorchVision 0.20.1
- **Numerical Computing:** NumPy 1.26.4, SciPy 1.14.1
- **Data Analysis:** Pandas 2.2.3
- **Visualization:** Matplotlib 3.9.3, Seaborn 0.13.2

### Data Storage
- **Primary Database:** SQLite 3 (file-based)
- **Data Serialization:** PyYAML 6.0.2

### Deployment & Infrastructure
- **Containerization:** Docker & Docker Compose
- **Reverse Proxy:** Nginx
- **Process Manager:** Gunicorn 23.0.0

### Development & Utilities
- **Configuration:** python-dotenv 1.0.1
- **File Type Detection:** python-magic 0.4.27
- **HTTP Client:** requests 2.32.3
- **CPU Info:** py-cpuinfo 9.0.0
- **System Monitoring:** psutil 6.1.0

---

## Core Features

### 1. Document Upload & OCR-Based Masking
- **Supported Formats:** PNG, JPG, JPEG, PDF
- **OCR Engine:** Tesseract for character recognition
- **Smart Detection:** Automatic region identification for sensitive data
- **Coordinate Scaling:** Adjusts OCR coordinates for resized images

**Key APIs:**
- `POST /mask/aadhaar` - Mask Aadhaar documents
- `POST /mask/document` - Mask generic identity documents

**Masking Options:**
- `first8_mask`: Mask first 8 digits of Aadhaar
- `last4_mask`: Mask last 4 digits of Aadhaar
- `mask_qr`: Mask QR code region

### 2. Identity Management with OTP Verification
- **Provider Support:** Demo OTP, Email-based OTP
- **TTL Configuration:** Configurable OTP expiration (default: 180 seconds)
- **Retry Limits:** Maximum OTP attempts with cooldown
- **PIN Protection:** Optional PIN-based identity profile unlock

**Endpoints:**
- `POST /identity/request-otp` - Generate and deliver OTP
- `POST /identity/verify-otp` - Verify OTP token
- `GET /identity/profiles` - Retrieve identity documents

### 3. Access Control & Authorization
- **Token-Based System:** Issued access codes with TTL
- **Rate Limiting:** Per-IP request throttling
- **API Key Authentication:** Optional API key requirement
- **Persistent State:** SQLite-backed session management

**Endpoints:**
- `POST /access/request-code` - Generate access code
- `POST /access/verify-code` - Exchange code for token
- `POST /access/verify-token` - Validate bearer token

### 4. Audit Logging
- **Event Tracking:** All document operations logged
- **User Attribution:** Session-based user identification
- **Timestamp Recording:** Precise operation timestamps
- **Persistent Storage:** SQLite audit log database

**Log Categories:**
- Document uploads and masking operations
- Authentication events (OTP, token verification)
- Access control decisions
- System health events

### 5. Health & Diagnostics
- **Public Health Check:** `GET /health` (minimal information)
- **Detailed Diagnostics:** `GET /health/details` (protected)
- **System Information:** CPU, memory, environment diagnostics
- **Security Status:** Configuration compliance validation

---

## API Reference

### Authentication Endpoints

#### 1. User Login
```http
POST /auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin123
```

**Response (Success - 200):**
```json
{
  "message": "Login successful",
  "sessionId": "unique_session_id"
}
```

**Response (Failure - 401):**
```json
{
  "error": "Invalid credentials"
}
```

---

#### 2. Request Access Code
```http
POST /access/request-code
Content-Type: application/json

{
  "documentId": "aadhaar"
}
```

**Response (Success - 200):**
```json
{
  "code": "XXXXXX",
  "expiresInSeconds": 300,
  "message": "Access code generated"
}
```

---

#### 3. Verify Access Code
```http
POST /access/verify-code
Content-Type: application/json

{
  "code": "XXXXXX"
}
```

**Response (Success - 200):**
```json
{
  "accessToken": "token_string",
  "expiresInSeconds": 300,
  "tokenType": "Bearer"
}
```

---

### Masking Endpoints

#### 1. Upload & Mask Aadhaar
```http
POST /mask/aadhaar
Content-Type: multipart/form-data
Authorization: Bearer <accessToken>

file=<binary>
first8_mask=true
last4_mask=true
mask_qr=false
```

**Response (Success - 200):**
```json
{
  "status": "success",
  "maskedImagePath": "/output/masked_image_id.png",
  "imageId": "unique_image_id",
  "detectedRegions": {
    "aadhaarNumber": "Region detected",
    "qrCode": "Not masked"
  }
}
```

---

#### 2. Upload & Mask Generic Document
```http
POST /mask/document
Content-Type: multipart/form-data
Authorization: Bearer <accessToken>

file=<binary>
documentType=pan|dl|passport
```

**Response (Success - 200):**
```json
{
  "status": "success",
  "maskedImagePath": "/output/masked_document.png",
  "documentType": "pan"
}
```

---

### Identity Verification Endpoints

#### 1. Request OTP
```http
POST /identity/request-otp
Content-Type: application/json

{
  "email": "user@example.com"
}
```

**Response (Success - 200):**
```json
{
  "message": "OTP sent to email",
  "otpExpiresInSeconds": 180,
  "otp": "123456"  // Only in demo mode
}
```

---

#### 2. Verify OTP
```http
POST /identity/verify-otp
Content-Type: application/json

{
  "email": "user@example.com",
  "otp": "123456"
}
```

**Response (Success - 200):**
```json
{
  "verified": true,
  "identityToken": "token_string"
}
```

---

#### 3. Get Identity Documents
```http
GET /identity/profiles
Authorization: Bearer <identityToken>
```

**Response (Success - 200):**
```json
{
  "profiles": [
    {
      "profileId": "unique_id",
      "documentType": "aadhaar",
      "maskedImage": "/output/masked_123.png",
      "uploadedAt": "2026-05-04T10:30:00Z",
      "profileLinkedDocuments": 2,
      "profileAutoLoaded": true
    }
  ]
}
```

---

### Health Endpoints

#### 1. Public Health Check
```http
GET /health
```

**Response (Success - 200):**
```json
{
  "status": "ok",
  "timestamp": "2026-05-04T10:30:00Z"
}
```

---

#### 2. Detailed Health Diagnostics
```http
GET /health/details?token=HEALTH_DETAILS_TOKEN
```

**Response (Success - 200):**
```json
{
  "status": "ok",
  "environment": "production",
  "python_version": "3.12.0",
  "system": {
    "cpu_percent": 15.2,
    "memory_percent": 42.5,
    "disk_usage_percent": 67.3
  },
  "security": {
    "api_key_required": true,
    "rate_limiting_enabled": true,
    "production_mode": true
  },
  "dependencies": {
    "tesseract_installed": true,
    "database_accessible": true
  }
}
```

---

## Configuration Guide

### Environment Variables

#### Core Application
```bash
# Application
APP_ENV=production              # or "development"
PRODUCTION=false               # or "true"
SECRET_KEY=your_secret_key_here # MUST be set in production
PORT=3000                       # Default port
AUTO_PORT_FALLBACK=true        # Fallback to next available port

# Flask-specific
FLASK_ENV=production
FLASK_DEBUG=false
```

#### Security & Authentication
```bash
# HMAC & Hashing
HASH_SECRET=your_hash_secret_here    # MUST be set in production
HASH_ALGORITHM=sha256

# API Authentication
API_KEY_REQUIRED=false
API_KEY=your_api_key_here

# Default Credentials (development only)
USER_ID=admin
USER_PASSWORD=admin123
SHOW_LOGIN_CREDENTIAL_HINTS=false
```

#### Rate Limiting
```bash
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=20        # Max requests per window
RATE_LIMIT_WINDOW_SECONDS=60  # Time window in seconds
```

#### Access Control
```bash
ACCESS_CODE_TTL_SECONDS=300       # Access code expiration
ACCESS_TOKEN_TTL_SECONDS=300      # Bearer token expiration
ACCESS_MAX_ATTEMPTS=5             # Max verification attempts
ACCESS_SHOW_CODE=true             # Debug: show code in response
ACCESS_STATE_PERSIST=true         # Persist state to database
ACCESS_STATE_DB_PATH=output/access_state.sqlite3
ACCESS_FALLBACK_SECRET=fallback_secret_key
```

#### Identity & OTP
```bash
IDENTITY_REQUIRE_OTP=true
IDENTITY_OTP_TTL_SECONDS=180              # OTP expiration
IDENTITY_OTP_MAX_ATTEMPTS=5               # Max OTP attempts
IDENTITY_OTP_COOLDOWN_SECONDS=30          # Retry cooldown
IDENTITY_SHOW_OTP=false                   # Debug: show OTP in response
IDENTITY_OTP_PROVIDER=demo                # or "email"
IDENTITY_DB_PATH=output/identity_profiles.sqlite3

# SMTP Configuration (for email OTP)
OTP_EMAIL_SMTP_HOST=smtp.gmail.com
OTP_EMAIL_SMTP_PORT=587
OTP_EMAIL_USE_TLS=true
OTP_EMAIL_USERNAME=your_email@gmail.com
OTP_EMAIL_PASSWORD=your_app_password
OTP_EMAIL_FROM=noreply@masking-service.com
OTP_EMAIL_TO=admin@example.com
OTP_EMAIL_SUBJECT_PREFIX=Smart Masking
```

#### OCR & Processing
```bash
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
STRICT_QREADER_IMPORT=false     # true = fail startup if QR not available
PDF_RENDER_DPI=180              # 120-300, default 180
RETURN_RAW_AADHAAR=false        # Debug: return unmasked data
```

#### Storage & Retention
```bash
UPLOAD_FOLDER=./.images
PERSIST_ORIGINAL_UPLOADS=false  # Keep original uploads
ORIGINAL_UPLOADS_DIR=output/uploads
STORAGE_CLEANUP_ENABLED=false   # Enable retention cleanup
STORAGE_RETENTION_DAYS=30       # Days to retain files
STORAGE_CLEANUP_AT_STARTUP=true # Run cleanup on startup
IDENTITY_DOC_MAX_BYTES=5242880  # 5 MB max document size
```

#### Audit & Logging
```bash
AUDIT_LOG_PATH=output/audit.log
HEALTH_DETAILS_TOKEN=your_health_token  # Required for /health/details
```

#### Branding
```bash
BRAND_PROJECT_TITLE=Smart Document Masking
BRAND_COLLEGE_NAME=ABC Institute of Technology
BRAND_DEPARTMENT=Department of Computer Science
BRAND_GUIDE_NAME=Dr. Your Guide Name
BRAND_STUDENT_NAME=Your Name
BRAND_REG_NO=N/A
BRAND_YEAR=Final Year
BRAND_LOGO_URL=https://example.com/logo.png
```

### Production Safety Checklist

⚠️ **CRITICAL: The application fails startup in production mode if:**

1. ✅ `SECRET_KEY` is not set
2. ✅ `HASH_SECRET` is not set
3. ✅ `ACCESS_SHOW_CODE=true` (debug mode enabled)
4. ✅ `IDENTITY_SHOW_OTP=true` (debug mode enabled)
5. ✅ `IDENTITY_OTP_PROVIDER=demo` (demo mode enabled)

---

## Deployment

### Local Development Setup

```powershell
# Clone and navigate to project
git clone <repo> jg-doc-masking-service
cd jg-doc-masking-service

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Setup environment
Copy-Item .env.example .env
# Edit .env with your configuration

# Run application
python main.py
```

Application starts at `http://localhost:3000`

### Docker Deployment

#### Development Container
```bash
docker-compose up -d
```

#### Production Container
```bash
# Generate secure production environment
.\tools\generate_production_env.ps1

# Deploy with production configuration
docker-compose -f docker-compose.production.yml up -d
```

**Production Stack:**
- Flask application (Gunicorn WSGI)
- Nginx reverse proxy on port 80/443
- SQLite databases (persisted volumes)
- SMTP for OTP delivery

### Nginx Configuration

Located at `deployment/nginx/default.conf`:

```nginx
upstream flask_app {
    server app:8000;
}

server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://flask_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://flask_app;
        access_log off;
    }
}
```

### Database Initialization

The application automatically creates SQLite databases on first run:

- **`output/access_state.sqlite3`** - Access control state
- **`output/identity_profiles.sqlite3`** - Identity document profiles
- **`output/audit.log`** - Audit log (if enabled)

No manual database setup required.

---

## Security Architecture

### Authentication Layers

1. **Session-Based Login**
   - Username/password authentication via Flask-Login
   - Session cookies with HMAC validation

2. **Access Code System**
   - Short-lived codes (default: 5 minutes)
   - IP-based rate limiting
   - Per-user attempt tracking

3. **Bearer Token Authorization**
   - JWT-style tokens with TTL
   - Required for all document operations
   - Automatic expiration

4. **Identity Verification**
   - OTP-based email verification
   - Optional PIN protection for profiles
   - Audit logging of all access

### Rate Limiting Strategy

**Per-IP Limits:**
- Default: 20 requests per 60 seconds
- Applies to all authenticated and unauthenticated endpoints
- Automatic cleanup of stale entries

**Configurable:**
- `RATE_LIMIT_REQUESTS`: Number of allowed requests
- `RATE_LIMIT_WINDOW_SECONDS`: Time window for rate limit

### Data Protection

**Encryption:**
- Secret key used for session signing
- HMAC-SHA256 for data integrity
- Passwords not stored (demo credentials in dev only)

**File Security:**
- Original uploads can be deleted automatically
- Masked images served from `/output/` with access control
- Temporary upload folder cleaned per session

**Database Security:**
- SQLite files in secure output directory
- Access control enforced at application level
- No plain-text sensitive data storage

### Audit & Compliance

**Audit Trail:**
- All document uploads logged with timestamp, user ID, document type
- Access code generation and verification events
- OTP delivery and verification attempts
- Health check access logging

**Compliance Features:**
- Production environment validation
- Demo mode prevention in production
- Configurable retention policies
- Detailed diagnostics for compliance verification

---

## Development Guide

### Running Tests

**Unit Tests:**
```powershell
# Using unittest (no pytest required)
python -m unittest discover -s tests -p "test_*.py"

# With verbose output
python -m unittest discover -s tests -p "test_*.py" -v
```

**Test Coverage:**
- `test_access_control.py` - Access token and code generation
- `test_health.py` - Health endpoint validation
- `test_identity_vault_fullmask.py` - Identity management
- `test_mask_security.py` - Masking operation integrity
- `test_upload_persistence.py` - File upload persistence
- `test_upload.py` - Document upload functionality

### Key Development Notes

1. **Lazy OCR Imports**
   - Keep OCR imports lazy in `mask_service.py` for faster test execution
   - Heavyweight packages (Tesseract, QReader) are imported on-demand

2. **Coordinate Scaling**
   - Aadhaar OCR runs on resized images
   - Detected coordinates must be scaled back before drawing masks
   - See `mask_utils/aadhaar.py` for scaling logic

3. **MIME Type Detection**
   - Windows: `python-magic`/libmagic can hang during MIME sniffing
   - Solution: Use signature-based fallback with optional `MIME_USE_PYTHON_MAGIC=true` flag

4. **Port Fallback**
   - Default port 3000 can be overridden with `PORT` env var
   - Enable auto-fallback with `AUTO_PORT_FALLBACK=true`
   - Shows message when fallback occurs

### Code Structure Best Practices

**Routes (`app/routes/`):**
- Handle HTTP parsing and validation
- Delegate business logic to services
- Return JSON with appropriate HTTP status codes

**Services (`app/services/`):**
- Implement business logic
- Handle data transformation
- Manage external dependencies (Tesseract, SMTP)

**Models (`app/models/`):**
- Manage data persistence
- Abstract database operations
- Provide clean data access layer

**Utils (`app/utils/`):**
- Reusable helper functions
- No dependency on Flask context
- Testable in isolation

### Debugging Tips

**Enable Route Inspection:**
```powershell
$env:SHOW_ROUTES="true"
python main.py
```

**Check Health Details:**
```bash
curl http://localhost:3000/health/details?token=YOUR_HEALTH_TOKEN
```

**Force Port Override:**
```powershell
$env:PORT=3010
python main.py
```

---

## Troubleshooting

### Issue: Port Already in Use

**Symptoms:**
```
OSError: [Errno 48] Address already in use
```

**Solution:**
```powershell
# Option 1: Enable auto port fallback (default)
python main.py

# Option 2: Use specific port
$env:PORT=3010
python main.py

# Option 3: Kill process on current port (Windows)
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

### Issue: Tesseract Not Found

**Symptoms:**
```
TesseractNotFoundError: tesseract is not installed or it's not in your PATH
```

**Solution:**

Windows:
```powershell
# Install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
python main.py
```

Linux/Mac:
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# macOS (with Homebrew)
brew install tesseract
```

### Issue: MIME Sniffing Hangs on Windows

**Symptoms:**
- File upload endpoint hangs indefinitely
- No error messages

**Root Cause:**
- `python-magic` can stall during MIME type detection on Windows

**Solution:**
```powershell
# Method 1: Disable python-magic (default safe mode)
# Just run normally - uses signature-based detection

# Method 2: Opt-in to python-magic if needed
$env:MIME_USE_PYTHON_MAGIC="true"
python main.py
```

### Issue: OTP Email Not Sending (Gmail)

**Symptoms:**
```
SMTPAuthenticationError: (535, b'5.7.8 Username and password not accepted')
```

**Solutions:**

1. **Use Gmail App Password:**
   - Enable 2-Factor Authentication on Gmail
   - Generate App Password at https://myaccount.google.com/apppasswords
   - Use App Password (not regular password)

2. **Switch to Demo Mode (Development Only):**
   ```powershell
   $env:IDENTITY_OTP_PROVIDER="demo"
   $env:IDENTITY_SHOW_OTP="true"  # Development only!
   python main.py
   ```

3. **Update SMTP Settings:**
   ```powershell
   $env:OTP_EMAIL_SMTP_HOST="smtp.gmail.com"
   $env:OTP_EMAIL_SMTP_PORT="587"
   $env:OTP_EMAIL_USE_TLS="true"
   $env:OTP_EMAIL_USERNAME="your_email@gmail.com"
   $env:OTP_EMAIL_PASSWORD="your_app_password"
   python main.py
   ```

### Issue: Database Locked (SQLite)

**Symptoms:**
```
sqlite3.OperationalError: database is locked
```

**Solution:**
```powershell
# SQLite databases are file-locked; ensure only one process accesses them
# Stop all running instances
Get-Process -Name "python" | Stop-Process -Force

# Manually remove lock file if persistent
Remove-Item "output/*.sqlite3-journal" -Force -ErrorAction SilentlyContinue

# Restart application
python main.py
```

### Issue: Missing `importlib-metadata` on Windows

**Symptoms:**
```
ModuleNotFoundError: No module named 'importlib_metadata'
```

**Solution:**
```powershell
pip install importlib-metadata
pip install -r requirements.txt
```

### Issue: Debugpy Startup Stall

**Symptoms:**
- VS Code debugger hangs on launch
- Breakpoints not hitting

**Solution:**
```powershell
# Ensure importlib-metadata is installed
pip install importlib-metadata

# Verify .venv has all dependencies
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Restart VS Code debugger
```

---

## Support & Resources

### Project Structure
- **Main Entry:** [main.py](main.py)
- **Configuration:** [app/config.py](app/config.py)
- **Routes:** [app/routes/](app/routes/)
- **Services:** [app/services/](app/services/)
- **Tests:** [tests/](tests/)

### External Documentation
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- [Docker Compose Guide](https://docs.docker.com/compose/)
- [Nginx Configuration](https://nginx.org/en/docs/)

### Key Files for Reference
- **Health Checks:** [app/routes/health.py](app/routes/health.py)
- **Masking Logic:** [app/services/mask_service.py](app/services/mask_service.py)
- **Access Control:** [app/services/access_service.py](app/services/access_service.py)
- **OTP Delivery:** [app/services/otp_delivery_service.py](app/services/otp_delivery_service.py)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | May 2026 | Initial technical documentation |

---

**Document Maintainer:** Development Team  
**Last Updated:** May 4, 2026  
**Next Review:** Q3 2026
