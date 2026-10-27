import argparse
import csv
import json
import os
import sys
import time
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


def _make_poster(base_url, timeout_sec, in_process, cookie="", api_key=""):
    """Return post_mask(filename, fileobj, data) -> (status, json, latency_ms, body_text)."""
    if in_process:
        # Run entirely in a throwaway folder so benchmarking never touches real documents, databases or logs.
        import atexit
        import shutil
        import tempfile
        from unittest.mock import patch

        sandbox = tempfile.mkdtemp(prefix="sdm-eval-")
        atexit.register(shutil.rmtree, sandbox, ignore_errors=True)
        os.environ.update(
            {
                "IDENTITY_DOCS_DIR": os.path.join(sandbox, "identity_docs"),
                "ACCESS_STATE_DB_PATH": os.path.join(sandbox, "access_state.sqlite3"),
                "IDENTITY_DB_PATH": os.path.join(sandbox, "identity_profiles.sqlite3"),
                "AUDIT_LOG_PATH": os.path.join(sandbox, "audit.log"),
                "ORIGINAL_UPLOADS_DIR": os.path.join(sandbox, "uploads"),
                "UPLOAD_FOLDER": os.path.join(sandbox, "uploads_tmp"),
            }
        )
        from app import create_app
        from app.services import mask_service

        sandbox_output = os.path.join(sandbox, "output")
        os.makedirs(sandbox_output)
        patch.object(mask_service, "OUTPUT_DIR", sandbox_output).start()

        app = create_app()
        app.config.update(TESTING=True, RATE_LIMIT_ENABLED=False, API_KEY_REQUIRED=False)
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["auth_user"] = "evaluator"

        def post_in_process(filename, fileobj, data):
            started = time.time()
            resp = client.post(
                "/mask/document",
                data={**data, "file": (fileobj, filename)},
                content_type="multipart/form-data",
            )
            latency = int((time.time() - started) * 1000)
            return resp.status_code, resp.get_json(silent=True) or {}, latency, resp.get_data(as_text=True)

        return post_in_process

    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if api_key:
        headers["X-API-Key"] = api_key

    def post_remote(filename, fileobj, data):
        resp = requests.post(
            f"{base_url.rstrip('/')}/mask/document",
            files={"file": (filename, fileobj, "image/png")},
            data=data,
            headers=headers,
            timeout=timeout_sec,
        )
        payload = resp.json() if resp.ok else {}
        return resp.status_code, payload, int(resp.elapsed.total_seconds() * 1000), resp.text

    return post_remote


def evaluate(base_url, images_dir, labels_csv, timeout_sec, out_json_path="", out_csv_path="", in_process=False, cookie="", api_key=""):
    post_mask = _make_poster(base_url, timeout_sec, in_process, cookie, api_key)
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

        data = {
            "document_type": document_type,
            "first8_mask": "true",
            "last4_mask": "false",
            "mask_qr": "false",
        }
        with open(image_path, "rb") as image_file:
            try:
                status_code, payload, latency_ms, body = post_mask(filename, image_file, data)
            except requests.RequestException as exc:
                print(f"Request failed for {filename}: {exc}")
                continue

        if status_code != 200:
            print(f"Non-200 for {filename}: {status_code} {body[:160]}")
            continue
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
    parser.add_argument("--in-process", action="store_true", help="Run the app in this process (no server or login needed)")
    parser.add_argument("--cookie", default="", help="Session cookie header value for a running, login-protected service")
    parser.add_argument("--api-key", default="", help="X-API-Key value when API_KEY_REQUIRED=true")
    args = parser.parse_args()

    if args.in_process:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    evaluate(
        args.base_url, args.images_dir, args.labels_csv, args.timeout, args.out_json, args.out_csv,
        in_process=args.in_process, cookie=args.cookie, api_key=args.api_key,
    )


if __name__ == "__main__":
    main()
