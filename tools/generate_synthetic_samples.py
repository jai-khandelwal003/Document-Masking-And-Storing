"""Generate synthetic ID-card style images (no real personal data) plus a labels CSV.

The Aadhaar numbers are random but Verhoeff-valid; PAN/DL values are random patterns.
Run: python tools/generate_synthetic_samples.py
"""
import argparse
import csv
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.utils.validate_addhar import is_valid_aadhaar  # noqa: E402

FONT_CANDIDATES = ["arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]
NAMES = ["Asha Verma", "Rohan Mehta", "Priya Nair", "Imran Sheikh", "Kavya Reddy", "Arjun Das"]
STATES = ["KA", "MH", "DL", "TN", "GJ", "RJ"]


def _font(size):
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _aadhaar_number(rng, valid=True):
    while True:
        digits = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
        for check in range(10):
            candidate = digits + str(check)
            if is_valid_aadhaar(candidate) == valid:
                return candidate


def _pan(rng):
    letters = lambda n: "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(n))
    return f"{letters(5)}{rng.randint(1000, 9999)}{letters(1)}"


def _dl(rng):
    return f"{rng.choice(STATES)}{rng.randint(10, 30):02d}{rng.randint(2005, 2022)}{rng.randint(0, 9999999):07d}"


def _card(title, lines, number_text, font_size=54):
    img = Image.new("RGB", (1000, 620), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 1000, 90], fill=(230, 235, 245))
    draw.text((40, 22), title, fill="black", font=_font(40))
    y = 140
    for line in lines:
        draw.text((40, y), line, fill=(40, 40, 40), font=_font(34))
        y += 60
    if number_text:
        draw.text((40, 470), number_text, fill="black", font=_font(font_size))
    return img


def _degrade(img, rng):
    img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.2)))
    pixels = img.load()
    for _ in range(img.width * img.height // 40):
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        v = rng.randint(90, 255)
        pixels[x, y] = (v, v, v)
    return img


def generate(out_dir, labels_csv, seed=7, per_group=5):
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)
    rows = []

    def save(name, img, doc_type, expected):
        img.save(os.path.join(out_dir, name), "PNG")
        rows.append((name, doc_type, 1 if expected else 0))

    for i in range(per_group):
        num = _aadhaar_number(rng)
        spaced = f"{num[:4]} {num[4:8]} {num[8:]}"
        card = _card("Government of India - Aadhaar", [rng.choice(NAMES), "DOB: 01/01/1990", "Male"], spaced)
        save(f"aadhaar_clean_{i}.png", card, "aadhaar", True)
        save(f"aadhaar_noisy_{i}.png", _degrade(card, rng), "aadhaar", True)

    for i in range(3):
        save(f"aadhaar_none_{i}.png", _card("Library Membership", [rng.choice(NAMES), "Member since 2019"], ""), "aadhaar", False)
    for i in range(3):
        bad = _aadhaar_number(rng, valid=False)
        card = _card("Order Reference", [rng.choice(NAMES), "Tracking number"], f"{bad[:4]} {bad[4:8]} {bad[8:]}")
        save(f"aadhaar_badchecksum_{i}.png", card, "aadhaar", False)

    for i in range(per_group):
        card = _card("INCOME TAX DEPARTMENT", [rng.choice(NAMES).upper(), "Permanent Account Number"], _pan(rng))
        save(f"pan_clean_{i}.png", card, "pan", True)
        save(f"pan_noisy_{i}.png", _degrade(card, rng), "pan", True)
    for i in range(3):
        save(f"pan_none_{i}.png", _card("Gym Membership", [rng.choice(NAMES), "Plan: Annual"], ""), "pan", False)

    for i in range(per_group):
        card = _card("DRIVING LICENCE", [rng.choice(NAMES), "Valid till 2035"], _dl(rng))
        save(f"dl_clean_{i}.png", card, "dl", True)
        save(f"dl_noisy_{i}.png", _degrade(card, rng), "dl", True)
    for i in range(3):
        save(f"dl_none_{i}.png", _card("Parking Permit", [rng.choice(NAMES), "Zone B"], ""), "dl", False)

    with open(labels_csv, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "document_type", "expected_detected"])
        writer.writerows(rows)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="evaluation/samples")
    parser.add_argument("--labels-csv", default="evaluation/labels_synthetic.csv")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    count = generate(args.out_dir, args.labels_csv, seed=args.seed)
    print(f"Wrote {count} images to {args.out_dir} and labels to {args.labels_csv}")


if __name__ == "__main__":
    main()
