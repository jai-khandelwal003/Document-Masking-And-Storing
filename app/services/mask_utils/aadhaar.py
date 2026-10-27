import os
from typing import Tuple
from PIL import Image, ImageDraw, ImageEnhance
import pytesseract

tesseract_path = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path


from app.utils.image_utils import increase_size_and_resolution
from app.services.mask_utils.aadhar_helpers import (
    detect_aadhaar_number,
    get_numbers_and_positions_from_addhar,
    _digits_only,
)

os.environ.setdefault("TESSDATA_PREFIX", "./resources/4.0.01/")


def _already_masked(box, masked_boxes, threshold=0.5):
    """True if `box` mostly overlaps a box that was already masked (same number seen by another OCR pass)."""
    x1, y1, x2, y2 = box
    area = max(1, (x2 - x1) * (y2 - y1))
    for mx1, my1, mx2, my2 in masked_boxes:
        overlap_w = min(x2, mx2) - max(x1, mx1)
        overlap_h = min(y2, my2) - max(y1, my1)
        if overlap_w > 0 and overlap_h > 0:
            smaller = min(area, max(1, (mx2 - mx1) * (my2 - my1)))
            if (overlap_w * overlap_h) / smaller >= threshold:
                return True
    return False


def mask_aadhaar(
    image_path: str,
    output_path: str,
    mask_first8: bool,
    mask_last4: bool,
    angle: int = 0
) -> Tuple[bool, str, int]:

    if not os.path.exists(image_path):
        return False, "", 0

    original_image = Image.open(image_path)
    original_width, original_height = original_image.size
    image_size = os.path.getsize(image_path)

    processed = increase_size_and_resolution(original_image, image_size)
    processed = ImageEnhance.Contrast(processed).enhance(2)

    if angle:
        processed = processed.rotate(angle, expand=True)

    processed = processed.convert("L")
    processed_width, processed_height = processed.size

    # OCR is performed on the processed image; draw coordinates must be scaled
    # back to the original image space to mask the correct area.
    x_scale = original_width / max(processed_width, 1)
    y_scale = original_height / max(processed_height, 1)

    def _ocr_data(img, psm):
        return pytesseract.image_to_data(
            img,
            lang="eng",
            config=f"--oem 3 --psm {psm}",
            output_type=pytesseract.Output.DICT,
        )

    binary = processed.point(lambda p: 255 if p > 145 else 0)

    ocr_runs = []
    repeat_scan_data = None

    draw = ImageDraw.Draw(original_image)
    masked_count = 0
    aadhaar_number = ""
    seen_rects = set()
    masked_boxes = []

    for data in (_ocr_data(processed, 6), _ocr_data(processed, 11), _ocr_data(binary, 6)):
        ocr_runs.append(data)
        positions = detect_aadhaar_number(data["text"])
        if not positions:
            continue

        if repeat_scan_data is None:
            repeat_scan_data = data

        for group in get_numbers_and_positions_from_addhar(data, positions):
            aadhaar_number = aadhaar_number or "".join([x[0] for x in group])

            # Deduplicate same detection from multiple OCR passes.
            min_x = min(item[1][0] for item in group)
            min_y = min(item[1][1] for item in group)
            max_x = max(item[1][0] + item[1][2] for item in group)
            max_y = max(item[1][1] + item[1][3] for item in group)
            key = (
                int(min_x / 25),
                int(min_y / 25),
                int(max_x / 25),
                int(max_y / 25),
            )
            if key in seen_rects or _already_masked((min_x, min_y, max_x, max_y), masked_boxes):
                continue
            seen_rects.add(key)
            masked_boxes.append((min_x, min_y, max_x, max_y))

            mask_group = group
            if mask_first8 and not mask_last4:
                mask_group = group[:2]
            elif mask_last4 and not mask_first8:
                mask_group = group[2:]

            for _, (x, y, w, h) in mask_group:
                x = int(round(x * x_scale))
                y = int(round(y * y_scale))
                w = int(round(w * x_scale))
                h = int(round(h * y_scale))
                draw.rectangle([x, y, x + w, y + h], fill="black")

            masked_count += 1

        # Keep going after a hit: a later OCR pass can read a different number on the same page
        # that the first successful pass missed. All three passes already ran, so this costs nothing.

    # Additional pass: if one Aadhaar number was detected, mask repeated
    # occurrences of the same number elsewhere in the image.
    if aadhaar_number and repeat_scan_data is not None:
        target = aadhaar_number
        data = repeat_scan_data
        texts = data.get("text", [])
        for i in range(len(texts)):
            for span in (1, 2, 3):
                if i + span > len(texts):
                    continue

                joined = "".join(_digits_only(texts[i + j]) for j in range(span))
                if joined != target:
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
                        )
                    )

                min_x = min(box[0] for box in boxes)
                min_y = min(box[1] for box in boxes)
                max_x = max(box[0] + box[2] for box in boxes)
                max_y = max(box[1] + box[3] for box in boxes)
                key = (
                    int(min_x / 25),
                    int(min_y / 25),
                    int(max_x / 25),
                    int(max_y / 25),
                )
                if key in seen_rects:
                    continue
                seen_rects.add(key)

                rects = [
                    (min_x, min_y, (max_x - min_x) // 3, max_y - min_y),
                    (min_x + (max_x - min_x) // 3, min_y, (max_x - min_x) // 3, max_y - min_y),
                    (min_x + 2 * ((max_x - min_x) // 3), min_y, (max_x - min_x) - 2 * ((max_x - min_x) // 3), max_y - min_y),
                ]

                mask_group = rects
                if mask_first8 and not mask_last4:
                    mask_group = rects[:2]
                elif mask_last4 and not mask_first8:
                    mask_group = rects[2:]

                for x, y, w, h in mask_group:
                    sx = int(round(x * x_scale))
                    sy = int(round(y * y_scale))
                    sw = int(round(w * x_scale))
                    sh = int(round(h * y_scale))
                    draw.rectangle([sx, sy, sx + sw, sy + sh], fill="black")

                masked_count += 1

    if masked_count == 0:
        return False, "", 0

    original_image.save(output_path)
    return True, aadhaar_number, masked_count
