"""
Batch mode: process a whole CSV of sources in one shot.

CSV format (save as e.g. data/batch_sources.csv):
    type,source
    url,https://in.omega.com/pptst/SA1.html
    url,https://example.com/product2.html
    pdf,data/samples/valve_datasheet.pdf
    image,data/samples/product_label.jpg

Usage:
    python batch_pipeline.py data/batch_sources.csv
    python batch_pipeline.py data/batch_sources.csv --delay 2   # 2s between calls
"""

import csv
import sys
import time
import argparse
from dotenv import load_dotenv
from pipeline import process_webpage, process_pdf, process_image

load_dotenv()


def run_batch(csv_path: str, delay: float = 1.0):
    """Read a CSV of sources and process each one through the full pipeline."""
    results = {"ok": [], "failed": []}

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Batch: {len(rows)} sources from {csv_path}\n{'='*50}")

    for i, row in enumerate(rows):
        src_type = row.get("type", "").strip().lower()
        source = row.get("source", "").strip()

        if not src_type or not source:
            print(f"[{i+1}/{len(rows)}] SKIP — missing type or source in row: {row}")
            continue

        print(f"\n[{i+1}/{len(rows)}] {src_type.upper()}: {source}")
        try:
            if src_type == "url":
                result = process_webpage(source)
            elif src_type == "pdf":
                result = process_pdf(source)
            elif src_type == "image":
                result = process_image(source)
            else:
                print(f"  SKIP — unknown type '{src_type}' (use: url, pdf, image)")
                continue

            if result:
                record, report = result
                results["ok"].append({"source": source, "product": record.product_name,
                                      "status": report.overall_status,
                                      "completeness": f"{report.completeness_score*100:.0f}%"})
            else:
                results["failed"].append(source)

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append(source)

        if delay > 0 and i < len(rows) - 1:
            time.sleep(delay)

    print(f"\n{'='*50}")
    print(f"Batch complete: {len(results['ok'])} succeeded, {len(results['failed'])} failed")
    if results["ok"]:
        print("\nSucceeded:")
        for r in results["ok"]:
            print(f"  [{r['status'].upper()}] {r['product']} ({r['completeness']} complete) — {r['source']}")
    if results["failed"]:
        print("\nFailed:")
        for s in results["failed"]:
            print(f"  {s}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch process product sources from a CSV file")
    parser.add_argument("csv_file", help="Path to CSV file (columns: type, source)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds to wait between sources (default: 1.0)")
    args = parser.parse_args()
    run_batch(args.csv_file, delay=args.delay)
