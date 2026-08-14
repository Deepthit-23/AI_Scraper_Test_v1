"""
ScraperAPI Stage 3 — targeted test against untemplated brands.

Tests Stage 3 (ScraperAPI) against brands where Stage 1 (no direct URL
template) and Stage 2 (DDG disabled in production) both produce nothing,
to determine whether ScraperAPI is a viable enrichment path before wiring
it into the full 200-row eval.

Does NOT run the full eval.

Usage:
    python -m unihack.test_scraperapi

Requires SCRAPERAPI_KEY in .env.
Credit budget: 1 credit per row, plus free DDG calls for URL discovery.
Maximum cost for this script: ~3 credits.
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()

from unihack.enrichment.manufacturer_finder import (
    _scraperapi_fetch,
    _scraperapi_stage3,
    get_scraperapi_stats,
    _ddg_search,
    _BRAND_KEY_MAP,
    _BRAND_DOMAINS,
)

# ── Test cases ────────────────────────────────────────────────────────────────
# Each entry: (label, mpn, manufacturer_name, brand_name, known_url)
#
# known_url is provided directly here, bypassing DDG URL-discovery.
# DDG returned zero_results for all three brands in the previous run —
# it doesn't index these specific product MPNs at their domains.
# Providing known_url isolates ScraperAPI's actual fetch + render capability
# from the separate URL-discovery problem.
TEST_CASES = [
    # Leviton GFCI outlet — standard {brand}/products/{sku} pattern
    (
        "leviton.com",
        "R00-GFNT1-00K",
        "Leviton",
        "Leviton®",
        "https://www.leviton.com/en/products/R00-GFNT1-00K",
    ),
    # Southwire 4" square box cover — try their product-number URL pattern
    (
        "southwire.com",
        "G1941-UPC",
        "Southwire Company, LLC",
        "Southwire®",
        "https://www.southwire.com/G1941-UPC",
    ),
    # Oliver Machinery 13" benchtop planer — their dot-notation SKUs
    (
        "olivermachinery.net",
        "10045.201",
        "Oliver Machinery Company",
        "Oliver Machinery",
        "https://www.olivermachinery.net/product/10045.201/",
    ),
]


def _bar(char: str = "─", width: int = 66) -> str:
    return char * width


def run_tests() -> None:
    api_key = os.environ.get("SCRAPERAPI_KEY")
    if not api_key:
        print("ERROR: SCRAPERAPI_KEY not set in .env — cannot run ScraperAPI tests.")
        sys.exit(1)

    print(_bar("═"))
    print("ScraperAPI Stage 3 — targeted domain test")
    print(f"  API key prefix: {api_key[:8]}...")
    print(_bar("═"))
    print()

    results = []

    for label, mpn, manufacturer_name, brand_name, known_url in TEST_CASES:
        print(_bar())
        print(f"  TEST: {label}  |  MPN={mpn}")
        print(f"  URL:  {known_url}  (provided directly; skipping DDG)")
        print(_bar())

        t0 = time.monotonic()
        clean_text, url = _scraperapi_stage3(
            mpn=mpn,
            manufacturer_name=manufacturer_name,
            brand_name=brand_name,
            known_url=known_url,   # bypass DDG; tests ScraperAPI fetch directly
            verbose=True,
        )
        elapsed = time.monotonic() - t0

        stats = get_scraperapi_stats()
        success = clean_text is not None and len(clean_text) >= 100

        results.append({
            "label":    label,
            "mpn":      mpn,
            "success":  success,
            "url":      url,
            "chars":    len(clean_text) if clean_text else 0,
            "elapsed":  elapsed,
            "credits":  stats["credits"],
        })

        if success:
            preview = clean_text[:200].replace("\n", " ")
            print(f"  RESULT: SUCCESS — {len(clean_text):,} chars in {elapsed:.1f}s")
            print(f"  URL:    {url}")
            print(f"  TEXT:   {preview}…")
        else:
            print(f"  RESULT: FAILED — no usable content in {elapsed:.1f}s")
            if url:
                print(f"  URL:    {url} (fetched but content too sparse)")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    final_stats = get_scraperapi_stats()
    print(_bar("═"))
    print("SUMMARY")
    print(_bar("═"))
    print(f"  {'Domain / label':<45} {'OK?':<6} {'Chars':>7}  {'Time':>6}  URL")
    print(f"  {_bar('-', 44)} {_bar('-', 5)} {_bar('-', 7)}  {_bar('-', 6)}  {_bar('-', 20)}")
    for r in results:
        ok = "YES" if r["success"] else "NO"
        url_short = (r["url"] or "")[:50]
        print(
            f"  {r['label']:<45} {ok:<6} {r['chars']:>7,}  {r['elapsed']:>5.1f}s  {url_short}"
        )
    print(_bar())
    print(
        f"  Total ScraperAPI calls: {final_stats['calls']}  "
        f"credits used this session: {final_stats['credits']}"
    )
    print(_bar("═"))


if __name__ == "__main__":
    run_tests()
