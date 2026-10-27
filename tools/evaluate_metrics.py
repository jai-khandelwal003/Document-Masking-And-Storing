import argparse
import csv
import json
import os
from collections import defaultdict

import requests


def _bool_from_value(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _detected_for_type(response_json, doc_type):
    doc_type = str(doc_type or "").strip().lower()
    if doc_type == "aadhaar":
        return bool(response_json.get("aadhaarDetected", False))
    if doc_type == "pan":
        return bool(response_json.get("panDetected", False))
    if doc_type in {"dl", "driving_licence", "driving_license"}:
        return bool(response_json.get("drivingLicenceDetected", False))
    if doc_type == "all":
        return bool(
            response_json.get("aadhaarDetected", False)
            or response_json.get("panDetected", False)
            or response_json.get("drivingLicenceDetected", False)
        )
    return False


def _safe_div(num, den):
    return (float(num) / float(den)) if den else 0.0


def _f1(precision, recall):
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def evaluate(base_url, images_dir, labels_csv, timeout_sec, out_json_path="", out_csv_path=""):
    rows = []
    with open(labels_csv, "r", encoding="utf-8", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            rows.append(row)

    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "latency_ms": []})

    for row in rows:
        filename = str(row.get("filename", "")).strip()
        document_type = str(row.get("document_type", "")).strip().lower()
        expected = _bool_from_value(row.get("expected_detected", "0"))

        if not filename or document_type not in {"aadhaar", "pan", "dl", "all"}:
            print(f"Skipping invalid row: {row}")
            continue

        image_path = os.path.join(images_dir, filename)
        if not os.path.exists(image_path):
            print(f"Missing image: {image_path}")
            continue

        with open(image_path, "rb") as image_file:
            files = {"file": (filename, image_file, "image/jpeg")}
            data = {
                "document_type": document_type,
                "first8_mask": "true",
                "last4_mask": "false",
                "mask_qr": "false",
            }
            try:
                resp = requests.post(
                    f"{base_url.rstrip('/')}/mask/document",
                    files=files,
                    data=data,
                    timeout=timeout_sec,
                )
            except requests.RequestException as exc:
                print(f"Request failed for {filename}: {exc}")
                continue

        latency_ms = int(resp.elapsed.total_seconds() * 1000)
        if not resp.ok:
            print(f"Non-200 for {filename}: {resp.status_code} {resp.text[:160]}")
            continue

        payload = resp.json()
        predicted = _detected_for_type(payload, document_type)

        bucket = stats[document_type]
        bucket["latency_ms"].append(latency_ms)
        if expected and predicted:
            bucket["tp"] += 1
        elif (not expected) and predicted:
            bucket["fp"] += 1
        elif expected and (not predicted):
            bucket["fn"] += 1
        else:
            bucket["tn"] += 1

    print("\nEvaluation Summary")
    print("Document Type | Precision | Recall | F1 | Avg Time (ms) | Samples")
    print("-" * 74)

    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "latency_ms": []}

    summary_rows = []

    for doc_type in ("aadhaar", "pan", "dl", "all"):
        bucket = stats[doc_type]
        tp, fp, fn, tn = bucket["tp"], bucket["fp"], bucket["fn"], bucket["tn"]
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1_score = _f1(precision, recall)
        avg_time = int(sum(bucket["latency_ms"]) / len(bucket["latency_ms"])) if bucket["latency_ms"] else 0
        samples = tp + fp + fn + tn

        overall["tp"] += tp
        overall["fp"] += fp
        overall["fn"] += fn
        overall["tn"] += tn
        overall["latency_ms"].extend(bucket["latency_ms"])

        print(
            f"{doc_type:<13} | {precision:>8.2f} | {recall:>6.2f} | {f1_score:>4.2f} | {avg_time:>13} | {samples:>7}"
        )
        summary_rows.append(
            {
                "documentType": doc_type,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1_score, 4),
                "avgTimeMs": avg_time,
                "samples": samples,
            }
        )

    op = _safe_div(overall["tp"], overall["tp"] + overall["fp"])
    orc = _safe_div(overall["tp"], overall["tp"] + overall["fn"])
    of1 = _f1(op, orc)
    oat = int(sum(overall["latency_ms"]) / len(overall["latency_ms"])) if overall["latency_ms"] else 0
    osamples = overall["tp"] + overall["fp"] + overall["fn"] + overall["tn"]

    print("-" * 74)
    print(f"{'overall':<13} | {op:>8.2f} | {orc:>6.2f} | {of1:>4.2f} | {oat:>13} | {osamples:>7}")

    overall_row = {
        "documentType": "overall",
        "precision": round(op, 4),
        "recall": round(orc, 4),
        "f1": round(of1, 4),
        "avgTimeMs": oat,
        "samples": osamples,
    }
    summary_rows.append(overall_row)

    if out_json_path:
        with open(out_json_path, "w", encoding="utf-8") as file_obj:
            json.dump({"rows": summary_rows}, file_obj, indent=2)
        print(f"Saved JSON summary: {out_json_path}")

    if out_csv_path:
        with open(out_csv_path, "w", encoding="utf-8", newline="") as file_obj:
            writer = csv.DictWriter(
                file_obj,
                fieldnames=["documentType", "precision", "recall", "f1", "avgTimeMs", "samples"],
            )
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"Saved CSV summary: {out_csv_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate Smart Document Masking metrics from labeled images.")
    parser.add_argument("--base-url", default="http://localhost:3000", help="Running API base URL")
    parser.add_argument("--images-dir", default="app/static/samples", help="Directory with evaluation images")
    parser.add_argument("--labels-csv", default="evaluation/labels_template.csv", help="CSV with filename,document_type,expected_detected")
    parser.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds")
    parser.add_argument("--out-json", default="", help="Optional JSON summary output path")
    parser.add_argument("--out-csv", default="", help="Optional CSV summary output path")
    args = parser.parse_args()

    evaluate(args.base_url, args.images_dir, args.labels_csv, args.timeout, args.out_json, args.out_csv)


if __name__ == "__main__":
    main()
