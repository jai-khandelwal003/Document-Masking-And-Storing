from app.utils.validate_addhar import is_valid_aadhaar


def _digits_only(value: str) -> str:
    translation = {
        "O": "0",
        "o": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "l": "1",
        "|": "1",
        "Z": "2",
        "z": "2",
        "S": "5",
        "s": "5",
        "G": "6",
        "B": "8",
    }
    normalized = "".join(translation.get(ch, ch) for ch in str(value))
    return "".join(ch for ch in normalized if ch.isdigit())


def _is_probable_aadhaar(value: str) -> bool:
    # Fallback when checksum validation fails because OCR introduces minor noise.
    return len(value) == 12 and value.isdigit() and value[0] in "23456789"


def detect_aadhaar_number(data) -> list:
    """
    Detect Aadhaar number positions from OCR text tokens.
    """

    aadhaar_numbers = []
    strict_hits = []

    for i in range(len(data)):
        digits = _digits_only(data[i])
        if is_valid_aadhaar(digits):
            strict_hits.append([i])

    for i in range(len(data) - 1):
        joined = _digits_only(data[i]) + _digits_only(data[i + 1])
        if is_valid_aadhaar(joined):
            strict_hits.append([i, i + 1])

    for i in range(len(data) - 2):
        joined = _digits_only(data[i]) + _digits_only(data[i + 1]) + _digits_only(data[i + 2])
        if is_valid_aadhaar(joined):
            strict_hits.append([i, i + 1, i + 2])

    if strict_hits:
        return strict_hits

    # Fallback: probable Aadhaar pattern when strict checksum misses due to OCR quality.
    for i in range(len(data)):
        if _is_probable_aadhaar(_digits_only(data[i])):
            aadhaar_numbers.append([i])

    for i in range(len(data) - 1):
        joined = _digits_only(data[i]) + _digits_only(data[i + 1])
        if _is_probable_aadhaar(joined):
            aadhaar_numbers.append([i, i + 1])

    for i in range(len(data) - 2):
        joined = _digits_only(data[i]) + _digits_only(data[i + 1]) + _digits_only(data[i + 2])
        if _is_probable_aadhaar(joined):
            aadhaar_numbers.append([i, i + 1, i + 2])

    return aadhaar_numbers


def divide_rectangle(rect, parts):
    x, y, w, h = rect

    if parts == 3:
        width = w // 3
        return [
            (x, y, width, h),
            (x + width, y, width, h),
            (x + 2 * width, y, width, h),
        ]

    if parts == 2:
        width = w // 2
        return [
            (x, y, width, h),
            (x + width, y, width, h),
        ]

    return [rect]


def get_numbers_and_positions_from_addhar(data, detected_positions):
    """
    Map detected Aadhaar digits to their bounding boxes.
    """

    results = []

    for positions in detected_positions:
        token_boxes = []
        merged_digits = ""

        for index in positions:
            txt = _digits_only(data["text"][index])
            if not txt:
                continue

            x = data["left"][index]
            y = data["top"][index]
            w = data["width"][index]
            h = data["height"][index]
            token_boxes.append((x, y, w, h))
            merged_digits += txt

        if len(merged_digits) != 12 or not token_boxes:
            continue

        min_x = min(box[0] for box in token_boxes)
        min_y = min(box[1] for box in token_boxes)
        max_x = max(box[0] + box[2] for box in token_boxes)
        max_y = max(box[1] + box[3] for box in token_boxes)
        rects = divide_rectangle((min_x, min_y, max_x - min_x, max_y - min_y), 3)

        group = [
            (merged_digits[:4], rects[0]),
            (merged_digits[4:8], rects[1]),
            (merged_digits[8:], rects[2]),
        ]
        results.append(group)

    return results
