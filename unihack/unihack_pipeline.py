"""
Unihack product enrichment pipeline.

Orchestrates: normalize -> classify -> enrich (web scrape) -> generate descriptions -> save CSV.

Usage:
    # Fast baseline on the real 200-row eval set (no web enrichment):
    python -m unihack.unihack_pipeline --eval-full --no-enrich

    # Full 200-row eval with web enrichment (slow, ~15-30 min):
    python -m unihack.unihack_pipeline --eval-full

    # Quick 2-row sanity check (legacy):
    python -m unihack.unihack_pipeline --eval-mini
    python -m unihack.unihack_pipeline --eval-only    # alias for --eval-mini

    # Ad-hoc runs on the main 1000-row input:
    python -m unihack.unihack_pipeline --limit 5 --no-enrich
    python -m unihack.unihack_pipeline --limit 20 --category drill

Input files:
    unihack/data/input/Sample_1000_Items.csv
    unihack/data/ground_truth/input_200rows.csv           (--eval-full input)
    unihack/data/ground_truth/expected_output_200rows.csv (--eval-full scoring target)
    unihack/data/ground_truth/expected_output_2rows.csv   (--eval-mini scoring target)

Output:
    unihack/data/output/enriched_products.csv    (ad-hoc / eval-mini runs)
    unihack/data/output/enriched_200rows.csv     (--eval-full runs)
"""

import os
import sys
import csv
import time
import argparse
from pathlib import Path

# Force UTF-8 on Windows (cp1252 default can't encode box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Path setup (makes product-intel/ the Python root) ────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from unihack import llm_cache
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

# 200-row real eval set (separate input+output pair)
INPUT_200_CSV  = _UNIHACK / "data" / "ground_truth" / "input_200rows.csv"
GT_200_CSV     = _UNIHACK / "data" / "ground_truth" / "expected_output_200rows.csv"
OUTPUT_200_CSV = _UNIHACK / "data" / "output" / "enriched_200rows.csv"

# 2-row mini eval MPNs — always processed first in normal runs
_GT_MPNS = {"PDSH4816AF", "WDTS7024RZ"}

# Verbose enrichment debug for these MPNs (display-only floor models)
_VERBOSE_MPNS = {"PDSH4816AF", "WDTS7024RZ"}

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
    "_brand_resolution_method",
    "_enriched", "_enrichment_source", "_source_tier", "_exact_mpn_verified",
    "_enrichment_error",
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
    # Resolve brand from input columns FIRST so it can seed the canonical lookup
    # when Part_Manuf is a co-op / distributor rather than the real product maker.
    existing_brand = _resolve_brand(row)
    mfr = normalize_manufacturer(
        part_manuf, part_desc=part_desc, mpn=mpn, existing_brand=existing_brand
    )
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
            _verbose_enrich = mpn in _VERBOSE_MPNS
            enrichment = enrich_from_manufacturer(
                mpn, mfr["manufacturer_name"], brand_name,
                clf.get("product_type", ""),
                part_desc=part_desc,
                verbose=_verbose_enrich,
            )
        except Exception as exc:
            enrichment["error"] = str(exc)

    # 4. Build DescriptionInput from what we know
    attrs_raw = [
        {"name": a.name, "value": a.value, "unit": a.unit or ""}
        for a in enrichment.get("attributes", [])
    ]

    # Infer capacity unit for appliances when source page omits it (e.g. Speed Queen
    # pages show bare "7.0" with no "cu ft" label anywhere in the scraped text).
    _pt_lower = clf.get("product_type", "").lower()
    if any(k in _pt_lower for k in ("dryer", "washer", "refrigerator", "freezer")):
        for _a in attrs_raw:
            if "capacity" in _a["name"].lower() and not _a["unit"]:
                try:
                    _v = float(_a["value"].replace(",", "").strip())
                    _a["unit"] = "cu ft" if _v <= 30 else "lb"
                except (ValueError, TypeError):
                    pass

    inp = DescriptionInput(
        brand_name=brand_name,
        manufacturer_name=mfr["manufacturer_name"],
        mpn=mpn,
        product_type=clf.get("product_type", "Product"),
        series=enrichment.get("series") or "",
        attributes=attrs_raw,
        classpath=clf.get("Classpath", ""),
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
        "_brand_resolution_method": mfr.get("_brand_resolution_method", "unknown"),
        "_enriched": str(enrichment.get("enriched", False)),
        "_enrichment_source": enrichment.get("source_url") or "",
        "_source_tier": enrichment.get("source_tier") or "",
        "_exact_mpn_verified": str(enrichment.get("exact_mpn_verified", "")) if enrichment.get("enriched") else "",
        "_enrichment_error": enrichment.get("error") or "",
        "_invoice_desc_ok": str(descs.invoice_ok),
        "_mobile_desc_ok": str(descs.mobile_ok),
    }

    # Fill attribute triplets
    for i, attr in enumerate(attrs_raw[:10], 1):
        out[f"ATTRIBUTE_LABEL_{i}"] = attr.get("name", "")
        out[f"ATTRIBUTE_VALUE_{i}"] = attr.get("value", "")
        out[f"ATTRIBUTE_UOM_{i}"]   = normalize_unit(attr.get("unit", ""))

    return out


# ── Shared helpers ────────────────────────────────────────────────────────────

def _print_row_summary(out: dict) -> None:
    print(f"  Mfr:     {out['MANUFACTURER_NAME'] or '(none)'}  [{out['_brand_resolution_method']}]")
    print(f"  Brand:   {out['BRAND_NAME'] or '(none)'}")
    print(f"  Class:   {out['Classpath']}  [{out['_classification_method']}]")
    if out["_enriched"] == "True":
        n_attrs = sum(1 for k in out if k.startswith("ATTRIBUTE_LABEL_") and out[k])
        print(f"  Enriched: YES — {n_attrs} attrs from {out['_enrichment_source'][:60]}")
    else:
        err = out.get("_enrichment_error") or ""
        print(f"  Enriched: NO" + (f"  [{err[:80]}]" if err else ""))
    print(f"  INVOICE: {out['INVOICE_DESC']}  [ok={out['_invoice_desc_ok']}]")
    print(f"  MOBILE:  {out['MOBILE_DESC']}  [ok={out['_mobile_desc_ok']}]")


def _print_run_stats(results: list[dict], label: str = "") -> None:
    n = len(results)
    if not n:
        return
    misc_path = "Hardware>General Hardware>Miscellaneous"
    classified   = sum(1 for r in results if r.get("Classpath", "") != misc_path)
    brand_ok     = sum(1 for r in results if r.get("BRAND_NAME", ""))
    enriched     = sum(1 for r in results if r.get("_enriched") == "True")
    invoice_pass = sum(1 for r in results if r.get("_invoice_desc_ok") == "True")
    mobile_pass  = sum(1 for r in results if r.get("_mobile_desc_ok") == "True")

    hdr = f"── This-run summary ({n} rows{', ' + label if label else ''}) "
    print(f"\n{hdr}{'─' * max(0, 56 - len(hdr))}")
    print(f"  Classified (non-misc):  {classified}/{n}  ({classified/n*100:.0f}%)")
    print(f"  Brand resolved:         {brand_ok}/{n}  ({brand_ok/n*100:.0f}%)")
    print(f"  Web-enriched:           {enriched}/{n}  ({enriched/n*100:.0f}%)")
    print(f"  INVOICE_DESC pass:      {invoice_pass}/{n}  ({invoice_pass/n*100:.0f}%)")
    print(f"  MOBILE_DESC pass:       {mobile_pass}/{n}  ({mobile_pass/n*100:.0f}%)")
    print("─" * 56)


def _write_output(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"\nOutput saved: {path}  ({len(results)} rows)")


def _process_rows(
    rows: list[dict],
    enrich: bool,
    label: str = "",
) -> list[dict]:
    """Process a list of input rows through the full pipeline. Returns output dicts."""
    results: list[dict] = []
    n = len(rows)

    for i, row in enumerate(rows):
        mpn = (row.get("Mfg_Part_Num") or "?").strip()
        desc_preview = (row.get("Part_Desc") or "")[:55]
        print(f"\n[{i+1}/{n}] {mpn}  |  {desc_preview}")

        try:
            out = process_row(row, enrich=enrich)
            results.append(out)
            _print_row_summary(out)
        except Exception as exc:
            print(f"  ERROR: {exc}")

        delay = 1.0 if enrich else 0.1
        if i < n - 1:
            time.sleep(delay)

    return results


# ── Pipeline runners ──────────────────────────────────────────────────────────

def run_eval_full(enrich: bool = True, limit: int | None = None) -> list[dict]:
    """
    Process all 200 rows from input_200rows.csv and score against
    expected_output_200rows.csv.  Output goes to enriched_200rows.csv.
    """
    if not INPUT_200_CSV.exists():
        print(f"\nERROR: 200-row input not found at:\n  {INPUT_200_CSV}")
        return []

    with open(INPUT_200_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if limit is not None:
        rows = rows[:limit]
        print(f"Loaded {limit} rows (of 200) from {INPUT_200_CSV.name}  [--limit {limit}]")
    else:
        print(f"Loaded {len(rows)} rows from {INPUT_200_CSV.name}")
    enrich_flag = "no web enrichment" if not enrich else "with web enrichment"
    print(f"Mode: --eval-full  [{enrich_flag}]")

    llm_cache.reset_stats()
    results = _process_rows(rows, enrich=enrich, label="eval-full")
    if results:
        _write_output(results, OUTPUT_200_CSV)
        _print_run_stats(results, label="eval-full")

    # Score against 200-row ground truth
    if GT_200_CSV.exists():
        gt = load_ground_truth(str(GT_200_CSV))
        scored = [
            score_product(r["Mfg_Part_Num"], gt.get(r["Mfg_Part_Num"], {}), r)
            for r in results
            if r.get("Mfg_Part_Num") in gt
        ]
        if scored:
            print_report(scored)
        else:
            print("\n(No results matched GT MPNs — check Mfg_Part_Num column in input file)")
    else:
        print(f"\n(Skipping eval — GT file not found at {GT_200_CSV})")

    stats = llm_cache.get_stats()
    n_rows = len(results)
    print(f"\n── Groq usage this run ──────────────────────────────────────────")
    print(f"  Rows processed : {n_rows}")
    print(f"  LLM calls      : {stats['calls']}")
    print(f"  Tokens used    : {stats['tokens']:,}")
    if n_rows and stats['calls']:
        print(f"  Tokens/row     : {stats['tokens'] / n_rows:.0f}  |  tokens/call: {stats['tokens'] / stats['calls']:.0f}")
    if n_rows and limit is None:
        pass  # full run, no extrapolation needed
    elif n_rows and limit is not None:
        est_total = int(stats['tokens'] / n_rows * 200)
        print(f"  Extrapolated 200-row total : ~{est_total:,} tokens")
    print(f"────────────────────────────────────────────────────────────────")

    return results


def run_eval_mini(enrich: bool = True) -> list[dict]:
    """
    Process the 2 legacy ground-truth rows from Sample_1000_Items.csv.
    Scores against expected_output_2rows.csv.  Output appended to enriched_products.csv.
    """
    if not INPUT_CSV.exists():
        print(f"\nERROR: Input CSV not found at:\n  {INPUT_CSV}")
        return []

    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    gt_rows = [r for r in all_rows if (r.get("Mfg_Part_Num") or "").strip() in _GT_MPNS]
    if not gt_rows:
        print(f"\nERROR: GT MPNs {_GT_MPNS} not found in {INPUT_CSV.name}")
        return []

    print(f"Loaded {len(gt_rows)} GT rows from {INPUT_CSV.name}  [--eval-mini]")
    results = _process_rows(gt_rows, enrich=enrich, label="eval-mini")

    if results:
        _write_output(results, OUTPUT_CSV)
        _print_run_stats(results, label="eval-mini")

    if GT_CSV.exists():
        gt = load_ground_truth(str(GT_CSV))
        scored = [
            score_product(r["Mfg_Part_Num"], gt.get(r["Mfg_Part_Num"], {}), r)
            for r in results
            if r.get("Mfg_Part_Num") in gt
        ]
        if scored:
            print_report(scored)
    else:
        print(f"\n(Skipping eval — GT CSV not found at {GT_CSV})")

    return results


def run_pipeline(
    limit: int | None = None,
    category_filter: str | None = None,
    enrich: bool = True,
    eval_only: bool = False,   # legacy alias → eval_mini
    eval_mini: bool = False,
    eval_full: bool = False,
) -> list[dict]:
    """
    Main entry point.  Routes to the right sub-runner based on flags.
    """
    # ── Eval routing ──────────────────────────────────────────────────────────
    if eval_full:
        return run_eval_full(enrich=enrich, limit=limit)

    if eval_mini or eval_only:
        return run_eval_mini(enrich=enrich)

    # ── Normal ad-hoc run on Sample_1000_Items.csv ───────────────────────────
    if not INPUT_CSV.exists():
        print(f"\nERROR: Input CSV not found at:\n  {INPUT_CSV}")
        return []

    with open(INPUT_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    print(f"Loaded {len(all_rows)} rows from {INPUT_CSV.name}")

    # Always process GT rows first so mini-eval is embedded in every run
    gt_rows    = [r for r in all_rows if (r.get("Mfg_Part_Num") or "").strip() in _GT_MPNS]
    other_rows = [r for r in all_rows if (r.get("Mfg_Part_Num") or "").strip() not in _GT_MPNS]

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

    to_process = gt_rows + other_rows
    enrich_flag = "[no web enrichment]" if not enrich else ""
    print(f"Processing {len(to_process)} rows "
          f"({len(gt_rows)} GT + {len(other_rows)} other)  {enrich_flag}")

    results = _process_rows(to_process, enrich=enrich)
    if results:
        _write_output(results, OUTPUT_CSV)
        _print_run_stats(results)

    # Mini-eval against 2-row GT
    if GT_CSV.exists():
        gt = load_ground_truth(str(GT_CSV))
        gt_results = [r for r in results if r.get("Mfg_Part_Num", "") in _GT_MPNS]
        scored = [
            score_product(r["Mfg_Part_Num"], gt.get(r["Mfg_Part_Num"], {}), r)
            for r in gt_results
            if r.get("Mfg_Part_Num") in gt
        ]
        if scored:
            print_report(scored)

    return results


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Unihack product enrichment pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m unihack.unihack_pipeline --eval-full --no-enrich   # fast 200-row baseline
  python -m unihack.unihack_pipeline --eval-full               # full 200-row eval (slow)
  python -m unihack.unihack_pipeline --eval-mini               # 2-row sanity check
  python -m unihack.unihack_pipeline --eval-only               # alias for --eval-mini
  python -m unihack.unihack_pipeline --limit 5 --no-enrich
  python -m unihack.unihack_pipeline --limit 20 --category impact
        """,
    )
    parser.add_argument("--limit",      type=int,  default=None, help="Max non-GT rows (ad-hoc runs)")
    parser.add_argument("--category",   type=str,  default=None, help="Keyword filter on Part_Desc / Part_Manuf")
    parser.add_argument("--no-enrich",  action="store_true",     help="Skip web enrichment (fast mode)")

    eval_group = parser.add_mutually_exclusive_group()
    eval_group.add_argument("--eval-full", action="store_true",
                            help="Run all 200 rows from input_200rows.csv and score against GT")
    eval_group.add_argument("--eval-mini", action="store_true",
                            help="Run the 2 legacy GT rows only (quick sanity check)")
    eval_group.add_argument("--eval-only", action="store_true",
                            help="Alias for --eval-mini (legacy)")

    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        category_filter=args.category,
        enrich=not args.no_enrich,
        eval_only=args.eval_only,
        eval_mini=args.eval_mini,
        eval_full=args.eval_full,
    )
