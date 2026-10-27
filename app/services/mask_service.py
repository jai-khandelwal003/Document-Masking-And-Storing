import os
import uuid
import shutil
import hmac
import tempfile
from datetime import datetime, timezone
from werkzeug.datastructures import FileStorage
from flask import has_app_context, current_app
from PIL import Image

from app.config import Config
from app.services.file_service import handle_file_upload
from app.services.access_service import register_job_for_access, register_identity_vault, get_person_document_profile
from app.utils.hash_utils import hash_file_sha256, hmac_sha256


OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _convert_pdf_first_page_to_jpg(input_pdf_path: str) -> str:
    errors = []
    render_dpi = max(120, min(300, int(getattr(Config, "PDF_RENDER_DPI", 180))))

    # Primary path: PyMuPDF works well on Windows without external poppler/gs tools.
    try:
        import fitz  # type: ignore

        with fitz.open(input_pdf_path) as doc:
            if doc.page_count < 1:
                raise ValueError("PDF has no pages")
            page = doc.load_page(0)
            pix = page.get_pixmap(alpha=False, dpi=render_dpi)

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        output_path = temp_file.name
        temp_file.close()
        pix.save(output_path)
        return output_path
    except Exception as exc:
        errors.append(exc)

    # Fallback path: PIL may work when PDF plugins are present.
    try:
        with Image.open(input_pdf_path) as pdf_image:
            first_page = pdf_image.convert("RGB")
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            output_path = temp_file.name
            temp_file.close()
            first_page.save(output_path, format="JPEG", quality=95)
            return output_path
    except Exception as exc:
        errors.append(exc)

    raise RuntimeError("; ".join(str(err) for err in errors if str(err)) or "PDF conversion failed")


class MaskResponse:
    def __init__(
        self,
        error,
        message,
        aadhaar_detected,
        qr_detected,
        output_image_path="",
        output_image_url="",
        aadhaar_number="",
        aadhaar_hash="",
        aadhaar_preview="",
        input_file_hash="",
        output_file_hash="",
        hash_algorithm="sha256",
        integrity_token="",
        qr_engine="",
        job_id="",
        processed_at="",
        no_of_aadhaar_detected=0,
        no_of_qr_detected=0,
        document_type="aadhaar",
        pan_detected=False,
        driving_licence_detected=False,
        pan_preview="",
        driving_licence_preview="",
        no_of_pan_detected=0,
        no_of_driving_licence_detected=0,
        detection_confidence=None,
        matched_patterns=None,
        masked_regions=None,
        access_challenge_available=False,
        access_challenge_type="",
        access_challenge_hint="",
        identity_vault_enabled=False,
        identity_pin_mode="",
        identity_pin_hint="",
        profile_exists=False,
        profile_linked_documents_count=0,
        profile_linked_documents=None,
        profile_auto_loaded=False,
        profile_key="",
    ):
        self.error = error
        self.message = message
        self.aadhaar_detected = aadhaar_detected
        self.qr_detected = qr_detected
        self.output_image_path = output_image_path
        self.output_image_url = output_image_url
        self.aadhaar_number = aadhaar_number
        self.aadhaar_hash = aadhaar_hash
        self.aadhaar_preview = aadhaar_preview
        self.input_file_hash = input_file_hash
        self.output_file_hash = output_file_hash
        self.hash_algorithm = hash_algorithm
        self.integrity_token = integrity_token
        self.qr_engine = qr_engine
        self.job_id = job_id
        self.processed_at = processed_at
        self.no_of_aadhaar_detected = no_of_aadhaar_detected
        self.no_of_qr_detected = no_of_qr_detected
        self.document_type = document_type
        self.pan_detected = pan_detected
        self.driving_licence_detected = driving_licence_detected
        self.pan_preview = pan_preview
        self.driving_licence_preview = driving_licence_preview
        self.no_of_pan_detected = no_of_pan_detected
        self.no_of_driving_licence_detected = no_of_driving_licence_detected
        self.detection_confidence = detection_confidence or {}
        self.matched_patterns = matched_patterns or {}
        self.masked_regions = masked_regions or {}
        self.access_challenge_available = bool(access_challenge_available)
        self.access_challenge_type = access_challenge_type
        self.access_challenge_hint = access_challenge_hint
        self.identity_vault_enabled = bool(identity_vault_enabled)
        self.identity_pin_mode = identity_pin_mode
        self.identity_pin_hint = identity_pin_hint
        self.profile_exists = bool(profile_exists)
        self.profile_linked_documents_count = int(profile_linked_documents_count or 0)
        self.profile_linked_documents = list(profile_linked_documents or [])
        self.profile_auto_loaded = bool(profile_auto_loaded)
        self.profile_key = str(profile_key or "")

    def to_dict(self):
        if has_app_context():
            show_raw = bool(current_app.config.get("RETURN_RAW_AADHAAR", False))
        else:
            show_raw = bool(Config.RETURN_RAW_AADHAAR)

        return {
            "message": self.message,
            "aadhaarDetected": self.aadhaar_detected,
            "qrDetected": self.qr_detected,
            "aadhaarNumber": self.aadhaar_number if show_raw else "",
            "aadhaarPreview": self.aadhaar_preview,
            "aadhaarHash": self.aadhaar_hash,
            "inputFileHash": self.input_file_hash,
            "outputFileHash": self.output_file_hash,
            "hashAlgorithm": self.hash_algorithm,
            "integrityToken": self.integrity_token,
            "qrEngine": self.qr_engine,
            "jobId": self.job_id,
            "processedAt": self.processed_at,
            "noOfAadhaarDetected": self.no_of_aadhaar_detected,
            "noOfQrDetected": self.no_of_qr_detected,
            "documentType": self.document_type,
            "panDetected": self.pan_detected,
            "drivingLicenceDetected": self.driving_licence_detected,
            "panPreview": self.pan_preview,
            "drivingLicencePreview": self.driving_licence_preview,
            "noOfPanDetected": self.no_of_pan_detected,
            "noOfDrivingLicenceDetected": self.no_of_driving_licence_detected,
            "detectionConfidence": self.detection_confidence,
            "matchedPatterns": self.matched_patterns,
            "maskedRegions": self.masked_regions,
            "accessChallengeAvailable": self.access_challenge_available,
            "accessChallengeType": self.access_challenge_type,
            "accessChallengeHint": self.access_challenge_hint,
            "identityVaultEnabled": self.identity_vault_enabled,
            "identityPinMode": self.identity_pin_mode,
            "identityPinHint": self.identity_pin_hint,
            "profileExists": self.profile_exists,
            "profileLinkedDocumentsCount": self.profile_linked_documents_count,
            "profileLinkedDocuments": self.profile_linked_documents,
            "profileAutoLoaded": self.profile_auto_loaded,
            "profileKey": self.profile_key,
            "outputImagePath": self.output_image_path,
            "outputImageUrl": self.output_image_url,
            "error": self.error,
        }


def upload_aadhaar_and_mask(
    file: FileStorage,
    mask_first8: bool,
    mask_last4: bool,
    mask_qr: bool,
    document_type: str = "aadhaar",
) -> MaskResponse:
    return upload_document_and_mask(file, mask_first8, mask_last4, mask_qr, document_type=document_type)


def upload_document_and_mask(
    file: FileStorage,
    mask_first8: bool,
    mask_last4: bool,
    mask_qr: bool,
    document_type: str = "aadhaar",
) -> MaskResponse:
    def _sanitize_profile_docs_for_response(documents):
        sanitized = []
        for item in documents or []:
            if not isinstance(item, dict):
                continue
            doc_type = str(item.get("type", "")).strip().lower()
            if not doc_type:
                continue
            sanitized.append(
                {
                    "type": doc_type,
                    "id": str(item.get("id", "")).strip(),
                    "label": str(item.get("label", doc_type.upper())).strip() or doc_type.upper(),
                    "source": str(item.get("source", "registry")).strip() or "registry",
                    "fileName": str(item.get("fileName", "")).strip(),
                    "fileKey": str(item.get("fileKey", "")).strip(),
                }
            )
        return sanitized

    def _persist_original_uploads_enabled() -> bool:
        if has_app_context():
            return bool(current_app.config.get("PERSIST_ORIGINAL_UPLOADS", False))
        return bool(getattr(Config, "PERSIST_ORIGINAL_UPLOADS", False))

    def _build_integrity_token(job_id_value, processed_at_value, input_hash_value, output_hash_value):
        payload = f"{job_id_value}|{processed_at_value}|{input_hash_value}|{output_hash_value}"
        return hmac_sha256(payload, Config.HASH_SECRET)

    from app.services.mask_utils.aadhaar import mask_aadhaar

    def _aadhaar_preview(value: str, mask_first8_value: bool, mask_last4_value: bool) -> tuple[str, str, str]:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if len(digits) != 12:
            return "", "", ""

        if mask_first8_value and not mask_last4_value:
            return f"XXXXXXXX{digits[-4:]}", digits[-4:], "last4"
        if mask_last4_value and not mask_first8_value:
            return f"{digits[:8]}XXXX", digits[:8], "visible_fragment"
        if mask_first8_value and mask_last4_value:
            return "XXXXXXXXXXXX", "", ""
        return digits, digits, "visible_fragment"

    def _identifier_preview(value: str, mask_first8_value: bool, mask_last4_value: bool) -> tuple[str, str, str]:
        normalized = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
        if len(normalized) < 8:
            return "", "", ""

        if mask_first8_value and not mask_last4_value:
            preview = f"{'X' * 8}{normalized[8:]}"
            visible = normalized[8:]
            if len(visible) >= 4:
                return preview, visible, "visible_fragment"
            return preview, "", ""
        if mask_last4_value and not mask_first8_value:
            preview = f"{normalized[:-4]}XXXX"
            visible = normalized[:-4]
            if len(visible) >= 4:
                return preview, visible, "visible_fragment"
            return preview, "", ""
        if mask_first8_value and mask_last4_value:
            return "X" * len(normalized), "", ""
        return normalized, normalized, "visible_fragment"

    def _identity_primary_identifier(aadhaar_value: str, pan_value: str, dl_value: str):
        aadhaar_digits = "".join(ch for ch in str(aadhaar_value or "") if ch.isdigit())
        if len(aadhaar_digits) == 12:
            return aadhaar_digits, "aadhaar"

        pan_norm = "".join(ch for ch in str(pan_value or "").upper() if ch.isalnum())
        if len(pan_norm) >= 8:
            return pan_norm, "pan"

        dl_norm = "".join(ch for ch in str(dl_value or "").upper() if ch.isalnum())
        if len(dl_norm) >= 8:
            return dl_norm, "dl"

        return "", ""

    normalized_type = str(document_type or "aadhaar").strip().lower()
    input_path = handle_file_upload(file)
    temp_converted_path = ""
    input_path_for_processing = input_path

    if str(input_path).lower().endswith(".pdf"):
        try:
            temp_converted_path = _convert_pdf_first_page_to_jpg(input_path)
            input_path_for_processing = temp_converted_path
        except Exception as exc:
            if temp_converted_path and os.path.exists(temp_converted_path):
                os.remove(temp_converted_path)
            detail = str(exc).strip()
            if not detail:
                detail = "unknown PDF parsing error"
            return MaskResponse(
                error="pdf-conversion-failed",
                message=f"Unable to process PDF ({detail}). Ensure the file is valid, not password-protected, and try again.",
                aadhaar_detected=False,
                qr_detected=False,
                output_image_path="",
                output_image_url="",
                document_type=normalized_type,
            )

    job_id = uuid.uuid4().hex
    output_filename = f"masked_{job_id}.jpg"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    processed_at = datetime.now(timezone.utc).isoformat()

    input_hash = hash_file_sha256(input_path)

    try:
        aadhaar_detected = False
        aadhaar_number = ""
        aadhaar_count = 0
        pan_detected = False
        driving_licence_detected = False
        pan_count = 0
        driving_licence_count = 0
        pan_preview = ""
        driving_licence_preview = ""
        pan_confidence = 0.0
        driving_licence_confidence = 0.0
        pan_pattern = ""
        driving_licence_pattern = ""

        if normalized_type in {"aadhaar", "all"}:
            aadhaar_detected, aadhaar_number, aadhaar_count = mask_aadhaar(
                input_path_for_processing, output_path, mask_first8, mask_last4
            )

        if normalized_type in {"pan", "dl", "all"}:
            from app.services.mask_utils.document_generic import mask_pan_and_driving_licence

            if not os.path.exists(output_path):
                shutil.copy(input_path_for_processing, output_path)

            pan_detected, driving_licence_detected, pan_count, driving_licence_count, pan_preview, driving_licence_preview, pan_confidence, driving_licence_confidence, pan_pattern, driving_licence_pattern = (
                mask_pan_and_driving_licence(
                    output_path,
                    output_path,
                    mask_pan=normalized_type in {"pan", "all"},
                    mask_driving_licence=normalized_type in {"dl", "all"},
                    mask_first8=mask_first8,
                    mask_last4=mask_last4,
                )
            )

        is_masked = aadhaar_detected or pan_detected or driving_licence_detected

        qr_detected = False
        qr_count = 0
        qr_engine = "none"
        qr_warning = ""

        if mask_qr:
            if not os.path.exists(output_path):
                # Aadhaar masking may fail to produce an output image; copy input
                # so QR masking can still run independently.
                shutil.copy(input_path_for_processing, output_path)
            try:
                from app.services.mask_utils.qreader import mask_qr_code_with_qreader

                qr_detected, qr_count, qr_engine = mask_qr_code_with_qreader(output_path, output_path)
            except ModuleNotFoundError:
                qr_warning = " QR masking skipped because qreader is not installed."
                qr_engine = "not-installed"

        if is_masked:
            aadhaar_hash = hmac_sha256(aadhaar_number, Config.HASH_SECRET) if aadhaar_number else ""
            output_hash = hash_file_sha256(output_path)
            integrity_token = _build_integrity_token(job_id, processed_at, input_hash, output_hash)
            aadhaar_preview, access_challenge_value, access_challenge_type = _aadhaar_preview(
                aadhaar_number,
                mask_first8,
                mask_last4,
            )
            pan_preview_value, pan_challenge_value, pan_challenge_type = _identifier_preview(
                pan_preview,
                mask_first8,
                mask_last4,
            )
            dl_preview_value, dl_challenge_value, dl_challenge_type = _identifier_preview(
                driving_licence_preview,
                mask_first8,
                mask_last4,
            )
            aadhaar_confidence = min(0.98, 0.62 + (0.08 * aadhaar_count)) if aadhaar_detected else 0.0
            matched_patterns = {
                "aadhaar": "aadhaar-12-digit" if aadhaar_detected else "",
                "pan": pan_pattern,
                "drivingLicence": driving_licence_pattern,
            }
            detection_confidence = {
                "aadhaar": round(aadhaar_confidence, 2),
                "pan": round(pan_confidence, 2),
                "drivingLicence": round(driving_licence_confidence, 2),
                "qr": round(0.85 if qr_detected else 0.0, 2),
                "overall": round(max(aadhaar_confidence, pan_confidence, driving_licence_confidence, (0.85 if qr_detected else 0.0)), 2),
            }
            masked_regions = {
                "aadhaar": int(aadhaar_count),
                "pan": int(pan_count),
                "drivingLicence": int(driving_licence_count),
                "qr": int(qr_count),
                "total": int(aadhaar_count + pan_count + driving_licence_count + qr_count),
            }
            access_challenge_available = bool(access_challenge_value)
            access_challenge_hint = ""
            identity_vault_enabled = False
            identity_pin_mode = ""
            identity_pin_hint = ""
            profile_exists = False
            profile_linked_documents_count = 0
            profile_linked_documents = []
            profile_auto_loaded = False
            profile_key = ""

            primary_identifier, identity_document_type = _identity_primary_identifier(
                aadhaar_number,
                pan_preview,
                driving_licence_preview,
            )

            if primary_identifier:
                known_profile = get_person_document_profile(primary_identifier)
                profile_exists = bool(known_profile.get("exists", False))
                profile_linked_documents_count = int(known_profile.get("linkedCount", 0))
                profile_linked_documents = _sanitize_profile_docs_for_response(known_profile.get("documents", []))
                profile_auto_loaded = bool(profile_linked_documents)
                profile_key = str(known_profile.get("documentHash", "") or "").strip()

                # Derive a simple PIN mode from the selected masking strategy.
                if mask_first8 and not mask_last4:
                    identity_pin_mode = "last4"
                    identity_pin_hint = "Use last 4 visible characters as PIN"
                elif mask_last4 and not mask_first8:
                    identity_pin_mode = "first8"
                    identity_pin_hint = "Use first 8 visible characters as PIN"
                elif mask_first8 and mask_last4:
                    # Full masking leaves no visible fragment; allow deterministic PIN
                    # from the original identifier so OTP unlock can still work.
                    identity_pin_mode = "first8"
                    identity_pin_hint = "Identifier is fully masked. Use first 8 characters from the original document as PIN"

                if identity_pin_mode:
                    linked_docs = []
                    if aadhaar_detected:
                        linked_docs.append({"type": "aadhaar", "label": "Aadhaar"})
                    if pan_detected:
                        linked_docs.append({"type": "pan", "label": "PAN"})
                    if driving_licence_detected:
                        linked_docs.append({"type": "dl", "label": "Driving Licence"})
                    ok, _ = register_identity_vault(
                        job_id,
                        primary_identifier,
                        pin_mode=identity_pin_mode,
                        linked_documents=linked_docs,
                        document_type=identity_document_type or normalized_type,
                    )
                    identity_vault_enabled = bool(ok)

            if access_challenge_available:
                register_job_for_access(
                    job_id,
                    access_challenge_value,
                    f"/output/{output_filename}",
                    challenge_type=access_challenge_type,
                )
                access_challenge_hint = "Use visible characters left after masking"
            elif pan_challenge_value:
                register_job_for_access(
                    job_id,
                    pan_challenge_value,
                    f"/output/{output_filename}",
                    challenge_type=pan_challenge_type or "visible_fragment",
                )
                access_challenge_available = True
                access_challenge_type = pan_challenge_type or "visible_fragment"
                access_challenge_hint = "Use visible PAN characters left after masking"
            elif dl_challenge_value:
                register_job_for_access(
                    job_id,
                    dl_challenge_value,
                    f"/output/{output_filename}",
                    challenge_type=dl_challenge_type or "visible_fragment",
                )
                access_challenge_available = True
                access_challenge_type = dl_challenge_type or "visible_fragment"
                access_challenge_hint = "Use visible Driving Licence characters left after masking"
            elif aadhaar_detected and mask_first8 and mask_last4:
                fallback_secret = ""
                if has_app_context():
                    fallback_secret = str(current_app.config.get("ACCESS_FALLBACK_SECRET", "") or "").strip()
                if fallback_secret:
                    register_job_for_access(
                        job_id,
                        fallback_secret,
                        f"/output/{output_filename}",
                        challenge_type="fallback_secret",
                    )
                    access_challenge_available = True
                    access_challenge_type = "fallback_secret"
                    access_challenge_hint = "All digits are masked. Use fallback PIN + OTP for secure access"
                else:
                    access_challenge_hint = "No visible Aadhaar characters left after full masking"

            return MaskResponse(
                error="",
                message=f"Document masked successfully.{qr_warning}",
                aadhaar_detected=aadhaar_detected,
                qr_detected=qr_detected,
                output_image_path=output_path,
                output_image_url=f"/output/{output_filename}",
                aadhaar_number=aadhaar_number,
                aadhaar_hash=aadhaar_hash,
                aadhaar_preview=aadhaar_preview,
                input_file_hash=input_hash,
                output_file_hash=output_hash,
                hash_algorithm=Config.HASH_ALGORITHM,
                integrity_token=integrity_token,
                qr_engine=qr_engine,
                job_id=job_id,
                processed_at=processed_at,
                no_of_aadhaar_detected=aadhaar_count,
                no_of_qr_detected=qr_count,
                document_type=normalized_type,
                pan_detected=pan_detected,
                driving_licence_detected=driving_licence_detected,
                pan_preview=pan_preview_value or pan_preview,
                driving_licence_preview=dl_preview_value or driving_licence_preview,
                no_of_pan_detected=pan_count,
                no_of_driving_licence_detected=driving_licence_count,
                detection_confidence=detection_confidence,
                matched_patterns=matched_patterns,
                masked_regions=masked_regions,
                access_challenge_available=access_challenge_available,
                access_challenge_type=access_challenge_type,
                access_challenge_hint=access_challenge_hint,
                identity_vault_enabled=identity_vault_enabled,
                identity_pin_mode=identity_pin_mode,
                identity_pin_hint=identity_pin_hint,
                profile_exists=profile_exists,
                profile_linked_documents_count=profile_linked_documents_count,
                profile_linked_documents=profile_linked_documents,
                profile_auto_loaded=profile_auto_loaded,
                profile_key=profile_key,
            )

        if qr_detected:
            output_hash = hash_file_sha256(output_path)
            integrity_token = _build_integrity_token(job_id, processed_at, input_hash, output_hash)
            return MaskResponse(
                error="",
                message=f"QR masked successfully.{qr_warning}",
                aadhaar_detected=False,
                qr_detected=True,
                output_image_path=output_path,
                output_image_url=f"/output/{output_filename}",
                input_file_hash=input_hash,
                output_file_hash=output_hash,
                hash_algorithm=Config.HASH_ALGORITHM,
                integrity_token=integrity_token,
                qr_engine=qr_engine,
                job_id=job_id,
                processed_at=processed_at,
                no_of_aadhaar_detected=0,
                no_of_qr_detected=qr_count,
                document_type=normalized_type,
                detection_confidence={
                    "aadhaar": 0.0,
                    "pan": 0.0,
                    "drivingLicence": 0.0,
                    "qr": round(0.85 if qr_detected else 0.0, 2),
                    "overall": round(0.85 if qr_detected else 0.0, 2),
                },
                matched_patterns={"aadhaar": "", "pan": "", "drivingLicence": ""},
                masked_regions={"aadhaar": 0, "pan": 0, "drivingLicence": 0, "qr": int(qr_count), "total": int(qr_count)},
                access_challenge_available=False,
                access_challenge_type="",
                access_challenge_hint="No visible verification fragment available",
                identity_vault_enabled=False,
                identity_pin_mode="",
                identity_pin_hint="",
            )

        return MaskResponse(
            error="No supported document number detected",
            message="Masking failed",
            aadhaar_detected=False,
            qr_detected=False,
            input_file_hash=input_hash,
            hash_algorithm=Config.HASH_ALGORITHM,
            integrity_token="",
            qr_engine=qr_engine,
            job_id=job_id,
            processed_at=processed_at,
            document_type=normalized_type,
            detection_confidence={"aadhaar": 0.0, "pan": 0.0, "drivingLicence": 0.0, "qr": 0.0, "overall": 0.0},
            matched_patterns={"aadhaar": "", "pan": "", "drivingLicence": ""},
            masked_regions={"aadhaar": 0, "pan": 0, "drivingLicence": 0, "qr": 0, "total": 0},
            access_challenge_available=False,
            access_challenge_type="",
            access_challenge_hint="No visible verification fragment available",
            identity_vault_enabled=False,
            identity_pin_mode="",
            identity_pin_hint="",
        )

    finally:
        if (not _persist_original_uploads_enabled()) and os.path.exists(input_path):
            os.remove(input_path)
        if temp_converted_path and os.path.exists(temp_converted_path):
            os.remove(temp_converted_path)


def verify_integrity_token(job_id, processed_at, input_file_hash, output_file_hash, integrity_token):
    payload = f"{job_id}|{processed_at}|{input_file_hash}|{output_file_hash}"
    expected = hmac_sha256(payload, Config.HASH_SECRET)
    return hmac.compare_digest(expected, integrity_token)
