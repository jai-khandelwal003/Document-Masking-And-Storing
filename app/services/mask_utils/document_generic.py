import os
import re
from typing import Tuple

from PIL import Image, ImageDraw, ImageEnhance
import pytesseract

from app.utils.image_utils import increase_size_and_resolution


tesseract_path = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path


PAN_REGEX = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
DL_PATTERNS = [
    ("dl-india-standard", re.compile(r"^[A-Z]{2}[0-9]{2}[0-9]{4}[0-9]{7}$")),
    ("dl-india-legacy", re.compile(r"^[A-Z]{2}[0-9]{2}[0-9]{11}$")),
    ("dl-india-compact", re.compile(r"^[A-Z]{2}[0-9]{13}$")),
]


def _norm_token(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _match_pan(candidate: str) -> str:
    if PAN_REGEX.fullmatch(candidate):
        return "pan-standard"
    return ""


def _match_dl(candidate: str) -> str:
    translate = str.maketrans({
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
    })
    normalized = str(candidate or "").upper()
    if len(normalized) >= 2:
        normalized = normalized[:2] + normalized[2:].translate(translate)

    for name, pattern in DL_PATTERNS:
        if pattern.fullmatch(normalized):
            return name
    return ""


def _ocr_data(img, psm):
    return pytesseract.image_to_data(
        img,
        lang="eng",
        config=f"--oem 3 --psm {psm}",
        output_type=pytesseract.Output.DICT,
    )


def _mask_segments(length: int, mask_first8: bool, mask_last4: bool):
    if length <= 0:
        return []

    if mask_first8 and mask_last4:
        return [(0, length)]

    if mask_first8:
        end = min(8, length)
        return [(0, end)]

    if mask_last4:
        start = max(0, length - 4)
        return [(start, length)]

    return []


def _mask_partial_candidate(draw, boxes, candidate_len, x_scale, y_scale, mask_first8, mask_last4):
    segments = _mask_segments(candidate_len, mask_first8, mask_last4)
    if not segments:
        return

    char_total = 0
    mapped_boxes = []
    for left, top, width, height, token_chars in boxes:
        token_chars = max(1, int(token_chars))
        mapped_boxes.append((left, top, width, height, token_chars))
        char_total += token_chars

    if char_total <= 0:
        return

    # Re-map using candidate length to preserve approximate character proportions.
    rebuilt = []
    consumed = 0
    for idx, (left, top, width, height, _) in enumerate(mapped_boxes):
        remaining_boxes = len(mapped_boxes) - idx
        remaining_chars = candidate_len - consumed
        chars_here = max(1, remaining_chars // remaining_boxes)
        if idx == len(mapped_boxes) - 1:
            chars_here = max(1, remaining_chars)
        rebuilt.append((left, top, width, height, chars_here, consumed, consumed + chars_here))
        consumed += chars_here

    for seg_start, seg_end in segments:
        for left, top, width, height, chars_here, box_start, box_end in rebuilt:
            overlap_start = max(seg_start, box_start)
            overlap_end = min(seg_end, box_end)
            if overlap_start >= overlap_end:
                continue

            rel_start = (overlap_start - box_start) / max(chars_here, 1)
            rel_end = (overlap_end - box_start) / max(chars_here, 1)
            sx = int(round((left + (width * rel_start)) * x_scale))
            ex = int(round((left + (width * rel_end)) * x_scale))
            sy = int(round(top * y_scale))
            ey = int(round((top + height) * y_scale))
            if ex <= sx:
                ex = sx + 1
            draw.rectangle([sx, sy, ex, ey], fill="black")


def mask_pan_and_driving_licence(
    image_path: str,
    output_path: str,
    mask_pan: bool = True,
    mask_driving_licence: bool = True,
    mask_first8: bool = True,
    mask_last4: bool = False,
) -> Tuple[bool, bool, int, int, str, str, float, float, str, str]:
    if not os.path.exists(image_path):
        return False, False, 0, 0, "", "", 0.0, 0.0, "", ""

    original_image = Image.open(image_path)
    original_width, original_height = original_image.size
    image_size = os.path.getsize(image_path)

    processed = increase_size_and_resolution(original_image, image_size)
    processed = ImageEnhance.Contrast(processed).enhance(2)
    processed = processed.convert("L")
    processed_width, processed_height = processed.size

    x_scale = original_width / max(processed_width, 1)
    y_scale = original_height / max(processed_height, 1)

    binary = processed.point(lambda p: 255 if p > 145 else 0)

    draw = ImageDraw.Draw(original_image)
    seen_rects = set()

    pan_count = 0
    dl_count = 0
    pan_value = ""
    dl_value = ""
    pan_pattern = ""
    dl_pattern = ""

    def _scan_ocr_pass(data) -> bool:
        nonlocal pan_count, dl_count, pan_value, dl_value, pan_pattern, dl_pattern
        found_in_pass = False
        texts = data.get("text", [])
        for i in range(len(texts)):
            for span in (1, 2, 3):
                if i + span > len(texts):
                    continue

                parts = [_norm_token(texts[i + j]) for j in range(span)]
                if not all(parts):
                    continue
                candidate = "".join(parts)

                pan_match = _match_pan(candidate) if mask_pan else ""
                dl_match = _match_dl(candidate) if mask_driving_licence else ""
                matched_pan = bool(pan_match)
                matched_dl = bool(dl_match)
                if not (matched_pan or matched_dl):
                    continue

                boxes = []
                for j in range(span):
                    idx = i + j
                    boxes.append(
                        (
                            data["left"][idx],
                            data["top"][idx],
                            data["width"][idx],
                            data["height"][idx],
                            len(parts[j]),
                        )
                    )

                min_x = min(box[0] for box in boxes)
                min_y = min(box[1] for box in boxes)
                max_x = max(box[0] + box[2] for box in boxes)
                max_y = max(box[1] + box[3] for box in boxes)

                key = (
                    int(min_x / 20),
                    int(min_y / 20),
                    int(max_x / 20),
                    int(max_y / 20),
                )
                if key in seen_rects:
                    continue
                seen_rects.add(key)

                # Apply partial masking for PAN/DL based on selected mode.
                _mask_partial_candidate(
                    draw,
                    boxes,
                    len(candidate),
                    x_scale,
                    y_scale,
                    mask_first8,
                    mask_last4,
                )

                if matched_pan:
                    pan_count += 1
                    pan_value = pan_value or candidate
                    pan_pattern = pan_pattern or pan_match
                    found_in_pass = True
                if matched_dl:
                    dl_count += 1
                    dl_value = dl_value or candidate
                    dl_pattern = dl_pattern or dl_match
                    found_in_pass = True

        return found_in_pass

    found = _scan_ocr_pass(_ocr_data(processed, 6))
    if not found:
        found = _scan_ocr_pass(_ocr_data(processed, 11))
    if not found:
        _scan_ocr_pass(_ocr_data(binary, 6))

    if pan_count == 0 and dl_count == 0:
        return False, False, 0, 0, "", "", 0.0, 0.0, "", ""

    original_image.save(output_path)
    pan_conf = min(0.98, 0.62 + (0.1 * pan_count)) if pan_count > 0 else 0.0
    dl_conf = min(0.97, 0.58 + (0.1 * dl_count)) if dl_count > 0 else 0.0
    return pan_count > 0, dl_count > 0, pan_count, dl_count, pan_value, dl_value, pan_conf, dl_conf, pan_pattern, dl_pattern
