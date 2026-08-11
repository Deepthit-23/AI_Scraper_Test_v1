"""
Unihack product enrichment pipeline.

Orchestrates: normalize -> classify -> enrich (web scrape) -> generate descriptions -> save CSV.

Usage:
    cd product-intel
    python -m unihack.unihack_pipeline --eval-only         # just score the 2 GT items
    python -m unihack.unihack_pipeline --limit 5 --no-enrich  # quick classify+describe, no web
    python -m unihack.unihack_pipeline --limit 20 --category "drill"
    python -m unihack.unihack_pipeline --limit 20 --category "impact"
    python -m unihack.unihack_pipeline                     # full 1000 rows (ask first!)

Input files (place these before running):
    unihack/data/input/Sample_1000_Items.csv
    unihack/data/ground_truth/expected_output_2rows.csv

Output:
    unihack/data/output/enriched_products.csv
"""

import os
import sys
import csv
import time
import argparse
from pathlib import Path

# ── Path setup (makes product-intel/ the Python root) ────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from unihack.normalization.manufacturer_lookup import normalize_manufacturer
from unihack.normalization.uom_table import normalize_unit
from unihack.classification.classifier import classify_product
from unihack.enrichment.manufacturer_finder import enrich_from_manufacturer
from unihack.description.generator import DescriptionInput, generate_descriptions
from unihack.evaluation.scorer import (
    load_ground_truth, score_product, print_report, check_char_limits
)

# ── Paths ─────────────────────────────────────────────────────────────────────
_UNIHACK = _ROOT / "unihack"
INPUT_CSV      = _UNIHACK / "data" / "input"  / "Sample_1000_Items.csv"
GT_CSV         = _UNIHACK / "data" / "ground_truth" / "expected_output_2rows.csv"
OUTPUT_CSV     = _UNIHACK / "data" / "output" / "enriched_products.csv"

# Ground-truth MPNs — always processed first so the eval runs even with --limit
_GT_MPNS = {"PDSH4816AF", "WDTS7024RZ"}

# Placeholder values in brand columns that mean "no brand"
_BRAND_PLACEHOLDERS = {
    "-- unbranded --", "-- no unilog brand --", "-- no dib brand --",
    "commodity - unbranded", "", "nan",
}

# ── Output column spec (subset of the 252-column target we can credibly fill) ─
OUTPUT_COLS = [
    # Pass-through from input
    "Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf",
    # Enriched identity
    "MANUFACTURER_NAME", "BRAND_NAME", "MANUFACTURER_PART_NUMBER",
    # Taxonomy
    "Dept", "Class", "Fine", "Classpath",
    # Descriptions
    "Product Name", "MOBILE_DESC", "INVOICE_DESC", "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC",
    # Attributes (up to 10 triplets)
    *[f"ATTRIBUTE_LABEL_{i}" for i in range(1, 11)],
    *[f"ATTRIBUTE_VALUE_{i}" for i in range(1, 11)],
    *[f"ATTRIBUTE_UOM_{i}"   for i in range(1, 11)],
    # Pipeline metadata (prefixed _ so they're easy to strip for submission)
    "_classification_confidence", "_classification_method",
    "_enriched", "_enrichment_source",
    "_invoice_desc_ok", "_mobile_desc_ok",
]


# ── Per-row processing ────────────────────────────────────────────────────────

def _resolve_brand(row: dict) -> str:
    """Return first non-placeholder value from E1/Unilog/DIB brand columns."""
    for col in ("E1_Brand", "Unilog_Brand", "DIB_Brand"):
        val = (row.get(col) or "").strip().lower()
        if val not in _BRAND_PLACEHOLDERS:
            return row[col].strip()
    return ""


def process_row(row: dict, enrich: bool = True) -> dict:
    """
    Full enrichment pipeline for one input row.
    Returns a flat dict matching OUTPUT_COLS.
    """
    mpn        = (row.get("Mfg_Part_Num") or "").strip()
    part_desc  = (row.get("Part_Desc")    or "").strip()
    part_manuf = (row.get("Part_Manuf")   or "").strip()

    # 1. Manufacturer / brand normalization
    mfr = normalize_manufacturer(part_manuf)
    existing_brand = _resolve_brand(row)
    brand_name = existing_brand if existing_brand else mfr["brand_name"]

    # 2. Classification (rule-first, LLM fallback)
    clf = classify_product(part_desc, mpn)

    # 3. Web enrichment (optional)
    enrichment: dict = {
        "enriched": False, "source_url": None,
        "attributes": [], "series": None, "error": None,
    }
    if enrich and mfr["manufacturer_name"]:
        try:
            enrichment = enrich_from_manufacturer(
                mpn, mfr["manufacturer_name"], brand_name,
                clf.get("product_type", "")
            )
        except Exception as exc:
            enrichment["error"] = str(exc)

    # 4. Build DescriptionInput from what we know
    attrs_raw = [
        {"name": a.name, "value": a.value, "unit": a.unit or ""}
        for a in enrichment.get("attributes", [])
    ]

    inp = DescriptionInput(
        brand_name=brand_name,
        manufacturer_name=mfr["manufacturer_name"],
        mpn=mpn,
        product_type=clf.get("product_type", "Product"),
        series=enrichment.get("series") or "",
        attributes=attrs_raw,
    )

    # 5. Generate all five description types (pure template, no extra LLM call)
    descs = generate_descriptions(inp, use_llm=False)

    # 6. Assemble output row
    out: dict = {
        "Mfg_Part_Num": mpn,
        "Part_Desc": part_desc,
        "E1_Brand": row.get("E1_Brand", ""),
        "Unilog_Brand": row.get("Unilog_Brand", ""),
        "DIB_Brand": row.get("DIB_Brand", ""),
        "Part_Manuf": part_manuf,
        "MANUFACTURER_NAME": mfr["manufacturer_name"],
        "BRAND_NAME": brand_name,
        "MANUFACTURER_PART_NUMBER": mpn,
        "Dept": clf.get("Dept", ""),
        "Class": clf.get("Class", ""),
        "Fine": clf.get("Fine", ""),
        "Classpath": clf.get("Classpath", ""),
        "Product Name": clf.get("product_type", ""),
        "MOBILE_DESC": descs.mobile_desc,
        "INVOICE_DESC": descs.invoice_desc,
        "SHORT_DESC": descs.short_desc,
        "LONG_DESC1": descs.long_desc1,
        "RETAIL_DESC": descs.retail_desc,
        "_classification_confidence": clf.get("confidence", ""),
        "_classification_method": clf.get("method", ""),
        "_enriched": str(enrichment.get("enriched", False)),
        "_enrichment_source": enrichment.get("source_url") or "",
        "_invoice_desc_ok": str(descs.invoice_ok),
        "_mobile_desc_ok": str(descs.mobile_ok),
    }

    # Fill attribute triplets
    for i, attr in enumerate(attrs_raw[:10], 1):
        out[f"ATTRIBUTE_LABEL_{i}"] = attr.get("name", "")
        out[f"ATTRIBUTE_VALUE_{i}"] = attr.get("value", "")
        out[f"ATTRIBUTE_UOM_{i}"]   = normalize_unit(attr.get("unit", ""))

    return out


# ── Pipeline runner ───────────────────────────────────────────────────────────

def run_pipeline(
    limit: int | None = None,
    category_filter: str | None = None,
    enrich: bool = True,
    eval_only: bool = False,
) -> list[dict]:

    if not INPUT_CSV.exists():
        print(f"\nERROR: Input CSV not found at:\n  {INPUT_CSV}")
        print("\nPlease copy your files:")
        print(f"  Sample_1000_Items.csv       -> {INPUT_CSV}")
        print(f"  expected_output_2rows.csv   -> {GT_CSV}")
        return []

    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    print(f"Loaded {len(all_rows)} rows from {INPUT_CSV.name}")

    # Always process ground-truth rows first (needed for eval)
    gt_rows    = [r for r in all_rows if (r.get("Mfg_Part_Num") or "").strip() in _GT_MPNS]
    other_rows = [r for r in all_rows if (r.get("Mfg_Part_Num") or "").strip() not in _GT_MPNS]

    # Optional category keyword filter on the non-GT rows
    if category_filter:
        kw = category_filter.lower()
        other_rows = [
            r for r in other_rows
            if kw in (r.get("Part_Desc") or "").lower()
            or kw in (r.get("Part_Manuf") or "").lower()
        ]
        print(f"Category filter '{category_filter}': {len(other_rows)} rows match")

    if limit is not None:
        other_rows = other_rows[:limit]

    to_process = gt_rows + ([] if eval_only else other_rows)
    print(f"Processing {len(to_process)} rows "
          f"({len(gt_rows)} GT + {len(to_process) - len(gt_rows)} other)"
          + ("  [eval-only]" if eval_only else "")
          + ("  [no web enrichment]" if not enrich else ""))

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for i, row in enumerate(to_process):
        mpn = (row.get("Mfg_Part_Num") or "?").strip()
        desc_preview = (row.get("Part_Desc") or "")[:55]
        print(f"\n[{i+1}/{len(to_process)}] {mpn}  |  {desc_preview}")

        try:
            out = process_row(row, enrich=enrich)
            results.append(out)

            print(f"  Brand:   {out['BRAND_NAME'] or '(none)'}")
            print(f"  Class:   {out['Classpath']}  [{out['_classification_method']}]")
            if out["_enriched"] == "True":
                n_attrs = sum(1 for k in out if k.startswith("ATTRIBUTE_LABEL_") and out[k])
                print(f"  Enriched: YES — {n_attrs} attributes from {out['_enrichment_source'][:60]}")
            else:
                print(f"  Enriched: NO")
            print(f"  INVOICE: {out['INVOICE_DESC']}  [ok={out['_invoice_desc_ok']}]")
            print(f"  MOBILE:  {out['MOBILE_DESC']}  [ok={out['_mobile_desc_ok']}]")

        except Exception as exc:
            print(f"  ERROR: {exc}")

        # Polite delay to avoid hitting Groq rate limits
        if enrich and i < len(to_process) - 1:
            time.sleep(1.0)
        elif i < len(to_process) - 1:
            time.sleep(0.2)

    # Write output CSV
    if results:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        print(f"\nOutput saved: {OUTPUT_CSV}  ({len(results)} rows)")

    # ── Evaluation against ground truth ───────────────────────────────────────
    if GT_CSV.exists():
        gt = load_ground_truth(str(GT_CSV))
        gt_results = [r for r in results if r.get("Mfg_Part_Num", "") in _GT_MPNS]
        scores = [
            score_product(r["Mfg_Part_Num"], gt.get(r["Mfg_Part_Num"], {}), r)
            for r in gt_results
            if r.get("Mfg_Part_Num") in gt
        ]
        if scores:
            print_report(scores)
        elif gt_results:
            print("\n(Ground-truth MPNs processed but not found in GT CSV — check column names)")
        else:
            print("\n(No GT rows in this run — run without --category or add GT MPNs to filter)")
    else:
        print(f"\n(Skipping eval — GT CSV not found at {GT_CSV})")

    # ── Catalog-wide stats ────────────────────────────────────────────────────
    if results:
        n = len(results)
        misc_path = "Hardware>General Hardware>Miscellaneous"
        classified   = sum(1 for r in results if r.get("Classpath", "") != misc_path)
        brand_ok     = sum(1 for r in results if r.get("BRAND_NAME", ""))
        enriched     = sum(1 for r in results if r.get("_enriched") == "True")
        invoice_pass = sum(1 for r in results if r.get("_invoice_desc_ok") == "True")
        mobile_pass  = sum(1 for r in results if r.get("_mobile_desc_ok") == "True")

        print("\n── Catalog-wide stats ──────────────────────────────────")
        print(f"  Rows processed:         {n}")
        print(f"  Classified (non-misc):  {classified}/{n}  ({classified/n*100:.0f}%)")
        print(f"  Brand resolved:         {brand_ok}/{n}  ({brand_ok/n*100:.0f}%)")
        print(f"  Web-enriched:           {enriched}/{n}  ({enriched/n*100:.0f}%)")
        print(f"  INVOICE_DESC pass:      {invoice_pass}/{n}  ({invoice_pass/n*100:.0f}%)")
        print(f"  MOBILE_DESC pass:       {mobile_pass}/{n}  ({mobile_pass/n*100:.0f}%)")
        print("────────────────────────────────────────────────────────")

    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Unihack product enrichment pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m unihack.unihack_pipeline --eval-only
  python -m unihack.unihack_pipeline --limit 5 --no-enrich
  python -m unihack.unihack_pipeline --limit 20 --category impact
  python -m unihack.unihack_pipeline --limit 20 --category drill --no-enrich
        """,
    )
    parser.add_argument("--limit",      type=int,  default=None, help="Max non-GT rows to process")
    parser.add_argument("--category",   type=str,  default=None, help="Keyword filter on Part_Desc / Part_Manuf")
    parser.add_argument("--no-enrich",  action="store_true",     help="Skip web enrichment (faster)")
    parser.add_argument("--eval-only",  action="store_true",     help="Only run the 2 ground-truth rows")
    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        category_filter=args.category,
        enrich=not args.no_enrich,
        eval_only=args.eval_only,
    )
