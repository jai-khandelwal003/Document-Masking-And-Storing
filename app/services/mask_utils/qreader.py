import cv2
import numpy as np
import logging
from qreader import QReader


def _mask_quads(image_bgr, quads):
    count = 0
    for quad in quads:
        pts = np.array(quad, dtype=np.int32)
        if pts.shape[0] >= 4:
            cv2.fillPoly(image_bgr, [pts], (0, 0, 0))
            count += 1
    return count


def _extract_quads_from_qreader(results):
    quads = []
    for res in results or []:
        if isinstance(res, dict) and res.get("quad_xy") is not None:
            quads.append(res["quad_xy"])
    return quads


def _detect_quads_opencv(image_bgr):
    detector = cv2.QRCodeDetector()
    ok, _, points, _ = detector.detectAndDecodeMulti(image_bgr)
    if not ok or points is None:
        return []

    quads = []
    for quad in points:
        quads.append(quad.tolist())
    return quads


def mask_qr_code_with_qreader(
    image_path: str,
    output_path: str
) -> tuple[bool, int, str]:
    """
    Detects and masks QR codes in an image using QReader.

    Args:
        image_path (str): Path to input image
        output_path (str): Path to save masked image

    Returns:
        tuple(bool, int, str): (QR detected, number of QR codes masked, engine used)
    """

    try:
        reader = QReader()
        image_bgr = cv2.imread(image_path)

        if image_bgr is None:
            raise ValueError("Unable to read image")

        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

        results = reader.detect(image_rgb)

        quads = _extract_quads_from_qreader(results)
        engine = "qreader"
        if not quads:
            # Fallback for environments where qreader detection is weak.
            quads = _detect_quads_opencv(image_bgr)
            engine = "opencv-fallback"

        if not quads:
            logging.info("No QR codes detected")
            return False, 0, "none"

        masked_count = _mask_quads(image_bgr, quads)

        cv2.imwrite(output_path, image_bgr)
        return masked_count > 0, masked_count, engine

    except Exception as e:
        logging.exception("QR masking failed")
        return False, 0, "none"
