from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pytesseract
from PIL import Image

from app.services.mask_utils.aadhaar import _already_masked, mask_aadhaar
from app.utils.validate_addhar import is_valid_aadhaar


def valid_number(seed):
    base = f"{2 + seed % 7}{(seed * 7919) % 10 ** 10:010d}"
    for check in range(10):
        if is_valid_aadhaar(base + str(check)):
            return base + str(check)
    raise AssertionError("no valid check digit")


def ocr_data(*numbers_at):
    """Fake pytesseract data: each (number, x, y) becomes three 4-digit tokens in a row."""
    data = {"text": [], "left": [], "top": [], "width": [], "height": [], "conf": []}
    for number, x, y in numbers_at:
        for index in range(3):
            data["text"].append(number[index * 4 : index * 4 + 4])
            data["left"].append(x + index * 60)
            data["top"].append(y)
            data["width"].append(50)
            data["height"].append(24)
            data["conf"].append(90)
    return data


EMPTY = ocr_data()
A = valid_number(1)
B = valid_number(2)


class AadhaarMaskerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "in.png")
        Image.new("RGB", (800, 400), "white").save(self.src)
        self.dst = os.path.join(self.tmp, "out.png")

    def run_masker(self, *passes, first8=True, last4=False):
        with patch.object(pytesseract, "image_to_data", side_effect=list(passes)) as ocr:
            result = mask_aadhaar(self.src, self.dst, first8, last4)
        return result, ocr

    def test_numbers_found_by_different_ocr_passes_are_all_masked(self):
        # Regression: the masker used to stop after the first successful pass, so a number that
        # only a later pass could read (here B) stayed visible next to an easy one (A).
        (found, number, count), ocr = self.run_masker(ocr_data((A, 40, 40)), ocr_data((B, 40, 200)), EMPTY)
        self.assertTrue(found)
        self.assertEqual(count, 2)
        self.assertEqual(number, A)
        self.assertEqual(ocr.call_count, 3)
        self.assertTrue(os.path.exists(self.dst))

    def test_same_number_seen_by_two_passes_is_counted_once(self):
        (found, number, count), _ = self.run_masker(ocr_data((A, 40, 40)), ocr_data((A, 40, 40)), ocr_data((A, 40, 40)))
        self.assertEqual((found, number, count), (True, A, 1))

    def test_slightly_shifted_detection_of_the_same_number_is_counted_once(self):
        (found, number, count), _ = self.run_masker(ocr_data((A, 40, 40)), ocr_data((A, 47, 44)), EMPTY)
        self.assertEqual(count, 1)

    def test_two_numbers_on_the_same_pass_are_both_masked(self):
        (found, number, count), _ = self.run_masker(ocr_data((A, 40, 40), (B, 40, 220)), EMPTY, EMPTY)
        self.assertEqual(count, 2)

    def test_nothing_found_writes_no_output(self):
        (found, number, count), ocr = self.run_masker(EMPTY, EMPTY, EMPTY)
        self.assertEqual((found, number, count), (False, "", 0))
        self.assertFalse(os.path.exists(self.dst))
        self.assertEqual(ocr.call_count, 3)

    def test_missing_input_file_is_handled(self):
        self.assertEqual(mask_aadhaar(os.path.join(self.tmp, "absent.png"), self.dst, True, False), (False, "", 0))


class OverlapHelperTests(unittest.TestCase):
    def test_overlap_detection(self):
        masked = [(100, 100, 300, 130)]
        self.assertTrue(_already_masked((105, 102, 305, 132), masked))
        self.assertFalse(_already_masked((100, 200, 300, 230), masked))
        self.assertFalse(_already_masked((400, 100, 600, 130), masked))
        self.assertFalse(_already_masked((100, 100, 300, 130), []))


if __name__ == "__main__":
    unittest.main()
