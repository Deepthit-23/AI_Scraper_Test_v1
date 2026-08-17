"""
Manufacturer web enrichment.

Discovery stages:
  1. Direct URL template (fast, free, zero network if template exists).
  2. Tavily web search (replaces DDG; 1,000 free credits/month; regional TLD
     exclusions; returns scored results that Tavily has already fetched).
  2.5 MPN cache replay (free; checks llm_cache for a prior extraction).
  3. ScraperAPI last resort (costs credits; JS rendering; bypasses Cloudflare).

Source tiers
  Every attribute extracted from web enrichment is tagged with the tier of the
  page it came from:
    "manufacturer"  — the brand's own registered domain (frigidaire.com, etc.)
    "distributor"   — known B2B industrial supplier (MSC, Fastenal, Graybar…)
    "retailer"      — any other non-blocked source (AJ Madison, ABCWarehouse…)

Config flag
  ALLOW_RETAILER_SOURCES (below): when True, the highest-scoring Tavily result
  is used regardless of tier. When False, only manufacturer/distributor URLs are
  accepted; everything else falls through to "not enriched."
"""

import os
import sys
import re
import time
import requests
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ── Source policy config ──────────────────────────────────────────────────────
# Flip to False to restrict Stage 2 to manufacturer/distributor sources only.
ALLOW_RETAILER_SOURCES: bool = True

# Ensure we can import from the product-intel root
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from scraper.web_scraper import scrape_product_page
from extractor.llm_extractor import extract_product

# ── Request headers ───────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.google.com/",
}

# ── Speed Queen URL helper ────────────────────────────────────────────────────

def _speed_queen_url(mpn: str) -> str:
    """
    Map a Speed Queen MPN to its product page URL.
    Category determined by prefix (TV/TR = top-load washers) and trailing
    fuel letter (G = gas dryer, E or default = electric dryer).
    """
    prefix2 = mpn[:2].upper()
    last = mpn[-1].upper() if mpn else ""
    if prefix2 in ("TV", "TR"):
        slug = "top-load-washers"
    elif last == "G":
        slug = "gas-dryers"
    else:
        slug = "electric-dryers"
    return f"https://speedqueen.com/products/{slug}/{mpn.lower()}/"


# ── Manufacturer URL table ────────────────────────────────────────────────────

# For each brand we know: the canonical domain and either:
#   product_url  — a format string with {mpn} / {mpn_lower}
#   url_fn       — a callable(mpn) -> str for brands needing MPN-aware routing
#   product_url=None / url_fn=None means "no predictable direct URL; go to search"
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
    "speed_queen": {
        "domain": "speedqueen.com",
        "url_fn": _speed_queen_url,
    },
    # Cloudflare / bot-blocked: keep domain for DDG scoping, no direct URL
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
        "product_url": "https://www.satco.com/products/{mpn}",
    },
    "leviton": {
        "domain": "leviton.com",
        "product_url": "https://leviton.com/products/{mpn}",
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
    "speed queen": "speed_queen", "speed queen®": "speed_queen",
    "frigidaire": "frigidaire", "frigidaire®": "frigidaire",
    "whirlpool": "whirlpool", "whirlpool®": "whirlpool",
    "kichler": "kichler", "kichler®": "kichler",
    "philips": "philips", "philips®": "philips",
    "satco": "satco", "satco®": "satco", "nuvo® by satco": "satco", "nuvo by satco": "satco",
    "leviton": "leviton", "leviton®": "leviton",
    "3m": "3m", "3m™": "3m",
    "southwire": "southwire", "southwire®": "southwire",
}

# ── Per-domain rate-limit throttle ───────────────────────────────────────────
# Tracks the last request time per domain so consecutive hits to the SAME site
# get a short gap inserted. Requests to different domains are never delayed.
_DOMAIN_LAST_HIT: dict[str, float] = {}
_MIN_DOMAIN_GAP = 0.75   # seconds between consecutive requests to the same domain
_DDG_DOMAIN     = "html.duckduckgo.com"
_DDG_MIN_GAP    = 1.5    # DDG rate-limits aggressive bots; use a wider window


def _throttle(url: str) -> None:
    """Sleep if needed to respect per-domain rate limiting."""
    domain = urlparse(url).netloc or url
    now = time.monotonic()
    last = _DOMAIN_LAST_HIT.get(domain, 0.0)
    gap = now - last
    if gap < _MIN_DOMAIN_GAP:
        time.sleep(_MIN_DOMAIN_GAP - gap)
    _DOMAIN_LAST_HIT[domain] = time.monotonic()


# Domains confirmed to block DDG (Cloudflare-protected; 0% success rate in audit).
# These are ALWAYS skipped for DDG regardless of use_ddg flag.
_DDG_BLOCKED_DOMAINS = {
    "frigidaire.com",
    "whirlpool.com",
}


# ── ScraperAPI (Tier 3) ──────────────────────────────────────────────────────
# Stats reset each process; mirrors the llm_cache.record_usage() pattern.
_SCRAPERAPI_STATS: dict[str, int] = {"calls": 0, "credits": 0}


def _scraperapi_fetch(
    target_url: str,
    api_key: str,
    render: bool = True,
) -> tuple[str, int, str | None]:
    """
    Wrap target_url through ScraperAPI's endpoint to bypass Cloudflare,
    JS rendering, and CAPTCHA barriers that defeat plain requests.

    Free tier: 1,000 credits/month recurring.  1 call = 1 credit.
    Endpoint: http://api.scraperapi.com?api_key=KEY&url=TARGET&render=true
    Returns (html_text, http_status_code, error_or_none).
    """
    from urllib.parse import quote as _quote
    endpoint = (
        "http://api.scraperapi.com"
        f"?api_key={api_key}"
        f"&url={_quote(target_url, safe='')}"
        f"&render={'true' if render else 'false'}"
    )
    _throttle(target_url)   # rate-limit on the TARGET domain, not ScraperAPI's
    try:
        resp = requests.get(endpoint, timeout=(10, 25 if render else 45), verify=False)
        _SCRAPERAPI_STATS["calls"] += 1
        _SCRAPERAPI_STATS["credits"] += 1
        print(
            f"  [scraperapi] HTTP {resp.status_code}  "
            f"len={len(resp.text):,}  "
            f"credits_this_session={_SCRAPERAPI_STATS['credits']}"
        )
        if resp.status_code == 200:
            return resp.text, resp.status_code, None
        # Log up to 200 bytes of the error body — helps distinguish
        # malformed request (ScraperAPI error JSON) from target-site block
        body_preview = " ".join(resp.text[:200].split())
        print(f"  [scraperapi] response body: {body_preview}")
        return "", resp.status_code, f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        _SCRAPERAPI_STATS["calls"] += 1
        _SCRAPERAPI_STATS["credits"] += 1   # charged by ScraperAPI even on timeout
        print(f"  [scraperapi] TIMEOUT  credits_this_session={_SCRAPERAPI_STATS['credits']}")
        return "", 0, "timeout"
    except Exception as e:
        return "", 0, str(e)


def get_scraperapi_stats() -> dict[str, int]:
    """Return ScraperAPI credit/call usage for this session."""
    return dict(_SCRAPERAPI_STATS)


def _scraperapi_stage3(
    mpn: str,
    manufacturer_name: str,
    brand_name: str,
    known_url: str | None,
    verbose: bool = False,
) -> tuple[str | None, str | None]:
    """
    Stage 3: ScraperAPI last-resort enrichment.
    Only runs when SCRAPERAPI_KEY is set AND Stages 1+2 produced no clean text.

    If a URL was already found by Stage 1/2 but normal scraping failed,
    ScraperAPI re-fetches that same URL with JS rendering + proxy rotation.

    If no URL was found at all (e.g. frigidaire.com / whirlpool.com where DDG
    is blocked AND there is no direct URL template), runs DDG now — bypassing
    _DDG_BLOCKED_DOMAINS, since ScraperAPI can actually scrape the result.

    Returns (clean_text, url) or (None, None).
    """
    api_key = os.environ.get("SCRAPERAPI_KEY")
    if not api_key:
        return None, None   # key not configured — skip silently in production

    stage3_url = known_url

    # Discover URL via DDG if we don't have one yet (bypasses blocked-domain list)
    if not stage3_url:
        brand_key = _BRAND_KEY_MAP.get(brand_name.lower().strip(), "")
        domain = _BRAND_DOMAINS.get(brand_key, {}).get("domain", "")
        if domain:
            _q = chr(34) + mpn + chr(34)
            query = f"site:{domain} {_q} specifications"
        else:
            mfr_short = manufacturer_name.split(",")[0].strip()
            _q = chr(34) + mpn + chr(34)
            query = f"{mfr_short} {_q} specifications"
        print(f"  [scraperapi] Stage3 DDG query (blocked-domain list bypassed): '{query}'")
        ddg_results, ddg_status = _ddg_search(query)
        print(f"  [scraperapi] DDG status={ddg_status}  {len(ddg_results)} results")
        for r in ddg_results:
            candidate = r["url"]
            if _is_marketplace(candidate):
                continue
            if not domain or domain in candidate:
                stage3_url = candidate
                print(f"  [scraperapi] DDG found URL: {stage3_url}")
                break
        if not stage3_url:
            print(f"  [scraperapi] no usable DDG URL for {mpn} — Stage 3 skipped")
            return None, None

    print(f"  [scraperapi] fetching: {stage3_url}")
    html, status, err = _scraperapi_fetch(stage3_url, api_key)
    if not html:
        print(f"  [scraperapi] fetch failed: {err}")
        return None, stage3_url

    # Reuse the same trafilatura pipeline as web_scraper.py
    from scraper.web_scraper import clean_html as _web_clean_html
    extracted, _ = _web_clean_html(html)
    char_count = len(extracted or "")
    if not extracted or char_count < 100:
        print(
            f"  [scraperapi] HTTP {status} but content too sparse "
            f"({char_count} chars) — may still be JS-gated or wrong page"
        )
        return None, stage3_url

    print(f"  [scraperapi] content OK — {char_count:,} chars extracted")
    return extracted, stage3_url

_MARKETPLACE_DOMAINS = {
    "amazon", "ebay", "walmart", "homedepot", "lowes", "grainger",
    "mcmaster", "zoro", "wayfair", "target", "bestbuy", "costco",
    "overstock", "sears", "menards", "acehardware", "truevalue",
}


def _is_marketplace(url: str) -> bool:
    return any(m in url.lower() for m in _MARKETPLACE_DOMAINS)


# ── Promo-content filter ──────────────────────────────────────────────────────
# Signals that a scraped page is a rebate/promotion landing page, not a spec page.
_PROMO_SIGNALS: frozenset[str] = frozenset([
    "rebate", "promotion period", "claim submission", "prepaid mastercard",
    "bonus savings", "additional rebate", "rebate limit", "rebate payment",
    "mail-in rebate", "rebate form", "cashback", "coupon code",
])
# Signals that confirm genuine technical content is present.
_SPEC_SIGNALS: frozenset[str] = frozenset([
    "watt", "volt", "amp", "hertz", "hz", "decibel", "dba", "db ",
    "cubic feet", "cu ft", "gallon", "capacity", "dimension",
    "height", "width", "depth", "weight", "lb", "kg",
    "cycle", "temperature", "lumens", "color temperature", "efficacy",
    "horsepower", "rpm", "torque", "pressure", "flow rate",
    "ip rating", "ingress", "operating range",
])


def _is_promo_content(text: str) -> bool:
    """
    Return True when the scraped page is promotional / rebate copy with no
    technical specifications.  Two or more promo signals AND zero spec signals
    = page is useless for attribute extraction.
    """
    lower = text.lower()
    promo_hits = sum(1 for kw in _PROMO_SIGNALS if kw in lower)
    spec_hits  = sum(1 for kw in _SPEC_SIGNALS  if kw in lower)
    return promo_hits >= 2 and spec_hits == 0


def _brand_tokens(brand_name: str, manufacturer_name: str) -> frozenset[str]:
    """
    Build the set of lowercase identifiers we expect to see on a correct
    product page.  Includes the cleaned brand name (whole + individual words
    ≥ 4 chars) and the first word of the manufacturer name (company identity,
    not geography/legal suffix).
    """
    tokens: set[str] = set()
    brand_clean = re.sub(r"[®™]", "", brand_name).strip().lower()
    if brand_clean:
        tokens.add(brand_clean)
        tokens.update(w for w in brand_clean.split() if len(w) >= 4)
    # First word of manufacturer name (e.g. "Signify" from "Signify Netherlands B.V.")
    mfr_words = re.sub(r"[®™,.()\[\]]", " ", manufacturer_name).split()
    if mfr_words and len(mfr_words[0]) >= 4:
        tokens.add(mfr_words[0].lower())
    return frozenset(tokens)


def _is_wrong_brand(
    url: str,
    page_text: str,
    brand_name: str,
    manufacturer_name: str,
    verbose: bool = False,
) -> tuple[bool, str]:
    """
    Return (True, reason) when the scraped page belongs to a different
    manufacturer than the one we searched for.

    A page passes when at least one brand/manufacturer token appears in the
    hostname OR anywhere in the page text.  A page fails when none appear —
    confirming the content belongs to a different company.

    Returns (False, "") on pass; (True, human-readable reason) on fail.
    """
    tokens = _brand_tokens(brand_name, manufacturer_name)
    if not tokens:
        return False, ""   # can't verify — don't reject

    hostname = urlparse(url).netloc.lower()
    text_lower = page_text.lower()

    for tok in tokens:
        if tok in hostname or tok in text_lower:
            return False, ""   # brand confirmed present

    # Identify the actual brand from the hostname for a meaningful error message
    host_bare = hostname.lstrip("www.").split(".")[0]
    return True, (
        f"source page appears to be for '{host_bare}', not '{brand_name}' "
        f"(none of {sorted(tokens)} found in hostname or page text)"
    )


# ── Wrong-page-type gate ──────────────────────────────────────────────────────
_PAGE_COMPARISON_SIGNALS: frozenset[str] = frozenset([
    "comparison chart", "compare models", "side by side",
    "model comparison", "spec comparison", "compare features",
    "compare dishwashers", "compare appliances", "compare washers",
])

_PAGE_INSTALL_SIGNALS: frozenset[str] = frozenset([
    "installation checklist", "delivery checklist", "delivery check list",
    "installation guide", "installation instructions", "how to install",
    "support article", "support articles", "preparing for installation",
    "before your delivery", "installation requirements",
])


def _is_wrong_page_type(
    mpn: str,
    url: str,
    page_text: str,
    verbose: bool = False,
) -> tuple[bool, str]:
    """
    Return (True, reason) when the page is not a single-SKU product spec page.

    Primary check: the EXACT MPN appearing in the first 400 chars of the page
    (title/heading region) confirms the page is specifically about this product
    and passes outright — unless a hard comparison-chart signal also fires.

    When MPN is absent from the header (e.g. a manufacturer's EU catalog uses
    regional order numbers, not North American MPNs), secondary checks determine
    whether the page is a comparison chart, installation/support article, or
    product family/range page.  Pages that pass all secondary checks are accepted
    tentatively — brand and promo gates have already screened for the other
    failure modes.
    """
    lower = page_text.lower()
    mpn_lower = mpn.lower()
    # Normalize URL path: hyphens/underscores → spaces so "delivery-check-list"
    # matches the "delivery check list" signal.
    url_norm = url.lower().replace("-", " ").replace("_", " ")

    # ── Primary check: MPN in title/header region ─────────────────────────────
    mpn_in_header = mpn_lower in lower[:400]
    if mpn_in_header:
        # Still hard-reject a comparison chart even when MPN appears in it
        if any(s in lower or s in url_norm for s in _PAGE_COMPARISON_SIGNALS):
            return True, "comparison chart listing multiple models (MPN appears as one of many)"
        return False, ""

    # ── Secondary checks: MPN absent from header ──────────────────────────────

    # 1. Comparison / multi-model chart
    if any(s in lower or s in url_norm for s in _PAGE_COMPARISON_SIGNALS):
        return True, "comparison chart covering multiple models, not a single-SKU spec page"

    # 2. Installation / support article
    if any(s in lower or s in url_norm for s in _PAGE_INSTALL_SIGNALS):
        return True, "installation or support article, not a product spec page"

    # 3. Product family / range / category page (URL path signals)
    url_path = urlparse(url).path.lower()
    if (
        "/family" in url_path
        or "/range/" in url_path
        or url_path.endswith("/range")
        or url_path.endswith("/category")
        or "/category/" in url_path
    ):
        return True, "product family/range/category page covering multiple SKUs, not a single-model spec page"

    # 4. Range-valued specs in content (e.g. "300lm to 2000lm" or "2,700 K to
    #    6,500 K") indicate a family overview, not a single-product spec page.
    #    Pattern handles optional thousands comma and optional space before unit.
    if re.search(r"\d[\d,]*\s*(?:lm|w|v|hz|k)\s+to\s+\d[\d,]*\s*(?:lm|w|v|hz|k)", lower):
        return True, "page shows a range of spec values (e.g. '300lm to 2000lm'), not a single-SKU spec page"

    return False, ""


# ── Hard-excluded domains (Tavily exclude_domains list) ───────────────────────
# Judging brief explicitly forbids Amazon, eBay, Walmart, Home Depot.
# Expanded to cover all major regional TLDs so they can't slip through.
_TAVILY_HARD_EXCLUDE: list[str] = [
    # Amazon
    "amazon.com", "amazon.ca", "amazon.co.uk", "amazon.de", "amazon.ae",
    "amazon.in", "amazon.fr", "amazon.it", "amazon.es", "amazon.com.au",
    "amazon.co.jp", "amazon.com.mx", "amazon.com.br",
    # eBay
    "ebay.com", "ebay.ca", "ebay.co.uk", "ebay.de", "ebay.fr",
    "ebay.it", "ebay.es", "ebay.com.au",
    # Walmart
    "walmart.com", "walmart.ca",
    # Home Depot
    "homedepot.com", "homedepot.ca",
    # Grainger (forbidden per sourcing hierarchy)
    "grainger.com", "grainger.ca", "grainger.co.uk",
    # Zoro (Grainger subsidiary)
    "zoro.com",
]

# ── Known B2B distributor domain keywords (source tier = "distributor") ───────
# These are industrial/commercial suppliers that are NOT hard-excluded —
# they carry real specs and are acceptable sourcing for industrial products.
_DISTRIBUTOR_KEYWORDS: frozenset[str] = frozenset([
    "mscdirect", "fastenal", "motionindustries", "wesco", "graybar",
    "rexel", "anixter", "platt", "bulbconnection", "atlascopco",
    "genlyte", "signify", "1000bulbs", "bulbs", "lightbulbs",
    "galco", "automationdirect", "newark", "digikey", "mouser",
    "alliedelec", "arrow", "ttelectronics",
])


def _classify_source_tier(url: str, mfr_domain: str) -> str:
    """Classify a URL into 'manufacturer', 'distributor', or 'retailer'."""
    host = urlparse(url).netloc.lower().lstrip("www.")
    # Strip one leading subdomain level for comparison (e.g. lighting.philips.com → philips.com)
    host_base = host.split(".", 1)[-1] if host.count(".") >= 2 else host
    if mfr_domain:
        clean_mfr = mfr_domain.lstrip("www.")
        if host == clean_mfr or host_base == clean_mfr or host.endswith("." + clean_mfr):
            return "manufacturer"
    if any(kw in host for kw in _DISTRIBUTOR_KEYWORDS):
        return "distributor"
    return "retailer"


# ── Tavily client (lazy init) ─────────────────────────────────────────────────
_tavily_client = None


def _get_tavily_client():
    global _tavily_client
    if _tavily_client is not None:
        return _tavily_client
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None
    try:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=api_key)
        return _tavily_client
    except ImportError:
        return None


def _tavily_discover(
    mpn: str,
    brand_name: str,
    manufacturer_name: str,
    part_desc: str,
    mfr_domain: str,
    verbose: bool = False,
) -> tuple[str, str] | None:
    """
    Stage 2: Tavily search for the best product page for this MPN.

    Builds a rich query from brand + MPN + cleaned Part_Desc to anchor
    numeric MPNs to the right product (fixes Philips 801274/567313 mismatches
    that occurred with brand+MPN-only queries).

    Returns (url, source_tier) or None.
    source_tier is 'manufacturer', 'distributor', or 'retailer'.
    Respects ALLOW_RETAILER_SOURCES: when False, only manufacturer/distributor
    results are accepted.
    """
    client = _get_tavily_client()
    if client is None:
        if verbose:
            print(f"  [tavily] TAVILY_API_KEY not set or tavily-python not installed — skipping")
        return None

    # Build a richer query; strip leading "Brand MPN" from Part_Desc to avoid duplication.
    # Strip brand first (Part_Desc is often "Brand MPN Description"), then MPN.
    brand_display = re.sub(r"[®™]", "", brand_name).strip()
    mfr_short = manufacturer_name.split(",")[0].split("(")[0].strip()
    desc_clean = part_desc
    if brand_display:
        desc_clean = re.sub(r"^\s*" + re.escape(brand_display) + r"\s*[-–]?\s*", "", desc_clean, flags=re.IGNORECASE).strip()
    desc_clean = re.sub(r"^\s*" + re.escape(mpn) + r"\s*[-–]?\s*", "", desc_clean, flags=re.IGNORECASE).strip()

    if desc_clean:
        query = f"{brand_display} {mpn} {desc_clean} specifications"
    elif mfr_short and mfr_short.lower() not in brand_display.lower():
        query = f"{mfr_short} {brand_display} {mpn} specifications"
    else:
        query = f"{brand_display} {mpn} specifications"

    if verbose:
        print(f"  [tavily] query: '{query}'")

    # ── Pass A: domain-scoped search (manufacturer's own site) ───────────────
    # When we know the manufacturer's domain, try restricting Tavily to that
    # domain first.  This eliminates competitor pages for numeric MPNs (e.g.
    # Philips 567313 matching Feit on a general search).  Only skip when
    # mfr_domain is unknown.
    if mfr_domain:
        try:
            scoped_resp = client.search(
                query=query,
                include_domains=[mfr_domain],
                max_results=3,
                include_raw_content=False,
            )
            for r in scoped_resp.get("results", []):
                url = r.get("url", "")
                score = r.get("score", 0)
                if url:
                    if verbose:
                        print(f"  [tavily] domain-scoped hit [manufacturer] score={score:.3f}: {url}")
                    return url, "manufacturer"
        except Exception as e:
            if verbose:
                print(f"  [tavily] domain-scoped search error: {e}")
        if verbose:
            print(f"  [tavily] domain-scoped pass: no results on {mfr_domain} — falling back to general search")

    # ── Pass B: general search with hard exclusions ───────────────────────────
    try:
        resp = client.search(
            query=query,
            exclude_domains=_TAVILY_HARD_EXCLUDE,
            max_results=5,
            include_raw_content=False,
        )
    except Exception as e:
        if verbose:
            print(f"  [tavily] search error: {e}")
        return None

    results = resp.get("results", [])
    if verbose:
        print(f"  [tavily] general search: {len(results)} results")

    for r in results:
        url = r.get("url", "")
        score = r.get("score", 0)
        if not url:
            continue

        # Belt-and-suspenders: re-check hard exclusions (regional TLDs may slip)
        host_lower = urlparse(url).netloc.lower()
        if any(excl.lstrip("www.") in host_lower for excl in _TAVILY_HARD_EXCLUDE):
            if verbose:
                print(f"  [tavily] post-filter excluded: {url}")
            continue

        tier = _classify_source_tier(url, mfr_domain)

        if not ALLOW_RETAILER_SOURCES and tier == "retailer":
            if verbose:
                print(f"  [tavily] skip retailer (ALLOW_RETAILER_SOURCES=False): {url}")
            continue

        if verbose:
            print(f"  [tavily] selected [{tier}] score={score:.3f}: {url}")
        return url, tier

    if verbose:
        print(f"  [tavily] no usable result found for {mpn}")
    return None


def _tavily_candidates(
    mpn: str,
    brand_name: str,
    manufacturer_name: str,
    part_desc: str,
    mfr_domain: str,
    verbose: bool = False,
) -> list[tuple[str, str]]:
    """
    Return all (url, tier) candidates from Tavily in priority order:
    domain-scoped results (tier='manufacturer') first, then general results.
    Deduplicates URLs across both passes.

    The caller iterates this list and applies quality gates to each candidate,
    continuing to the next on any gate failure.  A bad domain-scoped hit never
    blocks the general search — it just gets skipped.
    """
    client = _get_tavily_client()
    if client is None:
        if verbose:
            print(f"  [tavily] TAVILY_API_KEY not set — skipping")
        return []

    # Build query (same logic as _tavily_discover)
    brand_display = re.sub(r"[®™]", "", brand_name).strip()
    mfr_short = manufacturer_name.split(",")[0].split("(")[0].strip()
    desc_clean = part_desc
    if brand_display:
        desc_clean = re.sub(
            r"^\s*" + re.escape(brand_display) + r"\s*[-–]?\s*",
            "", desc_clean, flags=re.IGNORECASE,
        ).strip()
    desc_clean = re.sub(
        r"^\s*" + re.escape(mpn) + r"\s*[-–]?\s*",
        "", desc_clean, flags=re.IGNORECASE,
    ).strip()

    if desc_clean:
        query = f"{brand_display} {mpn} {desc_clean} specifications"
    elif mfr_short and mfr_short.lower() not in brand_display.lower():
        query = f"{mfr_short} {brand_display} {mpn} specifications"
    else:
        query = f"{brand_display} {mpn} specifications"

    if verbose:
        print(f"  [tavily] query: '{query}'")

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Pass A: domain-scoped — collect all results, not just first
    if mfr_domain:
        try:
            scoped = client.search(
                query=query,
                include_domains=[mfr_domain],
                max_results=3,
                include_raw_content=False,
            )
            for r in scoped.get("results", []):
                url = r.get("url", "")
                score = r.get("score", 0)
                if url and url not in seen:
                    seen.add(url)
                    candidates.append((url, "manufacturer"))
                    if verbose:
                        print(f"  [tavily] domain-scoped candidate score={score:.3f}: {url}")
            if not candidates and verbose:
                print(f"  [tavily] domain-scoped: no results on {mfr_domain}")
        except Exception as e:
            if verbose:
                print(f"  [tavily] domain-scoped error: {e}")

    # Pass B: general search — collect all results, not just first
    try:
        general = client.search(
            query=query,
            exclude_domains=_TAVILY_HARD_EXCLUDE,
            max_results=5,
            include_raw_content=False,
        )
        for r in general.get("results", []):
            url = r.get("url", "")
            score = r.get("score", 0)
            if not url or url in seen:
                continue
            host_lower = urlparse(url).netloc.lower()
            if any(excl.lstrip("www.") in host_lower for excl in _TAVILY_HARD_EXCLUDE):
                continue
            tier = _classify_source_tier(url, mfr_domain)
            if not ALLOW_RETAILER_SOURCES and tier == "retailer":
                if verbose:
                    print(f"  [tavily] skip retailer (ALLOW_RETAILER_SOURCES=False): {url}")
                continue
            seen.add(url)
            candidates.append((url, tier))
            if verbose:
                print(f"  [tavily] general candidate [{tier}] score={score:.3f}: {url}")
    except Exception as e:
        if verbose:
            print(f"  [tavily] general search error: {e}")

    if not candidates and verbose:
        print(f"  [tavily] no candidates found for {mpn}")

    return candidates


def _ddg_search(query: str, max_results: int = 8) -> tuple[list[dict], str]:
    """
    DuckDuckGo HTML endpoint search (no API key, no rate limit contract).
    Returns (results, status) where status is one of:
      "ok"            — got ≥1 result
      "zero_results"  — HTTP 200 but no .result__a links
      "blocked"       — response suspiciously short (likely CAPTCHA/redirect)
      "timeout"       — connection or read timed out
      "error:<msg>"   — other exception
    """
    # Respect DDG's rate limits with a wider gap than regular domains
    now = time.monotonic()
    gap = now - _DOMAIN_LAST_HIT.get(_DDG_DOMAIN, 0.0)
    if gap < _DDG_MIN_GAP:
        time.sleep(_DDG_MIN_GAP - gap)
    _DOMAIN_LAST_HIT[_DDG_DOMAIN] = time.monotonic()

    try:
        resp = requests.post(
            f"https://{_DDG_DOMAIN}/html/",
            data={"q": query},
            headers=_HEADERS,
            verify=False,
            timeout=(5, 15),
        )
        html = resp.text
        # Very short response = CAPTCHA or block page
        if len(html) < 1000:
            return [], "blocked"
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for a in soup.select(".result__a")[:max_results]:
            href = a.get("href", "")
            m = re.search(r"uddg=([^&]+)", href)
            url = requests.utils.unquote(m.group(1)) if m else href
            results.append({"title": a.get_text(strip=True), "url": url})
        status = "ok" if results else "zero_results"
        return results, status
    except requests.exceptions.Timeout:
        return [], "timeout"
    except Exception as e:
        return [], f"error:{e}"


def _try_direct_url(mpn: str, domain_key: str) -> str | None:
    """
    Try to fetch the product page at a known URL pattern.
    Returns the URL if the page exists (HTTP 200), else None.
    Supports both format-string templates and callable url_fn entries.
    """
    entry = _BRAND_DOMAINS.get(domain_key, {})
    url_fn = entry.get("url_fn")
    template = entry.get("product_url")

    if url_fn:
        url = url_fn(mpn)
    elif template:
        url = template.format(mpn=mpn, mpn_lower=mpn.lower())
    else:
        return None

    try:
        _throttle(url)
        resp = requests.head(
            url, headers=_HEADERS, verify=False,
            timeout=(5, 8),   # 5s connect, 8s read — fail fast on blocked sites
            allow_redirects=True,
        )
        if resp.status_code == 200:
            return url
    except Exception:
        pass
    return None


def find_manufacturer_page(
    mpn: str,
    manufacturer_name: str,
    brand_name: str,
    verbose: bool = False,
    use_ddg: bool = False,
) -> str | None:
    """
    Stage 1: direct URL template lookup only.

    Returns the manufacturer's product page URL if a known template exists
    and the page responds with HTTP 200. Returns None otherwise.

    use_ddg is kept for backward compatibility but is ignored (DDG was
    replaced by Tavily in enrich_from_manufacturer; Stage 3 still uses DDG
    internally via _scraperapi_stage3).
    """
    brand_key = _BRAND_KEY_MAP.get(brand_name.lower().strip(), "")

    if verbose:
        print(f"  [enrich] brand_name='{brand_name}'  brand_key='{brand_key}'")

    if brand_key:
        entry = _BRAND_DOMAINS.get(brand_key, {})
        has_direct = entry.get("product_url") or entry.get("url_fn")
        if has_direct:
            if verbose:
                candidate = (entry["url_fn"](mpn) if entry.get("url_fn")
                             else entry["product_url"].format(mpn=mpn, mpn_lower=mpn.lower()))
                print(f"  [enrich] trying direct URL: {candidate}")
            direct = _try_direct_url(mpn, brand_key)
            if direct:
                if verbose:
                    print(f"  [enrich] direct URL OK → {direct}")
                return direct
            if verbose:
                print(f"  [enrich] direct URL returned non-200 or error")
        else:
            if verbose:
                print(f"  [enrich] no direct URL template for brand_key='{brand_key}'")
    else:
        if verbose:
            print(f"  [enrich] brand_key not in _BRAND_KEY_MAP — no direct URL")

    return None


def enrich_from_manufacturer(
    mpn: str,
    manufacturer_name: str,
    brand_name: str,
    product_type: str = "",
    part_desc: str = "",
    verbose: bool = False,
    use_ddg: bool = False,
) -> dict:
    """
    Full enrichment for one product:
      Stage 1: Direct URL template (fast, free) → source_tier = "manufacturer"
      Stage 2: Tavily web search (1,000 free credits/month) → source_tier from _classify_source_tier
      Stage 2.5: MPN cache replay (free; no network)
      Stage 3: ScraperAPI (last resort — costs credits; only runs if SCRAPERAPI_KEY set)

    Returns:
        {enriched, source_url, source_tier, attributes, series, product_record, error}

    enriched=False means all stages failed; caller should proceed without
    enrichment rather than raising.
    source_tier is 'manufacturer', 'distributor', or 'retailer'; None if not enriched.
    """
    result: dict = {
        "enriched": False,
        "source_url": None,
        "source_tier": None,
        "attributes": [],
        "series": None,
        "product_record": None,
        "error": None,
    }

    brand_key = _BRAND_KEY_MAP.get(brand_name.lower().strip(), "")
    mfr_domain = _BRAND_DOMAINS.get(brand_key, {}).get("domain", "")

    url: str | None = None
    source_tier: str | None = None
    clean_text: str | None = None

    # ── Stage 1: Direct URL template ─────────────────────────────────────────
    url = find_manufacturer_page(mpn, manufacturer_name, brand_name, verbose=verbose)
    if url:
        source_tier = "manufacturer"
        result["source_url"] = url
        result["source_tier"] = source_tier
        if verbose:
            print(f"  [enrich] Stage1 hit [manufacturer]: {url}")
        _throttle(url)
        page = scrape_product_page(url)
        if not page.success:
            result["error"] = f"Scrape failed: {page.error}"
            if verbose:
                print(f"  [enrich] scrape FAILED: {page.error}")
        elif len(page.clean_text) < 100:
            result["error"] = "Page text too short — likely JS-rendered or blocked"
            if verbose:
                print(f"  [enrich] page text too short ({len(page.clean_text)} chars)")
        else:
            if verbose:
                print(f"  [enrich] page scraped OK ({len(page.clean_text)} chars)")
            clean_text = page.clean_text

    # ── Stage 2: Tavily — collect all gate-passing candidates, prefer MPN match ─
    # Scrape every candidate from both domain-scoped and general search and apply
    # all three quality gates to each.  Collect every candidate that passes all
    # gates, then select the BEST one:
    #
    #   • exact_mpn_verified=True candidates rank above False ones, regardless
    #     of Tavily score or domain-scoped vs general tier.  A retailer page that
    #     explicitly mentions the MPN beats a manufacturer EU page that doesn't.
    #   • Within the same verification status, Tavily rank order is preserved
    #     (domain-scoped first, then general; stable sort).
    #
    # This prevents the common Philips pattern where domain-scoped returns an EU
    # product page (similar but not the same SKU) while a general-search retailer
    # page has the exact NA MPN in its text.
    stage2_gated = False
    if url is None:
        # Each entry: (url, tier, text_with_title, mpn_verified)
        _gate_passing: list[tuple[str, str, str, bool]] = []

        for cand_url, cand_tier in _tavily_candidates(
            mpn=mpn,
            brand_name=brand_name,
            manufacturer_name=manufacturer_name,
            part_desc=part_desc,
            mfr_domain=mfr_domain,
            verbose=verbose,
        ):
            if verbose:
                print(f"  [enrich] Stage2 trying [{cand_tier}]: {cand_url}")
            _throttle(cand_url)
            page = scrape_product_page(cand_url)
            if not page.success:
                if verbose:
                    print(f"  [enrich] scrape FAILED — skip: {page.error}")
                continue
            if len(page.clean_text) < 100:
                if verbose:
                    print(f"  [enrich] page too short ({len(page.clean_text)} chars) — skip")
                continue

            # Prepend page title before gates so the header region check in
            # _is_wrong_page_type also sees the title (MPN in title = singular page).
            page_title = page.title or ""
            cand_text = (f"{page_title}\n" if page_title else "") + page.clean_text

            # Gate 1: wrong brand
            wb, br = _is_wrong_brand(cand_url, cand_text, brand_name, manufacturer_name, verbose)
            if wb:
                if verbose:
                    print(f"  [enrich] brand gate — skip: {br}")
                continue

            # Gate 2: wrong page type
            wt, tr = _is_wrong_page_type(mpn, cand_url, cand_text, verbose)
            if wt:
                if verbose:
                    print(f"  [enrich] page-type gate — skip: {tr}")
                continue

            # Gate 3: promo content
            if _is_promo_content(cand_text):
                if verbose:
                    print(f"  [enrich] promo gate — skip: {cand_url}")
                continue

            # All gates passed — record MPN verification for selection ranking
            _mpn_lower = mpn.lower()
            cand_mpn_verified = (
                _mpn_lower in cand_text.lower()
                or _mpn_lower in cand_url.lower()
            )
            _gate_passing.append((cand_url, cand_tier, cand_text, cand_mpn_verified))
            if verbose:
                print(f"  [enrich] Stage2 gate-pass [{cand_tier}] mpn_verified={cand_mpn_verified}: {cand_url}")

        if _gate_passing:
            # Sort: exact-MPN matches first; within each group preserve Tavily rank
            # order (stable sort).  Pick the top candidate.
            _gate_passing.sort(key=lambda c: (not c[3],))
            url, source_tier, clean_text, _ = _gate_passing[0]
            result["source_url"] = url
            result["source_tier"] = source_tier
            stage2_gated = True
            if verbose:
                _best_mpn_v = _gate_passing[0][3]
                _total = len(_gate_passing)
                print(
                    f"  [enrich] Stage2 selected [mpn_verified={_best_mpn_v}] "
                    f"[{source_tier}] (1 of {_total} gate-passing): {url}"
                )
        else:
            if verbose:
                print(f"  [enrich] Stage2 no gate-passing candidates for {mpn}")

    # ── Stage 2.5: MPN-based cache replay ────────────────────────────────────
    # Check whether a prior successful run cached the extraction for this MPN.
    # The extract cache is keyed by URL; scan for any key containing the MPN.
    # extract_product() ignores source_text on cache hit, so "" is safe.
    if url is None and clean_text is None:
        try:
            from unihack import llm_cache as _lc
            match = _lc.find_by_substring("extract", mpn)
            if match:
                cached_url, _ = match
                print(f"  [enrich] cache replay for {mpn} → {cached_url}")
                record = extract_product("", source_id=cached_url)
                result["enriched"] = True
                result["source_url"] = cached_url
                result["product_record"] = record
                result["attributes"] = record.attributes
                for attr in record.attributes:
                    if "series" in attr.name.lower():
                        result["series"] = attr.value
                        break
                return result
        except Exception as _ce:
            if verbose:
                print(f"  [enrich] cache replay failed: {_ce}")

    # ── Stage 3: ScraperAPI fallback (last resort — costs credits) ──────────
    if clean_text is None:
        clean_text, s3_url = _scraperapi_stage3(
            mpn, manufacturer_name, brand_name, url, verbose=verbose
        )
        if s3_url:
            result["source_url"] = s3_url
            if source_tier is None:
                source_tier = _classify_source_tier(s3_url, mfr_domain)
            result["source_tier"] = source_tier

    if clean_text is None:
        if not result["error"]:
            result["error"] = f"No manufacturer page found for {mpn} ({brand_name})"
        return result

    # ── Quality gates (Stage 1 and Stage 3 results only) ─────────────────────
    # Stage 2 candidates already passed all three gates in the candidate loop
    # above.  Only Stage 1 (direct URL) and Stage 3 (ScraperAPI) results reach
    # this block.
    if not stage2_gated:
        wrong_brand, brand_reason = _is_wrong_brand(
            result["source_url"], clean_text, brand_name, manufacturer_name, verbose
        )
        if wrong_brand:
            result["error"] = f"Brand mismatch: {brand_reason}"
            if verbose:
                print(f"  [enrich] brand-verification gate triggered for {mpn}: {brand_reason}")
            return result

        wrong_type, type_reason = _is_wrong_page_type(
            mpn, result["source_url"], clean_text, verbose
        )
        if wrong_type:
            result["error"] = f"Wrong page type: {type_reason}"
            if verbose:
                print(f"  [enrich] wrong-page-type gate triggered for {mpn}: {type_reason}")
            return result

        if _is_promo_content(clean_text):
            result["error"] = "Page is promotional/rebate content — no technical specs present"
            if verbose:
                print(f"  [enrich] promo-content gate triggered — skipping LLM for {mpn}")
            return result

    # ── MPN verification flag ─────────────────────────────────────────────────
    # Check whether the exact input MPN appears literally in the page content,
    # page title (prepended to clean_text above), or the source URL slug.
    # True  → the page is confirmed to be about this specific product.
    # False → the page is related (correct brand/category) but may be a nearby
    #         model, EU variant, or family overview.  Specs are still useful but
    #         the discrepancy is surfaced in the dashboard rather than silently
    #         treated as a full match.
    _mpn_lower = mpn.lower()
    _url_lower = (result.get("source_url") or "").lower()
    exact_mpn_verified = _mpn_lower in clean_text.lower() or _mpn_lower in _url_lower
    result["exact_mpn_verified"] = exact_mpn_verified
    if verbose:
        status = "confirmed" if exact_mpn_verified else "NOT FOUND — related page"
        print(f"  [enrich] exact_mpn_verified={exact_mpn_verified} ('{mpn}' {status} in page text/URL)")

    # ── LLM extraction (same path regardless of which stage fetched the page) ─
    try:
        record = extract_product(clean_text, source_id=result["source_url"])
        result["product_record"] = record
        result["enriched"] = True

        # Stamp source_tier on every attribute extracted from this page
        for attr in record.attributes:
            attr.source_tier = source_tier

        result["attributes"] = record.attributes

        for attr in record.attributes:
            if "series" in attr.name.lower():
                result["series"] = attr.value
                break
    except Exception as e:
        result["error"] = f"Extraction failed: {e}"
        if verbose:
            print(f"  [enrich] extraction FAILED: {e}")

    return result
