# Accuracy results (synthetic benchmark)

Generated with `python tools/generate_synthetic_samples.py` (seed 7) and
`python tools/evaluate_metrics.py --in-process --images-dir evaluation/samples --labels-csv evaluation/labels_synthetic.csv`.

The 42 images contain **no real personal data**: random Verhoeff-valid Aadhaar numbers, random PAN/DL patterns, a
"noisy" variant of each (rotation, blur, pixel noise) and negatives (no number, or a 12-digit number with a bad checksum).
Measured with Tesseract on Windows, first-8 masking, one image per request.

| Mode | Type | Precision | Recall | F1 | Avg time |
|------|------|-----------|--------|----|----------|
| Default (`AADHAAR_ALLOW_UNCHECKED=true`) | Aadhaar | 0.73 | 0.80 | 0.76 | ~1.1 s |
| | PAN | 1.00 | 0.40 | 0.57 | ~0.8 s |
| | Driving licence | 1.00 | 1.00 | 1.00 | ~0.7 s |
| Strict (`AADHAAR_ALLOW_UNCHECKED=false`) | Aadhaar | 1.00 | 0.60 | 0.75 | ~1.0 s |

## What the numbers mean
- Aadhaar false positives in default mode are the three bad-checksum negatives: the service deliberately also masks
  12-digit numbers that fail the checksum, because OCR noise breaks valid numbers. Strict mode removes those false
  positives but misses more noisy cards. For a masking tool, a missed number is worse than an extra black box.
- PAN recall is low: Tesseract reads some digits as `/` and does not read the noisy PAN images at all.
- These are **synthetic** cards with clean fonts. Real photographs (glare, skew, holograms) will do worse.
  Treat this as a regression benchmark, not a claim of real-world accuracy.
- Only the first page of a PDF is processed, and a person must always check the output.

Raw numbers: `results_synthetic.json`, `results_synthetic_strict.json`.
