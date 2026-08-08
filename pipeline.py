"""
Main pipeline: give it a list of sources (URLs and/or PDF paths),
get back structured, validated, traceable product records.

Usage:
    python pipeline.py

Edit the SOURCES list below, or import run_pipeline() into your own script/UI.
"""

import os
import json
from dotenv import load_dotenv

from scraper.web_scraper import scrape_product_page
from scraper.pdf_ingest import pdf_to_clean_text
from scraper.image_ingest import image_to_clean_text
from extractor.llm_extractor import extract_product
from extractor.validator import validate_record

load_dotenv()

OUTPUT_DIR = "data/output"


def process_webpage(url: str):
    print(f"\n[SCRAPING] {url}")
    page = scrape_product_page(url)
    if not page.success:
        print(f"  FAILED: {page.error}")
        return None
    print(f"  Got {len(page.clean_text)} chars of clean content")
    return extract_and_validate(page.clean_text, source_id=url)


def process_pdf(path: str):
    print(f"\n[READING PDF] {path}")
    parsed = pdf_to_clean_text(path)
    print(f"  {parsed.page_count} pages, {len(parsed.clean_text)} chars extracted")
    return extract_and_validate(parsed.clean_text, source_id=path)


def extract_and_validate(text: str, source_id: str):
    print(f"  [EXTRACTING] calling Groq (Llama 3.3 70B)...")
    record = extract_product(text, source_id=source_id)
    report = validate_record(record)

    print(f"  [VALIDATING]")
    print("  " + report.summary().replace("\n", "\n  "))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_name = "".join(c if c.isalnum() else "_" for c in record.product_name)[:60]
    out_path = os.path.join(OUTPUT_DIR, f"{safe_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "record": record.model_dump(),
            "validation": {
                "completeness_score": report.completeness_score,
                "missing_fields": report.missing_fields,
                "conflicts": report.conflicts,
                "overall_status": report.overall_status,
            }
        }, f, indent=2, ensure_ascii=False)
    print(f"  Saved -> {out_path}")

    return record, report


def process_image(path: str):
    print(f"\n[READING IMAGE] {path}")
    result = image_to_clean_text(path)
    if not result.success:
        print(f"  FAILED: {result.error}")
        return None
    print(f"  Got {len(result.extracted_text)} chars from vision model")
    return extract_and_validate(result.extracted_text, source_id=path)


def run_pipeline(urls: list[str] = None, pdf_paths: list[str] = None, image_paths: list[str] = None):
    results = []
    for url in (urls or []):
        r = process_webpage(url)
        if r:
            results.append(r)
    for path in (pdf_paths or []):
        r = process_pdf(path)
        if r:
            results.append(r)
    for path in (image_paths or []):
        r = process_image(path)
        if r:
            results.append(r)

    print(f"\n{'='*50}")
    print(f"Pipeline complete: {len(results)} products processed")
    return results


if __name__ == "__main__":
    # Edit these to point at your own sample sources
    SOURCES = {
        "urls": [
            "https://in.omega.com/pptst/SA1.html",
        ],
        "pdfs": [
            # "data/samples/some_datasheet.pdf",
        ],
        "images": [
            # "data/samples/product_label.jpg",
        ],
    }

    run_pipeline(urls=SOURCES["urls"], pdf_paths=SOURCES["pdfs"], image_paths=SOURCES["images"])
