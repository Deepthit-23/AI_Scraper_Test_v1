"""
PDF spec-sheet discovery utilities.

Used by manufacturer_finder.py after a page passes all quality gates:
1. Scan the raw HTML for candidate PDF links.
2. Download each candidate to a temp file.
3. Caller passes the temp path to pdf_ingest.pdf_to_clean_text().
"""

import os
import tempfile
import requests
import urllib3
from urllib.parse import urljoin
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LINK_TEXT_KEYWORDS: frozenset[str] = frozenset([
    "datasheet", "data sheet", "spec sheet", "specification",
    "technical data", "download pdf", "product spec",
])

# Signals that a PDF is a warranty card or installation manual, not a spec sheet.
_REJECT_SIGNALS: frozenset[str] = frozenset([
    "limited warranty", "warranty card", "warranty registration",
    "installation guide", "installation instructions", "installation checklist",
    "installation manual", "owner's manual", "owners manual",
    "user manual", "how to install", "delivery checklist",
    "preparation checklist", "preparing for installation",
])

# Signals that confirm genuine technical spec content.
_SPEC_SIGNALS: frozenset[str] = frozenset([
    "watt", "volt", "amp", "lumen", "candela", "kelvin",
    "dimension", "capacity", "weight", "temperature",
    "efficacy", "cri", "color rendering", "ip rating",
    "horsepower", "rpm", "torque", "flow rate",
    "frequency", "hertz", "ohm", "gauge", "pressure",
])


def discover_pdf_links(html: str, base_url: str) -> list[str]:
    """
    Return absolute PDF URLs from <a> tags where:
      - href ends in .pdf (or contains .pdf?), OR
      - link text contains a spec-sheet keyword.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        link_text = a.get_text(strip=True).lower()
        href_lower = href.lower()

        is_pdf_href = ".pdf" in href_lower
        is_spec_link = any(kw in link_text for kw in _LINK_TEXT_KEYWORDS)

        if not (is_pdf_href or is_spec_link):
            continue

        abs_url = urljoin(base_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        found.append(abs_url)

    return found


def is_pdf_spec_sheet(text: str) -> bool:
    """
    Return True if the extracted PDF text looks like a spec sheet.
    Rejects warranty cards and installation manuals.
    """
    lower = text.lower()
    reject_hits = sum(1 for sig in _REJECT_SIGNALS if sig in lower)
    spec_hits = sum(1 for sig in _SPEC_SIGNALS if sig in lower)

    if reject_hits >= 2 and spec_hits == 0:
        return False
    if reject_hits >= 3:
        return False
    return True


def fetch_pdf_to_tempfile(
    pdf_url: str,
    headers: dict | None = None,
    timeout: tuple[int, int] = (5, 30),
) -> str | None:
    """
    Download a PDF URL to a temporary file.
    Returns the path to the temp file, or None on failure.
    Caller is responsible for deleting the file.
    """
    try:
        resp = requests.get(
            pdf_url,
            headers=headers or {},
            timeout=timeout,
            verify=False,
            stream=True,
        )
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("Content-Type", "")
        # Accept if content-type says PDF, or URL clearly ends in .pdf
        if "pdf" not in content_type.lower() and ".pdf" not in pdf_url.lower():
            return None

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return tmp_path
    except Exception:
        return None
