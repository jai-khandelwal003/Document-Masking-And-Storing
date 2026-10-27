import smtplib
import re
from email.mime.text import MIMEText

from flask import current_app


class OtpDeliveryError(Exception):
    pass


def _is_valid_email(value):
    candidate = str(value or "").strip()
    if not candidate:
        return False
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", candidate) is not None


def _build_email_body(job_id, otp):
    return (
        "Your identity verification OTP is below:\n\n"
        f"OTP: {otp}\n"
        f"Job ID: {job_id}\n\n"
        "This OTP expires soon. If you did not request this, ignore this message."
    )


def _send_otp_via_email(job_id, otp, recipient_email=""):
    smtp_host = str(current_app.config.get("OTP_EMAIL_SMTP_HOST", "")).strip()
    smtp_port = int(current_app.config.get("OTP_EMAIL_SMTP_PORT", 587))
    smtp_username = str(current_app.config.get("OTP_EMAIL_USERNAME", "")).strip()
    smtp_password = str(current_app.config.get("OTP_EMAIL_PASSWORD", "")).strip()
    smtp_use_tls = bool(current_app.config.get("OTP_EMAIL_USE_TLS", True))
    from_email = str(current_app.config.get("OTP_EMAIL_FROM", "")).strip()
    configured_to_email = str(current_app.config.get("OTP_EMAIL_TO", "")).strip()
    to_email = str(recipient_email or configured_to_email).strip()
    subject_prefix = str(current_app.config.get("OTP_EMAIL_SUBJECT_PREFIX", "Smart Masking")).strip() or "Smart Masking"

    if not _is_valid_email(to_email):
        raise OtpDeliveryError("Invalid recipientEmail")

    required = {
        "OTP_EMAIL_SMTP_HOST": smtp_host,
        "OTP_EMAIL_USERNAME": smtp_username,
        "OTP_EMAIL_PASSWORD": smtp_password,
        "OTP_EMAIL_FROM": from_email,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise OtpDeliveryError(f"Missing email OTP config: {', '.join(missing)}")

    message = MIMEText(_build_email_body(job_id, otp), "plain", "utf-8")
    message["Subject"] = f"{subject_prefix} OTP"
    message["From"] = from_email
    message["To"] = to_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(from_email, [to_email], message.as_string())
    except Exception as exc:
        raise OtpDeliveryError(f"Failed to send OTP email: {exc}") from exc

    return {
        "delivery": "email",
        "target": to_email,
    }


def deliver_identity_otp(job_id, otp, recipient_email=""):
    provider = str(current_app.config.get("IDENTITY_OTP_PROVIDER", "demo")).strip().lower() or "demo"

    if provider == "email":
        return _send_otp_via_email(job_id, otp, recipient_email=recipient_email)

    if provider == "demo":
        target = str(recipient_email or "api-response").strip() or "api-response"
        return {
            "delivery": "demo-response",
            "target": target,
        }

    raise OtpDeliveryError("Unsupported IDENTITY_OTP_PROVIDER. Use demo or email.")
