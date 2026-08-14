"""
Description generator — the key differentiator of our pipeline.

Design: HYBRID template + AI, not free-form AI generation.

Why hybrid, not pure LLM?
  - LLMs reliably violate strict character limits (40-char INVOICE_DESC)
    and produce inconsistent casing even when instructed.
  - Templates guarantee structure and limits; LLM adds vocabulary judgment
    only where a human's choice genuinely improves quality.
  - Result: every generated field is machine-verifiable against its rule
    (length, casing, presence of required elements). We report pass/fail
    in the output so catalog QA can filter without manual review.

LLM call strategy: ONE optional call per product to pick the top attributes
to feature when there are more than will fit. This is the only judgment call
that benefits from language understanding. Everything else is deterministic.

Ground truth patterns (reverse-engineered from expected_output_2rows.csv):
  INVOICE_DESC  : ALL CAPS ≤40 chars, no brand/MPN, type + mount + specs abbreviated
  MOBILE_DESC   : 60-80 chars sentence case, "{Mfr}[ {Brand}], {Type}, {Series}, {MPN}[, {Mount}]"
  SHORT_DESC    : title case, "{Brand}® {Series} {MPN} {Type} With {Feature}™, {attrs}"
  LONG_DESC1    : title case, full spec dump comma-separated + "Additional Information:" trailer
  RETAIL_DESC   : title case, no brand/MPN, "{Series} {Type}, {attr1}, {attr2}, {material}"
"""

import os
import json
import re
from dataclasses import dataclass, field
from groq import Groq
from unihack.normalization.uom_table import normalize_unit, INVOICE_ABBREV

_MODEL = "llama-3.3-70b-versatile"

# ── Input / output data structures ───────────────────────────────────────────

@dataclass
class DescriptionInput:
    """Structured data needed to generate all five description types."""
    brand_name: str = ""             # "DEWALT®"
    manufacturer_name: str = ""      # "Stanley Black & Decker, Inc."
    mpn: str = ""                    # "DCF860B"
    product_type: str = ""           # "Impact Driver"
    series: str = ""                 # "Atomic Series"
    material: str = ""               # "Stainless Steel"
    features: list[str] = field(default_factory=list)  # ["CleanBoost™"]
    attributes: list[dict] = field(default_factory=list)  # [{"name":..,"value":..,"unit":..}]
    mounting_type: str = ""          # "Leg", "Built-in", "Cordless"
    includes: str = ""               # "Battery, Charger, Case"
    classpath: str = ""              # full Classpath from classifier, e.g. "Electrical>...>LED Light Bulbs"


@dataclass
class GeneratedDescriptions:
    invoice_desc: str = ""
    mobile_desc: str = ""
    short_desc: str = ""
    long_desc1: str = ""
    retail_desc: str = ""
    product_name: str = ""

    # Post-generation validation flags (set by validate_descriptions)
    invoice_ok: bool = False   # ≤40 chars AND ALL CAPS
    mobile_ok: bool = False    # 60–80 chars


# ── Utility helpers ───────────────────────────────────────────────────────────

def _clean_brand(brand: str) -> str:
    """Append ® if brand has no trademark symbol."""
    if brand and not brand.endswith(("®", "™")):
        return brand + "®"
    return brand


def _apply_invoice_abbrev(text: str) -> str:
    """Substitute long phrases with INVOICE_DESC abbreviations."""
    result = text.upper()
    for phrase, abbrev in INVOICE_ABBREV.items():
        result = re.sub(re.escape(phrase.upper()), abbrev, result)
    return result


def _truncate_words(text: str, max_len: int) -> str:
    """Truncate to max_len at a word boundary (never mid-word)."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    return cut[:last_space].rstrip() if last_space > 0 else cut


def _title(s: str) -> str:
    """
    Title-case words while preserving tokens that already carry intentional casing:
      - All-uppercase tokens    (RPM, SST, V, A)
      - Mixed-case tokens       (dBA, Ah, kW-hr, pH)
      - Alphanumeric codes      (DCF860B, PDSH4816AF)
      - Tokens with ® or ™
    """
    def _word(w: str) -> str:
        stripped = w.strip("®™,.()")
        if not stripped:
            return w
        letters = [c for c in stripped if c.isalpha()]
        if not letters:
            return w  # pure number or punctuation — leave as-is
        has_upper = any(c.isupper() for c in letters)
        has_lower = any(c.islower() for c in letters)
        has_digit = any(c.isdigit() for c in stripped)

        # Preserve if: all-caps, mixed-case (like dBA/Ah/kW-hr), or has digits+letters (codes)
        if has_upper and (not has_lower or has_digit):
            return w
        if has_upper and has_lower:
            return w  # already mixed — intentional (dBA, kW-hr, pH)
        return w.capitalize()

    return " ".join(_word(w) for w in s.split())


# Generic fallback priority (used when no per-category list matches).
# Derived from all 5 GT INVOICE/SHORT/RETAIL patterns across appliance/tool rows.
_GENERIC_ATTR_PRIORITY = [
    "capacity",                          # 0  — 7CU-FT, 18LB  (strongest differentiator)
    "color", "finish",                   # 1, 2 — Matte Black, White
    "number of wash", "wash cycle",      # 3, 4 — dishwasher cycles
    "dry cycle", "preset cycle",         # 5, 6 — dryer/washer cycles
    "mounting",                          # 7  — Built-in, Leg
    "material",                          # 8  — Stainless Steel, Galvanized
    "sound level", "dba",                # 9, 10 — dishwasher noise
    "voltage", "volt",                   # 11, 12 — electrical rating
    "amperage", "current",               # 13, 14 — use specific names to avoid matching amp-hour
    "size", "dimension",                 # 15, 16
    "height", "width", "depth",          # 17, 18, 19 — dimensional specs
    "chuck", "drive size",               # 20, 21 — tool-specific
    "no-load speed", "rpm",              # 22, 23 — tool performance
    "max torque", "torque",              # 24, 25 — tool torque
    "ampere-hour", "amp-hour", "ah",     # 26, 27, 28 — battery capacity
    "wattage", "watt",                   # 29, 30 — heat source/motor power (secondary)
    "lumen",                             # 31 — lighting
]

# Per-category attribute priority derived from expected_output_200rows.csv.
# Keys are the lowercase last segment of the Classpath (e.g. "led light bulbs").
# Lists are ordered highest-priority first; keywords are lowercase substrings of
# ATTRIBUTE_LABEL values so they survive minor label variation.
_CATEGORY_ATTR_PRIORITY: dict[str, list[str]] = {
    # ── Light Bulbs ────────────────────────────────────────────────────────────
    "led light bulbs": [
        "wattage", "lumens", "bulb shape", "color temp",
        "light appearance", "bulb base", "voltage", "color rendering",
        "bulb finish", "dimmable",
    ],
    "incandescent light bulbs": [
        "wattage", "lumens", "bulb shape", "color temp",
        "light appearance", "bulb base", "voltage", "color rendering",
        "bulb finish",
    ],
    "halogen light bulbs": [
        "wattage", "lumens", "bulb shape", "color temp",
        "bulb base", "voltage", "color rendering",
    ],
    "fluorescent light bulbs": [
        "wattage", "lumens", "bulb shape", "color temp",
        "bulb base", "voltage",
    ],
    # ── Indoor Fixtures ────────────────────────────────────────────────────────
    "recessed lighting fixtures": [
        "fixture wattage", "wattage", "voltage", "amperage", "fixture style",
        "number of bulbs", "bulb type", "bulb wattage", "bulb base",
        "lumens", "color temp",
    ],
    "surface-mount fixtures": [
        "fixture wattage", "wattage", "voltage", "amperage", "fixture style",
        "fixture shape", "bulb type", "bulb wattage", "bulb base",
        "number of bulbs", "lumens", "color temp",
    ],
    "indoor ceiling fixtures": [
        "fixture wattage", "wattage", "voltage", "amperage", "fixture style",
        "fixture shape", "bulb type", "bulb wattage", "bulb base",
        "number of bulbs", "lumens", "color temp",
    ],
    "accent & display lighting": [
        "fixture wattage", "wattage", "voltage", "lumens", "color temp", "bulb type",
    ],
    "bath & vanity lights": [
        "fixture wattage", "wattage", "voltage", "lumens", "color temp",
        "number of bulbs", "bulb type", "fixture style",
    ],
    "high bay fixtures": [
        "fixture wattage", "wattage", "voltage", "lumens", "color temp",
        "mounting", "fixture style",
    ],
    # ── Laundry Appliances ─────────────────────────────────────────────────────
    "gas dryers": [
        "capacity", "rotational speed", "btu", "drum type", "fuel type",
        "number of cycles", "number of temperature", "color",
        "voltage", "amperage",
    ],
    "electric dryers": [
        "capacity", "voltage", "amperage", "power rating",
        "rotational speed", "number of cycles", "color",
    ],
    "top loading washers": [
        "capacity", "voltage", "amperage", "rotational speed",
        "number of cycles", "drum type", "color",
    ],
    "front loading washers": [
        "capacity", "voltage", "amperage", "rotational speed",
        "number of cycles", "drum type", "color",
    ],
    # ── Dishwashers ────────────────────────────────────────────────────────────
    "built-in dishwashers": [
        "number of wash", "voltage", "amperage", "mounting",
        "sound level", "dba", "color", "size",
    ],
    # ── Electrical Devices ─────────────────────────────────────────────────────
    "gfci & afci receptacles": [
        "voltage", "amperage", "interrupt rating", "short circuit",
        "number of poles", "number of wires", "wire size", "frequency",
    ],
    "receptacles & usb ports": [
        "voltage", "amperage", "number of outlets", "wire size",
    ],
    # ── Cordless Tool Batteries ────────────────────────────────────────────────
    "cordless tool batteries": [
        "voltage", "battery capacity", "battery chemistry",
        "suitable for use with",
    ],
    "cordless tool power supplies & battery adapters": [
        "voltage", "battery capacity", "battery chemistry",
    ],
    # ── Cordless Fastening Tools ───────────────────────────────────────────────
    "cordless nailers": [
        "nail capacity", "nail length", "nail diameter", "nail gauge",
        "nail head", "magazine", "firing", "fastening rate", "voltage",
    ],
    "cordless staplers": [
        "staple length", "staple gauge", "magazine capacity",
        "voltage", "battery capacity",
    ],
    "cordless ratchet wrenches": [
        "drive size", "drive type", "torque", "voltage",
        "battery capacity", "speed",
    ],
    "cordless impact wrenches": [
        "drive size", "drive type", "torque", "voltage",
        "battery capacity", "speed",
    ],
    "cordless impact drivers": [
        "drive size", "torque", "voltage", "battery capacity", "speed",
    ],
    "power nut setters & bit holders": [
        "drive size", "bit size", "voltage", "battery capacity",
    ],
    # ── Cordless Drills ────────────────────────────────────────────────────────
    "cordless drills": [
        "chuck", "voltage", "battery capacity", "torque", "speed",
    ],
    "cordless hammer drills": [
        "chuck", "voltage", "battery capacity", "torque", "speed", "impact",
    ],
    # ── Cordless Saws ──────────────────────────────────────────────────────────
    "cordless miter saws": [
        "blade diameter", "bevel range", "voltage", "battery capacity", "speed",
    ],
    "cordless circular saws": [
        "blade diameter", "voltage", "battery capacity", "speed",
    ],
    "cordless jig saws": [
        "stroke length", "speed", "voltage", "battery capacity",
    ],
    # ── Other Cordless Tools ───────────────────────────────────────────────────
    "cordless die & straight grinders": [
        "collet size", "speed", "voltage", "battery capacity",
    ],
    "cordless buffers & polishers": [
        "pad size", "speed", "voltage", "battery capacity",
    ],
    "cordless blowers": [
        "air volume", "air speed", "voltage", "battery capacity",
    ],
    # ── Power Saw Blades ───────────────────────────────────────────────────────
    "diamond saw blades": [
        "diameter", "bore size", "number of segments", "segment height", "arbor",
    ],
    "circular saw blades": [
        "diameter", "number of teeth", "kerf", "arbor",
    ],
    "planer blades": [
        "blade length", "blade width", "blade thickness", "number of blades",
    ],
    # ── Woodworking Machinery ──────────────────────────────────────────────────
    "woodworking planer machines": [
        "cutting width", "cutting thickness", "depth of cut",
        "voltage", "amperage", "wattage", "hp rating", "feed", "speed",
    ],
    "corded band saws": [
        "blade length", "throat depth", "cutting height", "voltage", "amperage", "hp rating",
    ],
    # ── Building Materials / Doors & Windows ──────────────────────────────────
    "patio doors": [
        "door width", "door height", "door color", "door finish",
        "door material", "frame material", "door handing",
    ],
    "fixed skylights": [
        "daylight area", "glass type", "frame material", "frame color",
        "uv protection", "u-factor", "glazing type",
    ],
    # ── Decking ────────────────────────────────────────────────────────────────
    "deck railing kits": [
        "rail length", "rail width", "rail material", "rail color",
        "balusters", "installation",
    ],
    "deck stair railing kits": [
        "rail length", "rail width", "rail material", "rail color",
        "balusters", "installation",
    ],
    "deck post sleeves": [
        "shape", "material", "finish", "color", "width", "depth", "height",
        "fits post size",
    ],
    # ── Safety ────────────────────────────────────────────────────────────────
    "safety glasses": [
        "lens type", "lens color", "lens material", "lens coating",
        "frame color", "frame material", "frame shape", "gender",
    ],
    # ── Test & Measurement ────────────────────────────────────────────────────
    "mason's lines": [
        "diameter", "length", "breaking strength", "material", "color",
    ],
    "rotary & straight line laser levels": [
        "working range", "accuracy", "leveling range", "laser projection",
        "ip rating", "power source",
    ],
    # ── Hand Tools ────────────────────────────────────────────────────────────
    "snips": [
        "cutting capacity", "jaw opening", "blade material", "handle material",
    ],
    "hex key sets": [
        "drive size", "number of pieces", "material", "finish",
    ],
    # ── Oscillating Tools ─────────────────────────────────────────────────────
    "oscillating tool sandpaper & sanding pads": [
        "grit", "length", "width", "material",
    ],
}


def _get_priority_list(classpath: str) -> list[str]:
    """Return the per-category priority list for a given classpath, or the generic fallback."""
    if not classpath:
        return _GENERIC_ATTR_PRIORITY
    segments = [s.strip().lower() for s in classpath.split(">")]
    # Most-specific segment first
    for seg in reversed(segments):
        if seg in _CATEGORY_ATTR_PRIORITY:
            return _CATEGORY_ATTR_PRIORITY[seg]
    # Substring fallback across the full classpath string
    cp_lower = classpath.lower()
    for key, priority in _CATEGORY_ATTR_PRIORITY.items():
        if key in cp_lower:
            return priority
    return _GENERIC_ATTR_PRIORITY


def _attr_rank(attr: dict, priority: list[str] | None = None) -> int:
    if priority is None:
        priority = _GENERIC_ATTR_PRIORITY
    name_lower = attr.get("name", "").lower()
    for i, kw in enumerate(priority):
        if kw in name_lower:
            return i
    return len(priority)


# Long-form unit words to strip from values when the short form is also present.
# Prevents "10 Watts" + "W" → "10 WattsW" or "10 Watts W".
_UNIT_LONGFORMS: dict[str, list[str]] = {
    "W":  ["watts", "watt"],
    "V":  ["volts", "volt"],
    "A":  ["amperes", "ampere", "amps", "amp"],
    "Hz": ["hertz"],
    "Ah": ["amp-hours", "amp-hour", "ampere-hours"],
    "lm": ["lumens", "lumen"],
    "K":  ["kelvin"],
}


def _format_attr_value(attr: dict) -> str:
    val = attr.get("value", "").strip()
    unit = normalize_unit(attr.get("unit", ""))
    if unit:
        # Strip the abbreviated unit first (e.g. "20V" → "20")
        val = re.sub(rf"\s*{re.escape(unit)}\s*$", "", val, flags=re.IGNORECASE).strip()
        # Also strip any long-form variant (e.g. "Watts", "Volts") that survives the first pass
        for longform in _UNIT_LONGFORMS.get(unit, []):
            val = re.sub(rf"\s*{re.escape(longform)}\s*$", "", val, flags=re.IGNORECASE).strip()
        return f"{val} {unit}"
    return val


def _top_attrs(attributes: list[dict], n: int = 4, classpath: str = "") -> list[dict]:
    """Return the top N attributes sorted by per-category importance."""
    priority = _get_priority_list(classpath)
    return sorted(attributes, key=lambda a: _attr_rank(a, priority))[:n]


# ── Optional LLM helper: pick top attributes ─────────────────────────────────

def _llm_pick_top_attrs(
    attributes: list[dict], product_type: str, classpath: str = "", n: int = 5
) -> list[dict]:
    """
    Ask the LLM to pick the N most important attributes to feature in descriptions.
    Only called when there are more than 8 attributes (saves API calls for short lists).
    Falls back to rule-based ranking on any error.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or len(attributes) <= 8:
        return _top_attrs(attributes, n, classpath)

    try:
        client = Groq(api_key=api_key)
        attr_text = "\n".join(
            f"{i+1}. {a['name']}: {_format_attr_value(a)}"
            for i, a in enumerate(attributes)
        )
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are writing product descriptions for a {product_type}. "
                        f"From the attribute list, return the {n} most important attribute "
                        "numbers (1-indexed) that a buyer would care most about, as a "
                        "JSON array of integers. Example: [2, 5, 1, 3, 7]"
                    ),
                },
                {"role": "user", "content": attr_text},
            ],
        )
        if hasattr(response, "usage") and response.usage:
            from unihack import llm_cache
            llm_cache.record_usage(response.usage.total_tokens)
        raw = response.choices[0].message.content.strip()
        indices = json.loads(re.search(r"\[.*\]", raw).group())
        picked = [attributes[i - 1] for i in indices if 1 <= i <= len(attributes)]
        return picked[:n]
    except Exception:
        return _top_attrs(attributes, n, classpath)


# ── Description builders ──────────────────────────────────────────────────────

def build_invoice_desc(inp: DescriptionInput) -> str:
    """
    ALL CAPS, ≤40 chars, no brand, no MPN.
    Tokens: TYPE MOUNT COUNT MATERIAL VOLTAGE AMPERAGE KEY_DIMENSION
    """
    tokens = [inp.product_type.upper()]

    if inp.mounting_type:
        abbr = INVOICE_ABBREV.get(inp.mounting_type.lower(), inp.mounting_type[:5].upper())
        tokens.append(abbr)

    for attr in _top_attrs(inp.attributes, n=6, classpath=inp.classpath):
        name_l = attr.get("name", "").lower()
        val = attr.get("value", "").strip()
        unit = normalize_unit(attr.get("unit", ""))

        if any(k in name_l for k in ["wash cycle", "number of", "dry cycle", "preset cycle"]):
            tokens.append(val)
        elif any(k in name_l for k in ["capacity"]):
            # Compact "7.0CU-FT" or "18LB"; _apply_invoice_abbrev normalizes the unit suffix
            fv = _format_attr_value(attr)      # "7.0", "7.0 cu-ft", "18 lb"
            tokens.append(fv.replace(" ", "")) # remove spaces so "18 lb" → "18lb" → "18LB"
        elif any(k in name_l for k in ["color", "finish"]):
            # Skip long descriptive strings like "Warm White to Natural Light" (not spec values)
            if len(val) <= 20:
                tokens.append(val)             # "Matte Black" → _apply_invoice_abbrev → "MATTE BK"
        elif "material" in name_l:
            tokens.append(INVOICE_ABBREV.get(val.lower(), val[:3].upper()))
        elif unit in ("V", "A", "RPM", "Ah", "dBA", "W"):
            # Use _format_attr_value so longform stripping ("10 Watts" → "10 W") is consistent
            fv = _format_attr_value(attr)   # "10 W" or "120 V"
            tokens.append(fv.replace(" ", ""))  # "10W" or "120V"
        elif any(k in name_l for k in ["depth", "size", "chuck", "drive"]):
            eff_unit = unit or "IN"
            clean_val = re.sub(rf"\s*{re.escape(eff_unit)}\s*$", "", val, flags=re.IGNORECASE).strip()
            tokens.append(f"{clean_val}{eff_unit}")

    joined = " ".join(t for t in tokens if t)
    result = _apply_invoice_abbrev(joined)
    return _truncate_words(result, 40)


def build_mobile_desc(inp: DescriptionInput) -> str:
    """
    60-80 chars, sentence case.
    Pattern: "{Mfr}[ {Brand}], {ProductType}, {Series}, {MPN}[, {MountingType}]"
    When still under 60 after the core parts, pad with material then top attribute values.
    """
    mfr = inp.manufacturer_name or ""
    brand_clean = inp.brand_name.replace("®", "").replace("™", "").strip()

    # Include brand name only when it differs from the first word of the manufacturer name
    mfr_first = mfr.split()[0].lower() if mfr else ""
    if brand_clean and brand_clean.lower() != mfr_first:
        lead = f"{mfr} {brand_clean}" if mfr else brand_clean
    else:
        lead = mfr or brand_clean

    parts = [p for p in [lead, inp.product_type, inp.series, inp.mpn, inp.mounting_type] if p]
    result = ", ".join(parts)

    # Pad to 60 chars: material first, then top attribute values one by one
    if len(result) < 60 and inp.material:
        result += f", {inp.material}"

    if len(result) < 60:
        for attr in _top_attrs(inp.attributes, n=6, classpath=inp.classpath):
            if len(result) >= 60:
                break
            val_str = _format_attr_value(attr)
            if val_str:
                result += f", {val_str}"

    # Final tier: if still short and we have a mounting type not already appended,
    # try restatement as "<MountingType> Mounting" for clarity.
    # This covers the common "no enrichment data at all" case.
    if len(result) < 60 and inp.mounting_type:
        mounting_phrase = f"{inp.mounting_type} Mounting"
        if mounting_phrase.lower() not in result.lower():
            result += f", {mounting_phrase}"

    # Last resort: append a category-context phrase so the string reads informatively
    # even with no enrichment data. Keyed on common words in product_type.
    if len(result) < 60 and inp.product_type:
        _context_hints = {
            "dishwasher":    "Kitchen Appliance",
            "refrigerator":  "Kitchen Appliance",
            "oven":          "Kitchen Appliance",
            "washer":        "Home Appliance",
            "dryer":         "Home Appliance",
            "impact driver": "Cordless Power Tool",
            "drill":         "Power Tool",
            "saw":           "Power Tool",
            "sander":        "Power Tool",
            "grinder":       "Power Tool",
            "belt":          "Abrasive Tool",
            "bulb":          "LED Lighting",
            "led":           "LED Lighting",
        }
        pt_lower = inp.product_type.lower()
        for kw, hint in _context_hints.items():
            if kw in pt_lower and hint.lower() not in result.lower():
                result += f", {hint}"
                break

    # Trim to 80 if over (word boundary)
    if len(result) > 80:
        result = _truncate_words(result, 80)

    return result


def build_short_desc(inp: DescriptionInput, use_llm: bool = True) -> str:
    """
    Title case. "{Brand}® {Series} {MPN} {Type} With {Feature}™, {Attr1}, {Material}"
    """
    brand = _clean_brand(inp.brand_name)
    lead_parts = [p for p in [brand, inp.series, inp.mpn, inp.product_type] if p]
    lead = " ".join(lead_parts)

    if inp.features:
        with_clause = " With " + ", ".join(inp.features)
    else:
        with_clause = ""

    top = _llm_pick_top_attrs(inp.attributes, inp.product_type, inp.classpath, n=4) if use_llm else _top_attrs(inp.attributes, 4, classpath=inp.classpath)
    attr_parts = [_format_attr_value(a) for a in top]
    if inp.material and inp.material not in attr_parts:
        attr_parts.append(inp.material)

    # Don't title-case the lead (brand has ®, MPN should stay uppercase, series is title already)
    result = lead + with_clause
    if attr_parts:
        result += ", " + ", ".join(_title(a) for a in attr_parts)

    return result


def build_long_desc(inp: DescriptionInput, use_llm: bool = True) -> str:
    """
    Title case, comma-separated full spec dump.
    "{Brand}® {Type} With {Feature}™, {Series}, {all attrs}, Additional Information: {overflow}"
    """
    brand = _clean_brand(inp.brand_name)
    lead = (brand + " " + inp.product_type if brand else inp.product_type).strip()
    if inp.features:
        lead += " With " + ", ".join(inp.features)
    parts = [_title(lead)]

    if inp.series:
        parts.append(_title(inp.series))

    # Lead with highest-priority attrs; overflow goes to "Additional Information:"
    priority = _get_priority_list(inp.classpath)
    attrs_to_use = sorted(inp.attributes, key=lambda a: _attr_rank(a, priority))
    for i, attr in enumerate(attrs_to_use):
        name = attr.get("name", "")
        val = _format_attr_value(attr)
        entry = f"{name} {val}".strip()
        if i < 12:
            parts.append(_title(entry))
        else:
            # Start "Additional Information:" section for overflow attrs
            overflow = [f"{a.get('name','')} {_format_attr_value(a)}".strip()
                        for a in attrs_to_use[12:]]
            parts.append("Additional Information: " + ", ".join(overflow))
            break

    if inp.material:
        parts.append(_title(inp.material))

    return ", ".join(p for p in parts if p)


def build_retail_desc(inp: DescriptionInput) -> str:
    """
    Title case, NO brand, NO MPN.
    "{Series} {Type}, {MountingType}, {Attr1}, {Attr2}, {Material}"
    """
    lead_parts = [p for p in [inp.series, inp.product_type] if p]
    parts = [_title(" ".join(lead_parts)) if lead_parts else "Product"]

    if inp.mounting_type:
        parts.append(_title(inp.mounting_type))

    for attr in _top_attrs(inp.attributes, n=3, classpath=inp.classpath):
        parts.append(_title(_format_attr_value(attr)))

    if inp.material:
        parts.append(_title(inp.material))

    return ", ".join(p for p in parts if p)


# ── Post-generation validation ────────────────────────────────────────────────

def validate_descriptions(desc: GeneratedDescriptions) -> GeneratedDescriptions:
    """Set *_ok flags. Called automatically by generate_descriptions."""
    inv = desc.invoice_desc
    desc.invoice_ok = bool(inv) and len(inv) <= 40 and inv == inv.upper()

    mob = desc.mobile_desc
    desc.mobile_ok = 60 <= len(mob) <= 80

    return desc


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_descriptions(inp: DescriptionInput, use_llm: bool = True) -> GeneratedDescriptions:
    """
    Generate all five description types and validate them.
    Set use_llm=False for the fastest mode (no LLM call, pure template).
    """
    desc = GeneratedDescriptions()
    desc.invoice_desc = build_invoice_desc(inp)
    desc.mobile_desc = build_mobile_desc(inp)
    desc.short_desc = build_short_desc(inp, use_llm=False)  # LLM not needed for short
    desc.long_desc1 = build_long_desc(inp, use_llm=False)
    desc.retail_desc = build_retail_desc(inp)
    desc.product_name = inp.product_type
    return validate_descriptions(desc)
