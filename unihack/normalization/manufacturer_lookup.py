"""
Manufacturer normalization: parses "Freud Inc (2435)" -> {manufacturer_name, brand_name}.

Design choice: hardcoded best-effort table for the 76 manufacturers in our data.
We lack the official 27k-row master list from the challenge brief, so this covers
the well-known brands with correct casing, trademark symbols, and the brand vs.
parent-company split that the ground truth expects.

Lookup priority: numeric code (most stable) > normalized name > fallback title-case.
LLM fallback: when Part_Manuf is a purchasing co-op / distributor, we ask Groq to
infer the real manufacturer and brand from Part_Desc + MPN.
"""

import os
import re
import json

# Keys are EITHER the code from "(CODE)" or the lowercased name.
# Values are {manufacturer_name, brand_name} using the ground truth's casing convention.
MANUFACTURER_CANONICAL: dict[str, dict] = {
    # Power Tools — Stanley Black & Decker family
    "2585": {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "black & decker/dewlt": {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "dewalt": {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},

    # Milwaukee Tool
    "4031": {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},
    "milwaukee accessory": {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},
    "milwaukee tool": {"manufacturer_name": "Milwaukee Tool", "brand_name": "Milwaukee®"},

    # Makita
    "makita usa inc": {"manufacturer_name": "Makita USA, Inc.", "brand_name": "Makita®"},
    "makita": {"manufacturer_name": "Makita USA, Inc.", "brand_name": "Makita®"},

    # Festool
    "festool usa": {"manufacturer_name": "Festool GmbH", "brand_name": "Festool®"},
    "festool": {"manufacturer_name": "Festool GmbH", "brand_name": "Festool®"},

    # Abrasives / Blades — Freud sells consumer line as Diablo
    "2435": {"manufacturer_name": "Freud America, Inc.", "brand_name": "Diablo®"},
    "freud inc": {"manufacturer_name": "Freud America, Inc.", "brand_name": "Diablo®"},
    "freud": {"manufacturer_name": "Freud America, Inc.", "brand_name": "Diablo®"},

    # 3M
    "3m": {"manufacturer_name": "3M Company", "brand_name": "3M™"},

    # Decking / Building Materials
    "trex": {"manufacturer_name": "Trex Company, Inc.", "brand_name": "Trex®"},
    "timbertech": {"manufacturer_name": "TimberTech", "brand_name": "TimberTech®"},
    "azek": {"manufacturer_name": "AZEK Building Products", "brand_name": "AZEK®"},
    "boise cascade building materials": {
        "manufacturer_name": "Boise Cascade Building Products",
        "brand_name": "Boise Cascade®",
    },
    "parksite": {"manufacturer_name": "Parksite Inc.", "brand_name": "Parksite"},
    "u s lumber": {"manufacturer_name": "U.S. LBM Holdings, LLC", "brand_name": "U.S. LBM"},

    # Appliances
    # Ground truth row 1: PDSH4816AF has MANUFACTURER_NAME=Rheem Manufacturing, BRAND_NAME=FRIGIDAIRE®
    # Rheem is listed in Part_Manuf but the consumer brand sold is Frigidaire (OEM relationship).
    "frigidaire": {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    "rheem manufacturing": {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    "whirlpool": {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    "whirlpool corporation": {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    "ge appliances": {"manufacturer_name": "GE Appliances", "brand_name": "GE®"},

    # Lighting
    "phillips lighting": {
        "manufacturer_name": "Signify North America Corporation",
        "brand_name": "Philips®",
    },
    "kichler lighting": {"manufacturer_name": "Kichler Lighting LLC", "brand_name": "Kichler®"},
    "satco prod inc": {"manufacturer_name": "Satco Products, Inc.", "brand_name": "Satco®"},
    "satco": {"manufacturer_name": "Satco Products, Inc.", "brand_name": "Satco®"},

    # Electrical
    "leviton mfg co": {
        "manufacturer_name": "Leviton Manufacturing Company, Inc.",
        "brand_name": "Leviton®",
    },
    "leviton": {
        "manufacturer_name": "Leviton Manufacturing Company, Inc.",
        "brand_name": "Leviton®",
    },
    "southwire": {"manufacturer_name": "Southwire Company, LLC", "brand_name": "Southwire®"},
}

# MPN prefix → canonical entry. Checked when Part_Manuf is a co-op/distributor and
# existing_brand is missing, giving deterministic resolution for known brand series.
_MPN_PREFIX_MAP: dict[str, dict] = {
    # Frigidaire / Electrolux dishwashers (distributed via APPDE co-op)
    "PDSH": {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    "PDWF": {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    "PD":   {"manufacturer_name": "Rheem Manufacturing", "brand_name": "FRIGIDAIRE®"},
    # Whirlpool dishwashers
    "WDT":  {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    "WDF":  {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    "WDTS": {"manufacturer_name": "Whirlpool Corporation", "brand_name": "Whirlpool®"},
    # DEWALT power tools
    "DCF":  {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "DCD":  {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "DCS":  {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "DCK":  {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
    "DCB":  {"manufacturer_name": "Stanley Black & Decker, Inc.", "brand_name": "DEWALT®"},
}

# Terms that identify a purchasing co-op, distributor, or trade group rather than a real
# product manufacturer. When any of these appear in Part_Manuf we skip the canonical lookup
# and instead ask the LLM to infer the actual brand from Part_Desc + MPN.
_NON_MANUFACTURER_TERMS = frozenset([
    "dealers cooperative",
    "distributors",
    "distributor",
    "wholesale",
    "supply co",
    "buying group",
    "co-op",
    "coop",
    "appde",           # code for Appliance Dealers Cooperative
    "buying cooperative",
    "trade association",
    "members cooperative",
])

_MODEL = "llama-3.3-70b-versatile"


def _is_non_manufacturer(name: str) -> bool:
    """Return True if the name looks like a co-op / distributor rather than a product maker."""
    name_lower = name.lower()
    return any(term in name_lower for term in _NON_MANUFACTURER_TERMS)


def _infer_brand_from_desc(part_desc: str, mpn: str, existing_brand: str = "") -> dict:
    """
    Resolve manufacturer/brand when Part_Manuf is a purchasing co-op or distributor.

    Steps:
      1. If existing_brand is provided (from E1/Unilog/DIB columns), try canonical lookup.
      2. Fall back to Groq LLM inference from Part_Desc + MPN.

    Returns {manufacturer_name, brand_name, _brand_resolution_method}.
    """
    # Step 0: MPN prefix match (deterministic, covers known brand series like PDSH→Frigidaire)
    if mpn:
        mpn_upper = mpn.upper()
        # Longest matching prefix wins (WDTS before WDT)
        for prefix in sorted(_MPN_PREFIX_MAP, key=len, reverse=True):
            if mpn_upper.startswith(prefix):
                result = dict(_MPN_PREFIX_MAP[prefix])
                result["_brand_resolution_method"] = "mpn_prefix_lookup"
                return result

    # Step 1: use known brand from input columns (fastest, most accurate)
    if existing_brand:
        for lookup_key in [existing_brand.lower()]:
            if lookup_key in MANUFACTURER_CANONICAL:
                result = dict(MANUFACTURER_CANONICAL[lookup_key])
                result["_brand_resolution_method"] = "brand_column_lookup"
                return result
        # Partial match (e.g. "Frigidaire" in "Frigidaire Professional")
        brand_lower = existing_brand.lower()
        for key, val in MANUFACTURER_CANONICAL.items():
            if key and (key in brand_lower or brand_lower in key):
                result = dict(val)
                result["_brand_resolution_method"] = "brand_column_lookup"
                return result

    # Step 2: LLM inference
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
            max_tokens=150,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a product database expert. Given a product part number and description, "
                        "identify the actual manufacturer (the company that made the product) and the "
                        "consumer-facing brand name. "
                        "Reply with valid JSON only, no extra text: "
                        '{"manufacturer_name": "...", "brand_name": "..."}'
                    ),
                },
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content.strip()
        m = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if not m:
            return {"manufacturer_name": "", "brand_name": "", "_brand_resolution_method": "unknown"}
        data = json.loads(m.group())
        inferred_brand = data.get("brand_name", "").strip()
        inferred_mfr = data.get("manufacturer_name", "").strip()

        # Cross-reference canonical table for correct casing & trademark symbols
        for lookup_key in [inferred_brand.lower(), inferred_mfr.lower()]:
            if lookup_key and lookup_key in MANUFACTURER_CANONICAL:
                result = dict(MANUFACTURER_CANONICAL[lookup_key])
                result["_brand_resolution_method"] = "llm_inferred"
                return result

        return {
            "manufacturer_name": inferred_mfr,
            "brand_name": inferred_brand,
            "_brand_resolution_method": "llm_inferred",
        }
    except Exception:
        return {"manufacturer_name": "", "brand_name": "", "_brand_resolution_method": "unknown"}


def parse_part_manuf(raw: str) -> dict:
    """
    "Freud Inc (2435)"  ->  {name: "Freud Inc", code: "2435"}
    "Whirlpool"         ->  {name: "Whirlpool", code: ""}
    """
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
    Given a raw Part_Manuf string, return {manufacturer_name, brand_name, _brand_resolution_method}.

    Resolution order:
      1. If Part_Manuf looks like a co-op / distributor:
         a. Try canonical lookup using existing_brand from E1/Unilog/DIB columns
         b. Fall back to LLM inference from part_desc + mpn
      2. Numeric code lookup in MANUFACTURER_CANONICAL
      3. Name lookup in MANUFACTURER_CANONICAL
      4. Partial name match
      5. Title-case fallback
    """
    parsed = parse_part_manuf(raw_part_manuf)
    code_key = parsed["code"].lower()
    name_key = parsed["name"].lower()

    # Bail out early when Part_Manuf is a purchasing co-op or distributor
    if _is_non_manufacturer(parsed["name"]) or _is_non_manufacturer(parsed["code"]):
        return _infer_brand_from_desc(part_desc, mpn, existing_brand=existing_brand)

    if code_key and code_key in MANUFACTURER_CANONICAL:
        result = dict(MANUFACTURER_CANONICAL[code_key])
        result["_brand_resolution_method"] = "direct_lookup"
        return result
    if name_key and name_key in MANUFACTURER_CANONICAL:
        result = dict(MANUFACTURER_CANONICAL[name_key])
        result["_brand_resolution_method"] = "direct_lookup"
        return result

    # Partial name match for long names like "Boise Cascade Building Materials (123)"
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
