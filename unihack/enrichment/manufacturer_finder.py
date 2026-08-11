"""
Manufacturer web enrichment.

Challenge sourcing rule: use the manufacturer's OWN website, not marketplaces.

Two-stage lookup:
  1. Try a direct URL from our domain + URL-pattern table for the top ~15 brands.
     A HEAD request confirms the page exists before we spend a full scrape + LLM call.
  2. Fall back to DuckDuckGo HTML search scoped to the manufacturer's domain.
     No API key required — uses the public HTML endpoint. Results are filtered
     to reject known marketplace/distributor URLs.

The enrichment result feeds directly into the existing extract_product() pipeline
(scraper/web_scraper.py + extractor/llm_extractor.py) — no code duplication.

One LLM call per product (the attribute extraction call inside extract_product).
"""

import os
import sys
import re
import time
import requests
from pathlib import Path
from bs4 import BeautifulSoup

# Ensure we can import from the product-intel root
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from scraper.web_scraper import scrape_product_page
from extractor.llm_extractor import extract_product

# ── Manufacturer URL table ────────────────────────────────────────────────────

# For each brand we know: the canonical domain and a URL template to try directly.
# {mpn} = the raw MPN string, {mpn_lower} = lowercased MPN.
# product_url=None means "no predictable direct URL; go straight to search".
_BRAND_DOMAINS: dict[str, dict] = {
    "dewalt": {
        "domain": "dewalt.com",
        "product_url": "https://www.dewalt.com/product/{mpn_lower}/",
    },
    "milwaukee": {
        "domain": "milwaukeetool.com",
        "product_url": "https://www.milwaukeetool.com/Products/{mpn}",
    },
    "makita": {
        "domain": "makitatools.com",
        "product_url": "https://www.makitatools.com/products/details/{mpn}",
    },
    "festool": {
        "domain": "festool.com",
        "product_url": None,
    },
    "diablo": {
        "domain": "diablotools.com",
        "product_url": "https://www.diablotools.com/products/{mpn_lower}",
    },
    "frigidaire": {
        "domain": "frigidaire.com",
        "product_url": None,
    },
    "whirlpool": {
        "domain": "whirlpool.com",
        "product_url": None,
    },
    "kichler": {
        "domain": "kichler.com",
        "product_url": None,
    },
    "philips": {
        "domain": "lighting.philips.com",
        "product_url": None,
    },
    "satco": {
        "domain": "satco.com",
        "product_url": None,
    },
    "leviton": {
        "domain": "leviton.com",
        "product_url": None,
    },
    "3m": {
        "domain": "3m.com",
        "product_url": None,
    },
    "southwire": {
        "domain": "southwire.com",
        "product_url": None,
    },
}

# Brand name -> domain key mapping (strips ® / ™ symbols)
_BRAND_KEY_MAP: dict[str, str] = {
    "dewalt": "dewalt", "dewalt®": "dewalt",
    "milwaukee": "milwaukee", "milwaukee®": "milwaukee",
    "makita": "makita", "makita®": "makita",
    "festool": "festool", "festool®": "festool",
    "diablo": "diablo", "diablo®": "diablo",
    "frigidaire": "frigidaire", "frigidaire®": "frigidaire",
    "whirlpool": "whirlpool", "whirlpool®": "whirlpool",
    "kichler": "kichler", "kichler®": "kichler",
    "philips": "philips", "philips®": "philips",
    "satco": "satco", "satco®": "satco",
    "leviton": "leviton", "leviton®": "leviton",
    "3m": "3m", "3m™": "3m",
    "southwire": "southwire", "southwire®": "southwire",
}

_MARKETPLACE_DOMAINS = {
    "amazon", "ebay", "walmart", "homedepot", "lowes", "grainger",
    "mcmaster", "zoro", "wayfair", "target", "bestbuy", "costco",
    "overstock", "sears", "menards", "acehardware", "truevalue",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _is_marketplace(url: str) -> bool:
    return any(m in url.lower() for m in _MARKETPLACE_DOMAINS)


def _ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """
    DuckDuckGo HTML endpoint search (no API key, no rate limit contract).
    Returns list of {title, url}.
    """
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=_HEADERS,
            verify=False,
            timeout=15,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in soup.select(".result__a")[:max_results]:
            href = a.get("href", "")
            # DDG wraps URLs; extract the real one
            m = re.search(r"uddg=([^&]+)", href)
            url = requests.utils.unquote(m.group(1)) if m else href
            results.append({"title": a.get_text(strip=True), "url": url})
        return results
    except Exception:
        return []


def _try_direct_url(mpn: str, domain_key: str) -> str | None:
    """
    Try to fetch the product page at a known URL pattern.
    Returns the URL if the page exists (HTTP 200), else None.
    """
    entry = _BRAND_DOMAINS.get(domain_key, {})
    template = entry.get("product_url")
    if not template:
        return None

    url = template.format(mpn=mpn, mpn_lower=mpn.lower())
    try:
        resp = requests.head(
            url, headers=_HEADERS, verify=False, timeout=8, allow_redirects=True
        )
        if resp.status_code == 200:
            return url
    except Exception:
        pass
    return None


def find_manufacturer_page(mpn: str, manufacturer_name: str, brand_name: str) -> str | None:
    """
    Find the manufacturer's OWN official product page for this MPN.
    Returns URL or None.
    """
    brand_key = _BRAND_KEY_MAP.get(brand_name.lower().strip(), "")

    # Stage 1: direct URL
    if brand_key:
        direct = _try_direct_url(mpn, brand_key)
        if direct:
            return direct

    # Stage 2: DuckDuckGo search
    domain = _BRAND_DOMAINS.get(brand_key, {}).get("domain", "")
    if domain:
        query = f"site:{domain} {mpn} specifications"
    else:
        mfr_short = manufacturer_name.split(",")[0].strip()
        query = f"{mfr_short} {mpn} product specifications"

    results = _ddg_search(query)
    for r in results:
        url = r["url"]
        if _is_marketplace(url):
            continue
        if domain and domain in url:
            return url
        # Accept if the brand key appears in the domain
        if brand_key and brand_key.replace(" ", "") in url.lower():
            return url

    return None


def enrich_from_manufacturer(
    mpn: str,
    manufacturer_name: str,
    brand_name: str,
    product_type: str = "",
) -> dict:
    """
    Full enrichment for one product:
      1. Find manufacturer page
      2. Scrape it (reuse scraper/web_scraper.py)
      3. Extract attributes (reuse extractor/llm_extractor.py)

    Returns:
        {enriched, source_url, attributes, series, product_record, error}

    enriched=False means we tried but failed; caller should proceed without
    enrichment rather than raising.
    """
    result: dict = {
        "enriched": False,
        "source_url": None,
        "attributes": [],
        "series": None,
        "product_record": None,
        "error": None,
    }

    url = find_manufacturer_page(mpn, manufacturer_name, brand_name)
    if not url:
        result["error"] = f"No manufacturer page found for {mpn} ({brand_name})"
        return result

    result["source_url"] = url

    page = scrape_product_page(url)
    if not page.success:
        result["error"] = f"Scrape failed: {page.error}"
        return result

    if len(page.clean_text) < 100:
        result["error"] = "Page text too short — likely JS-rendered or blocked"
        return result

    try:
        record = extract_product(page.clean_text, source_id=url)
        result["product_record"] = record
        result["attributes"] = record.attributes
        result["enriched"] = True

        # Pull series name out of extracted attributes if present
        for attr in record.attributes:
            if "series" in attr.name.lower():
                result["series"] = attr.value
                break
    except Exception as e:
        result["error"] = f"Extraction failed: {e}"

    return result
