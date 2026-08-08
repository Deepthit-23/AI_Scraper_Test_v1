"""
Generic product page scraper.

Design choice: we do NOT write per-site CSS selectors (e.g. "price is in div.price").
Those break the moment you point the scraper at a different manufacturer's site,
and industrial catalogs come from hundreds of different vendors.

Instead:
  1. Fetch the raw HTML
  2. Strip out navigation, ads, scripts, footers -- keep only the "main content"
     (this is what trafilatura is good at -- same tech used by read-it-later apps)
  3. Hand the cleaned TEXT to the AI extraction stage (see extractor/llm_extractor.py)
     which understands it regardless of layout.

This means one scraper works across almost any manufacturer site, which directly
supports the "scale across large catalogs" requirement.

NOTE ON JS-HEAVY SITES:
Some sites (Cloudflare-protected, React-rendered) won't return real content to a
plain HTTP request. For those, swap fetch_raw_html() to use Playwright
(render the page in a real headless browser first). A stub for that is included
below -- uncomment/install playwright if you need it.
"""

import requests
import urllib3
import trafilatura
from dataclasses import dataclass
from typing import Optional

# Windows often can't verify certain site certificates (corporate CAs / missing root certs).
# Disable verification for scraping; this is acceptable for read-only data collection.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    # Identify as a normal browser. Still be a good citizen: add delays between
    # requests, respect robots.txt, and don't hammer a site in a hackathon demo loop.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class ScrapedPage:
    url: str
    raw_html: str
    clean_text: str
    title: Optional[str]
    success: bool
    error: Optional[str] = None


def fetch_raw_html(url: str, timeout: int = 15) -> str:
    """Plain HTTP fetch. Works for most static/server-rendered product pages."""
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, verify=False)
    resp.raise_for_status()
    # Force UTF-8: requests often guesses Latin-1 for sites that don't declare charset,
    # which double-encodes characters like ° (U+00B0) into Â° garbage.
    resp.encoding = "utf-8"
    return resp.text


def fetch_raw_html_with_browser(url: str, timeout_ms: int = 20000) -> str:
    """
    Fallback for JS-rendered pages (React/Vue storefronts).
    Requires: pip install playwright && playwright install chromium
    Only use this when fetch_raw_html() comes back mostly empty --
    it's much slower, so don't use it by default for every page.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, timeout=timeout_ms)
        page.wait_for_load_state("networkidle")
        html = page.content()
        browser.close()
        return html


def clean_html(raw_html: str) -> tuple[Optional[str], Optional[str]]:
    """Returns (clean_text, title). Strips nav/ads/scripts, keeps main content."""
    extracted = trafilatura.extract(
        raw_html,
        include_tables=True,
        include_links=False,
        favor_recall=True,  # for product specs, better to keep slightly too much than lose data
    )
    metadata = trafilatura.extract_metadata(raw_html)
    title = metadata.title if metadata else None
    return extracted, title


def scrape_product_page(url: str, use_browser_fallback: bool = False) -> ScrapedPage:
    """Main entry point: give it a URL, get back cleaned product page content."""
    try:
        raw_html = fetch_raw_html(url)
        clean_text, title = clean_html(raw_html)

        # If plain fetch got almost nothing useful, the page is probably JS-rendered
        if (not clean_text or len(clean_text) < 200) and use_browser_fallback:
            raw_html = fetch_raw_html_with_browser(url)
            clean_text, title = clean_html(raw_html)

        if not clean_text:
            return ScrapedPage(url, raw_html, "", title, success=False,
                                error="Could not extract main content (page may need JS rendering)")

        return ScrapedPage(url, raw_html, clean_text, title, success=True)

    except requests.exceptions.RequestException as e:
        return ScrapedPage(url, "", "", None, success=False, error=str(e))


if __name__ == "__main__":
    # Quick manual test -- run this file directly on your own machine:
    #   python web_scraper.py
    test_url = "https://in.omega.com/pptst/SA1.html"
    result = scrape_product_page(test_url)
    if result.success:
        print(f"Title: {result.title}")
        print(f"Extracted {len(result.clean_text)} characters of clean content:\n")
        print(result.clean_text[:800])
    else:
        print(f"Failed: {result.error}")
