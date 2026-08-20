"""
Manufacturer normalization: parses "Freud Inc (2435)" -> {manufacturer_name, brand_name}.

Name casing follows the 200-row ground truth:
  "Stanley Black & Decker" (no Inc.), "Makita" (no "USA, Inc."),
  "Signify Holding" (not North America Corp), "SATCO®" (all caps), "DeWALT®", etc.

Lookup priority: MPN prefix (most reliable) > numeric code > normalized name > LLM.
"""

import os
import re
import json

# Keys: lowercase code OR lowercase name fragment from Part_Manuf "(CODE)" or bare name.
# Values: {manufacturer_name, brand_name} using ground-truth casing.
MANUFACTURER_CANONICAL: dict[str, dict] = {

    # ── Stanley Black & Decker / DEWALT ─────────────────────────────────────
    "2585":               {"manufacturer_name": "Stanley Black & Decker", "brand_name": "DeWALT®"},
    "black & decker/dewlt": {"manufacturer_name": "Stanley Black & Decker", "brand_name": "DeWALT®"},
    "dewalt":             {"manufacturer_name": "Stanley Black & Decker", "brand_name": "DeWALT®"},

    # ── Milwaukee Tool ───────────────────────────────────────────────────────
    "4031":               {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},
    "milwaukee accessory": {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},
    "milwaukee tool":     {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},

    # ── Makita ──────────────────────────────────────────────────────────────
    "makita usa inc":     {"manufacturer_name": "Makita", "brand_name": "Makita®"},
    "makita":             {"manufacturer_name": "Makita", "brand_name": "Makita®"},

    # ── Freud / Diablo ──────────────────────────────────────────────────────
    "2435":               {"manufacturer_name": "Freud America, Inc", "brand_name": "DIABLO®"},
    "freud inc":          {"manufacturer_name": "Freud America, Inc", "brand_name": "DIABLO®"},
    "freud":              {"manufacturer_name": "Freud America, Inc", "brand_name": "DIABLO®"},

    # ── Festool ─────────────────────────────────────────────────────────────
    "festool usa":        {"manufacturer_name": "Festool GmbH", "brand_name": "Festool®"},
    "festool":            {"manufacturer_name": "Festool GmbH", "brand_name": "Festool®"},

    # ── Building materials ───────────────────────────────────────────────────
    "trex":               {"manufacturer_name": "Trex Company, Inc", "brand_name": "Trex®"},
    "trex company":       {"manufacturer_name": "Trex Company, Inc", "brand_name": "Trex®"},
    "timbertech":         {"manufacturer_name": "TimberTech", "brand_name": "TimberTech®"},
    "azek":               {"manufacturer_name": "AZEK Building Products", "brand_name": "AZEK®"},
    "boise cascade building materials": {
        "manufacturer_name": "Boise Cascade Building Products", "brand_name": "Boise Cascade®",
    },
    "parksite":           {"manufacturer_name": "Parksite Inc.", "brand_name": "Parksite"},
    "u s lumber":         {"manufacturer_name": "U.S. LBM Holdings, LLC", "brand_name": "U.S. LBM"},

    # ── Appliances — Rheem/Frigidaire ────────────────────────────────────────
    "frigidaire":         {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    "rheem manufacturing": {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},

    # ── Whirlpool ────────────────────────────────────────────────────────────
    "whirlpool":          {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    "whirlpool corporation": {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    # Whirlpool sub-brands
    "maytag":             {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Maytag®"},
    "kitchenaid":         {"manufacturer_name": "Whirlpool Corporation", "brand_name": "KitchenAid®"},
    "amana":              {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Amana®"},
    "jennair":            {"manufacturer_name": "Whirlpool Corporation", "brand_name": "JennAir®"},
    "jenn-air":           {"manufacturer_name": "Whirlpool Corporation", "brand_name": "JennAir®"},

    # ── Speed Queen / Alliance Laundry ───────────────────────────────────────
    "alliance laundry":   {"manufacturer_name": "Alliance Laundry Systems LLC", "brand_name": "Speed Queen®"},
    "alliance laundry systems": {"manufacturer_name": "Alliance Laundry Systems LLC", "brand_name": "Speed Queen®"},
    "speed queen":        {"manufacturer_name": "Alliance Laundry Systems LLC", "brand_name": "Speed Queen®"},

    # ── GE Appliances / Haier ───────────────────────────────────────────────
    # Haier acquired GE Appliances in 2016; consumer brand remains "GE Appliances"
    "ge appliances":      {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},
    "ge appliances, a haier company": {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},
    "haier":              {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},
    "haier us appliance": {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},
    "general electric":   {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},
    # GE sub-brands
    "ge profile":         {"manufacturer_name": "GE Appliances", "brand_name": "GE Profile™"},
    "ge cafe":            {"manufacturer_name": "GE Appliances", "brand_name": "GE Café™"},
    "ge café":            {"manufacturer_name": "GE Appliances", "brand_name": "GE Café™"},

    # ── Lighting — Signify/Philips ───────────────────────────────────────────
    "phillips lighting":  {"manufacturer_name": "Signify Holding", "brand_name": "Philips"},
    "5831":               {"manufacturer_name": "Signify Holding", "brand_name": "Philips"},
    "signify":            {"manufacturer_name": "Signify Holding", "brand_name": "Philips"},
    "philips":            {"manufacturer_name": "Signify Holding", "brand_name": "Philips"},

    # ── Kichler ──────────────────────────────────────────────────────────────
    "kichler lighting":   {"manufacturer_name": "The L.D. Kichler Co", "brand_name": "Kichler®"},
    "kicli":              {"manufacturer_name": "The L.D. Kichler Co", "brand_name": "Kichler®"},
    "kichler":            {"manufacturer_name": "The L.D. Kichler Co", "brand_name": "Kichler®"},

    # ── Satco / NUVO ─────────────────────────────────────────────────────────
    "satco prod inc":     {"manufacturer_name": "Satco Products, Inc", "brand_name": "SATCO®"},
    "5573":               {"manufacturer_name": "Satco Products, Inc", "brand_name": "SATCO®"},
    "satco":              {"manufacturer_name": "Satco Products, Inc", "brand_name": "SATCO®"},
    "nuvo":               {"manufacturer_name": "Satco Products, Inc", "brand_name": "NUVO® by SATCO"},

    # ── United Window & Door ───────────────────────────────────────────────
    "united window & door": {"manufacturer_name": "United Window & Door", "brand_name": "United Window & Door"},
    "united window":      {"manufacturer_name": "United Window & Door", "brand_name": "United Window & Door"},
    "uniwi":              {"manufacturer_name": "United Window & Door", "brand_name": "United Window & Door"},

    # ── VELUX Group ──────────────────────────────────────────────────
    "velux america inc":  {"manufacturer_name": "VELUX Group", "brand_name": "VELUX®"},
    "velux america":      {"manufacturer_name": "VELUX Group", "brand_name": "VELUX®"},
    "velam":              {"manufacturer_name": "VELUX Group", "brand_name": "VELUX®"},
    "velux":              {"manufacturer_name": "VELUX Group", "brand_name": "VELUX®"},

    # ── HAGER COMPANIES ───────────────────────────────────────────────
    "hager hinge co":     {"manufacturer_name": "HAGER COMPANIES", "brand_name": "HAGER®"},
    "4189":               {"manufacturer_name": "HAGER COMPANIES", "brand_name": "HAGER®"},
    "hager":              {"manufacturer_name": "HAGER COMPANIES", "brand_name": "HAGER®"},

    # ── J.M. Huber / ZIP System ────────────────────────────────────────────
    "huber eng wood llc": {"manufacturer_name": "J.M. Huber Corporation", "brand_name": "ZIP System®"},
    "huber eng wood":     {"manufacturer_name": "J.M. Huber Corporation", "brand_name": "ZIP System®"},
    "3158":               {"manufacturer_name": "J.M. Huber Corporation", "brand_name": "ZIP System®"},
    "huber":              {"manufacturer_name": "J.M. Huber Corporation", "brand_name": "ZIP System®"},

    # ── Schumacher Electric ───────────────────────────────────────────────
    "schumacher electric corporation": {"manufacturer_name": "Schumacher Electric Corporation", "brand_name": "Schumacher®"},
    "schumacher electric": {"manufacturer_name": "Schumacher Electric Corporation", "brand_name": "Schumacher®"},
    "schumacher":         {"manufacturer_name": "Schumacher Electric Corporation", "brand_name": "Schumacher®"},

    # ── Lithonia Lighting / Acuity Brands ───────────────────────────────────
    "lithonia lighting":  {"manufacturer_name": "Acuity Brands Lighting", "brand_name": "Lithonia Lighting®"},
    "2776":               {"manufacturer_name": "Acuity Brands Lighting", "brand_name": "Lithonia Lighting®"},
    "acuity brands":      {"manufacturer_name": "Acuity Brands Lighting", "brand_name": "Lithonia Lighting®"},

    # ── Cooper Lighting / Halo ───────────────────────────────────────────────
    "cooper lighting":    {"manufacturer_name": "Cooper Lighting LLC", "brand_name": "HALO"},
    "7638":               {"manufacturer_name": "Cooper Lighting LLC", "brand_name": "HALO"},

    # ── Electrical — Leviton ─────────────────────────────────────────────────
    "leviton mfg co":     {"manufacturer_name": "Leviton", "brand_name": "Leviton®"},
    "leviton":            {"manufacturer_name": "Leviton", "brand_name": "Leviton®"},

    # ── Southwire ─────────────────────────────────────────────────────────────
    "southwire":          {"manufacturer_name": "Southwire Company, LLC", "brand_name": "Southwire®"},
    "6603":               {"manufacturer_name": "Southwire Company, LLC", "brand_name": "Southwire®"},
    "7579":               {"manufacturer_name": "Southwire Company, LLC", "brand_name": "Southwire®"},

    # ── Police Security ───────────────────────────────────────────────────────
    "police security":    {"manufacturer_name": "Police Security Flashlights", "brand_name": "Police Security®"},
    "9470":               {"manufacturer_name": "Police Security Flashlights", "brand_name": "Police Security®"},

    # ── U.S. Tape / Stringliner ───────────────────────────────────────────────
    "u s tape company":   {"manufacturer_name": "U.S. Tape Company", "brand_name": "Stringliner®"},
    "6694":               {"manufacturer_name": "U.S. Tape Company", "brand_name": "Stringliner®"},

    # ── Malco Products ────────────────────────────────────────────────────────
    "malco prod":         {"manufacturer_name": "Aspen Pumps Group Limited", "brand_name": "Malco®"},
    "2370":               {"manufacturer_name": "Aspen Pumps Group Limited", "brand_name": "Malco®"},

    # ── Mirka ─────────────────────────────────────────────────────────────────
    "mirka abrasives inc": {"manufacturer_name": "Mirka Ltd", "brand_name": "MIRKA"},
    "mirus":              {"manufacturer_name": "Mirka Ltd", "brand_name": "MIRKA"},

    # ── CMT USA ───────────────────────────────────────────────────────────────
    "cmt usa inc":        {"manufacturer_name": "CMT ORANGE TOOLS", "brand_name": "CMT ORANGE TOOLS®"},
    "cmtus":              {"manufacturer_name": "CMT ORANGE TOOLS", "brand_name": "CMT ORANGE TOOLS®"},

    # ── JPW Industries / JET ──────────────────────────────────────────────────
    "jpw industries":     {"manufacturer_name": "JPW Industries", "brand_name": "JET®"},
    "jpwin":              {"manufacturer_name": "JPW Industries", "brand_name": "JET®"},

    # ── Senco / KYOCERA ───────────────────────────────────────────────────────
    "senco products inc": {"manufacturer_name": "KYOCERA Corporation", "brand_name": "SENCO®"},
    "4650":               {"manufacturer_name": "KYOCERA Corporation", "brand_name": "SENCO®"},

    # ── EDGE Eyewear / Wolf Peak ──────────────────────────────────────────────
    "edge eyewear inc":   {"manufacturer_name": "Wolf Peak International", "brand_name": "EDGE®"},
    "edgsa":              {"manufacturer_name": "Wolf Peak International", "brand_name": "EDGE®"},

    # ── Oliver Machinery ─────────────────────────────────────────────────────
    "oliver machinery company": {"manufacturer_name": "Oliver Machinery Company", "brand_name": "Oliver Machinery"},
    "olima":              {"manufacturer_name": "Oliver Machinery Company", "brand_name": "Oliver Machinery"},

    # ── 3M ───────────────────────────────────────────────────────────────────
    "3m":                 {"manufacturer_name": "3M Company", "brand_name": "3M™"},
}

# MPN prefix → canonical entry, used inside _infer_brand_from_desc (co-op/distributor path).
# Sorted longest-first at runtime so the most specific prefix wins.
_MPN_PREFIX_MAP: dict[str, dict] = {
    # Frigidaire / Electrolux (longer prefix beats generic)
    "PDSH": {"manufacturer_name": "Rheem Manufacturing",           "brand_name": "FRIGIDAIRE®"},
    "PDWF": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    "FGID": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    "FFID": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    "FGHD": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    # GE Profile (GE Appliances, Haier subsidiary)
    "PDD":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    "PTD":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    "PEP":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    # GE Cafe (GE Appliances, Haier subsidiary)
    "CHP":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Café™"},
    # Whirlpool dishwashers (WDTS before WDT)
    "WDTS": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    "WDT":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    "WDF":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    # Maytag (Whirlpool sub-brand)
    "MDB":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    "MHW":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    "MED":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    # KitchenAid (Whirlpool sub-brand) — 4-char before 3-char KDT
    "KDTE": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    "KDTM": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    "KDFE": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    # Amana (Whirlpool sub-brand)
    "ADB":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Amana®"},
    "NTW":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Amana®"},
    # Speed Queen / Alliance Laundry (DC5 before any DC*)
    "DC5":  {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "DR":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "DV":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "TV":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "TR":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    # DEWALT
    "DCF":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCD":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCS":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCK":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCB":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
}

# Checked FIRST in normalize_manufacturer — a known prefix beats any supplier name or LLM.
# Dict insertion order: longer/more-specific prefixes come first to avoid early short-prefix match.
_MPN_PREFIXES: dict[str, dict] = {
    # Frigidaire family (Rheem OEM) — 4-char before any shorter
    "PDSH": {"manufacturer_name": "Rheem Manufacturing",           "brand_name": "FRIGIDAIRE®"},
    "FGID": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    "FFID": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    "FGHD": {"manufacturer_name": "Electrolux Home Products",       "brand_name": "FRIGIDAIRE®"},
    # GE Profile / CAFE (GE Appliances, Haier subsidiary) — 3-char before any 2-char PD
    "PDD":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    "PTD":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    "PEP":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Profile™"},
    "CHP":  {"manufacturer_name": "GE Appliances",                  "brand_name": "GE Café™"},
    # Whirlpool — 4-char WDTS before 3-char WDT
    "WDTS": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    "WDT":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    "WDF":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    "WRS":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Whirlpool®"},
    # KitchenAid (Whirlpool sub-brand) — 4-char before any shorter KD prefix
    "KDTE": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    "KDTM": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    "KDFE": {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "KitchenAid®"},
    # Maytag (Whirlpool sub-brand)
    "MDB":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    "MHW":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    "MED":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Maytag®"},
    # Amana (Whirlpool sub-brand)
    "ADB":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Amana®"},
    "NTW":  {"manufacturer_name": "Whirlpool Corporation",          "brand_name": "Amana®"},
    # Speed Queen / Alliance Laundry — DC5 (3-char) before DR/DV (2-char)
    "DC5":  {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "DR":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "DV":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "TV":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    "TR":   {"manufacturer_name": "Alliance Laundry Systems LLC",   "brand_name": "Speed Queen®"},
    # DEWALT (Stanley Black & Decker)
    "DCF":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCD":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCK":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCB":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DCS":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    "DWE":  {"manufacturer_name": "Stanley Black & Decker",         "brand_name": "DeWALT®"},
    # Milwaukee Tool
    "M18":  {"manufacturer_name": "Milwaukee Tool",                 "brand_name": "Milwaukee®"},
    "M12":  {"manufacturer_name": "Milwaukee Tool",                 "brand_name": "Milwaukee®"},
    # Makita (18V LXT = XP series, 40V XGT = GP series)
    "XPH":  {"manufacturer_name": "Makita",                         "brand_name": "Makita®"},
    "XDT":  {"manufacturer_name": "Makita",                         "brand_name": "Makita®"},
    "XFD":  {"manufacturer_name": "Makita",                         "brand_name": "Makita®"},
    "GFD":  {"manufacturer_name": "Makita",                         "brand_name": "Makita®"},
    # Diablo (Freud America)
    "DCB5": {"manufacturer_name": "Freud America, Inc",             "brand_name": "DIABLO®"},
    # NUVO® by SATCO (numeric-hyphenated SKUs: 62-xxxx, 64-xxxx, 65-xxxx)
    "62-":  {"manufacturer_name": "Satco Products, Inc",            "brand_name": "NUVO® by SATCO"},
    "64-":  {"manufacturer_name": "Satco Products, Inc",            "brand_name": "NUVO® by SATCO"},
    "65-":  {"manufacturer_name": "Satco Products, Inc",            "brand_name": "NUVO® by SATCO"},
    # Schumacher Electric — SL-series chargers/jump starters
    "SL":   {"manufacturer_name": "Schumacher Electric Corporation", "brand_name": "Schumacher®"},
    # J.M. Huber / ZIP System — specific MPN (Part_Manuf is "-" for this SKU)
    "1501767": {"manufacturer_name": "J.M. Huber Corporation",      "brand_name": "ZIP System®"},
}

# Terms that flag a purchasing co-op / distributor rather than a real product manufacturer.
# When present in Part_Manuf we skip canonical lookup and infer the brand from desc + MPN.
_NON_MANUFACTURER_TERMS = frozenset([
    "dealers cooperative",
    "distributors",
    "distributor",
    "wholesale",
    "supply co",
    "buying group",
    "co-op",
    "appde",
    "buying cooperative",
    "trade association",
    "members cooperative",
])

_MODEL = "openai/gpt-oss-120b"

# Compiled patterns for desc-keyword brand scan — checked when MPN prefix doesn't match.
# More-specific patterns (GE Profile) listed before generic ones (GE Appliances).
_DESC_BRAND_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r'\bge\s+profile\b', re.IGNORECASE),    "GE Appliances",       "GE Profile™"),
    (re.compile(r'\bge\s+caf[eé]\b', re.IGNORECASE),    "GE Appliances",       "GE Café™"),
    (re.compile(r'\bge\s+appliances?\b', re.IGNORECASE), "GE Appliances",       "GE®"),
    (re.compile(r'\bmaytag\b', re.IGNORECASE),           "Whirlpool Corporation", "Maytag®"),
    (re.compile(r'\bkitchenaid\b', re.IGNORECASE),       "Whirlpool Corporation", "KitchenAid®"),
    (re.compile(r'\bamana\b', re.IGNORECASE),            "Whirlpool Corporation", "Amana®"),
    (re.compile(r'\bjenn[- ]?air\b', re.IGNORECASE),     "Whirlpool Corporation", "JennAir®"),
]


def _desc_brand_scan(part_desc: str) -> dict | None:
    """Return {manufacturer_name, brand_name} if the description names a known sub-brand."""
    if not part_desc:
        return None
    for pattern, mfr, brand in _DESC_BRAND_PATTERNS:
        if pattern.search(part_desc):
            return {"manufacturer_name": mfr, "brand_name": brand}
    return None


def _is_non_manufacturer(name: str) -> bool:
    name_lower = name.lower()
    return any(term in name_lower for term in _NON_MANUFACTURER_TERMS)


def _infer_brand_from_desc(part_desc: str, mpn: str, existing_brand: str = "") -> dict:
    """
    Resolve manufacturer/brand when Part_Manuf is a purchasing co-op.
    1. MPN prefix match (deterministic)
    2. existing_brand canonical lookup
    3. Groq LLM inference (with cache to avoid re-burning quota)
    """
    # 0. MPN prefix — sorted longest-first so PDSH beats PD, WDTS beats WDT
    if mpn:
        mpn_upper = mpn.upper()
        for prefix in sorted(_MPN_PREFIX_MAP, key=len, reverse=True):
            if mpn_upper.startswith(prefix):
                result = dict(_MPN_PREFIX_MAP[prefix])
                result["_brand_resolution_method"] = "mpn_prefix_lookup"
                return result

    # 0.5. Part_Desc keyword scan — catches GE Profile, Maytag, etc. before LLM
    desc_hit = _desc_brand_scan(part_desc)
    if desc_hit:
        desc_hit["_brand_resolution_method"] = "desc_keyword"
        return desc_hit

    # 1. Use existing brand column
    if existing_brand:
        eb_lower = existing_brand.lower()
        if eb_lower in MANUFACTURER_CANONICAL:
            result = dict(MANUFACTURER_CANONICAL[eb_lower])
            result["_brand_resolution_method"] = "brand_column_lookup"
            return result
        for key, val in MANUFACTURER_CANONICAL.items():
            if key and (key in eb_lower or eb_lower in key):
                result = dict(val)
                result["_brand_resolution_method"] = "brand_column_lookup"
                return result

    # 2. LLM inference (cache-first)
    from unihack import llm_cache
    cache_key = f"{part_desc}::{mpn}::{existing_brand}"
    cached = llm_cache.get("mfr_infer", cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"manufacturer_name": "", "brand_name": "", "_brand_resolution_method": "unknown"}

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        user_content = f"Part number: {mpn}\nProduct description: {part_desc}"
        if existing_brand:
            user_content += f"\nKnown brand hint: {existing_brand}"
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=800,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a product database expert. Given a product part number and description, "
                        "identify the actual manufacturer (company that made it) and the consumer-facing brand. "
                        'Reply with valid JSON only: {"manufacturer_name": "...", "brand_name": "..."}'
                    ),
                },
                {"role": "user", "content": user_content},
            ],
        )
        if hasattr(response, "usage") and response.usage:
            llm_cache.record_usage(response.usage.total_tokens)
        raw = response.choices[0].message.content.strip()
        m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if not m:
            result = {"manufacturer_name": "", "brand_name": "", "_brand_resolution_method": "unknown"}
            llm_cache.set("mfr_infer", cache_key, result)
            return result
        data = json.loads(m.group())
        inferred_brand = data.get("brand_name", "").strip()
        inferred_mfr = data.get("manufacturer_name", "").strip()

        for lookup_key in [inferred_brand.lower(), inferred_mfr.lower()]:
            if lookup_key and lookup_key in MANUFACTURER_CANONICAL:
                result = dict(MANUFACTURER_CANONICAL[lookup_key])
                result["_brand_resolution_method"] = "llm_inferred"
                llm_cache.set("mfr_infer", cache_key, result)
                return result

        result = {
            "manufacturer_name": inferred_mfr,
            "brand_name": inferred_brand,
            "_brand_resolution_method": "llm_inferred",
        }
        llm_cache.set("mfr_infer", cache_key, result)
        return result
    except Exception:
        return {"manufacturer_name": "", "brand_name": "", "_brand_resolution_method": "unknown"}


def parse_part_manuf(raw: str) -> dict:
    """'Freud Inc (2435)' → {name: 'Freud Inc', code: '2435'}"""
    if not raw or not raw.strip():
        return {"name": "", "code": ""}
    m = re.match(r"^(.+?)\s*\((\w+)\)\s*$", raw.strip())
    if m:
        return {"name": m.group(1).strip(), "code": m.group(2).strip()}
    return {"name": raw.strip(), "code": ""}


def normalize_manufacturer(
    raw_part_manuf: str,
    part_desc: str = "",
    mpn: str = "",
    existing_brand: str = "",
) -> dict:
    """
    Resolution order:
      0. MPN prefix (most reliable)
      1. Co-op/distributor check → infer from desc+MPN
      2. If existing_brand hints a sub-brand, prefer it
      3. Numeric code lookup
      4. Name lookup
      5. Partial name match
      6. Title-case fallback
    """
    parsed = parse_part_manuf(raw_part_manuf)
    code_key = parsed["code"].lower()
    name_key = parsed["name"].lower()

    # 0. MPN prefix — checked before anything else
    if mpn:
        mpn_upper = mpn.upper()
        for prefix, val in _MPN_PREFIXES.items():
            if mpn_upper.startswith(prefix):
                result = dict(val)
                result["_brand_resolution_method"] = "mpn_prefix"
                return result

    # 0.5. Part_Desc keyword scan — catches conglomerate sub-brands when MPN prefix doesn't match
    desc_hit = _desc_brand_scan(part_desc)
    if desc_hit:
        desc_hit["_brand_resolution_method"] = "desc_keyword"
        return desc_hit

    # 1. Co-op / distributor check
    if _is_non_manufacturer(parsed["name"]) or _is_non_manufacturer(parsed["code"]):
        return _infer_brand_from_desc(part_desc, mpn, existing_brand=existing_brand)

    # 2. existing_brand sub-brand hint (e.g. "NUVO" when Part_Manuf is Satco)
    if existing_brand:
        eb_lower = existing_brand.lower()
        if eb_lower in MANUFACTURER_CANONICAL:
            result = dict(MANUFACTURER_CANONICAL[eb_lower])
            result["_brand_resolution_method"] = "brand_hint"
            return result

    # 3. Numeric code
    if code_key and code_key in MANUFACTURER_CANONICAL:
        result = dict(MANUFACTURER_CANONICAL[code_key])
        result["_brand_resolution_method"] = "direct_lookup"
        return result

    # 4. Name
    if name_key and name_key in MANUFACTURER_CANONICAL:
        result = dict(MANUFACTURER_CANONICAL[name_key])
        result["_brand_resolution_method"] = "direct_lookup"
        return result

    # 5. Partial name match
    for key, val in MANUFACTURER_CANONICAL.items():
        if key and (key in name_key or name_key in key):
            result = dict(val)
            result["_brand_resolution_method"] = "direct_lookup"
            return result

    return {
        "manufacturer_name": parsed["name"].title() if parsed["name"] else "",
        "brand_name": "",
        "_brand_resolution_method": "unknown",
    }
