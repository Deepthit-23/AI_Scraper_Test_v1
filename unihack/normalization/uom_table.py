"""
Unit of Measure normalization.

We lack the official 161k-row LOV vocabulary file, so this table covers only
the UOMs we actually encounter across our five data categories: Power Tools,
Appliances, Lighting, Abrasives, and Decking/Building Materials.

Ground truth formatting rule: always "{number} {unit}" with a single space.
"""

# raw string (lowercase) -> approved abbreviation
UOM_TABLE: dict[str, str] = {
    # Length / dimension
    "inch": "in", "inches": "in", '"': "in", "in.": "in", "\"": "in",
    "foot": "ft", "feet": "ft", "ft.": "ft", "'": "ft",
    "millimeter": "mm", "millimeters": "mm", "mm": "mm",
    "centimeter": "cm", "centimeters": "cm",
    "meter": "m", "meters": "m",

    # Electrical
    "volt": "V", "volts": "V", "voltage": "V", "v": "V",
    "amp": "A", "amps": "A", "ampere": "A", "amperes": "A", "a": "A",
    "watt": "W", "watts": "W", "w": "W",
    "kilowatt": "kW", "kilowatts": "kW",
    "kilowatt-hour": "kW-hr", "kilowatt hour": "kW-hr", "kwh": "kW-hr", "kw-hr": "kW-hr",
    "amp-hour": "Ah", "amp hour": "Ah", "ampere-hour": "Ah", "ah": "Ah",

    # Sound
    "decibel": "dBA", "decibels": "dBA", "dba": "dBA", "db(a)": "dBA", "db": "dBA",

    # Speed
    "rpm": "RPM", "r.p.m.": "RPM", "revolutions per minute": "RPM",

    # Weight / mass
    "pound": "lb", "pounds": "lb", "lb.": "lb", "lbs": "lb", "lbs.": "lb",
    "ounce": "oz", "ounces": "oz", "oz.": "oz",

    # Torque
    "in-lb": "in-lb", "in·lb": "in-lb", "inch-pound": "in-lb", "inch pound": "in-lb",
    "ft-lb": "ft-lb", "ft·lb": "ft-lb", "foot-pound": "ft-lb", "foot pound": "ft-lb",
    "newton meter": "Nm", "newton-meter": "Nm", "nm": "Nm",

    # Light output / color
    "lumen": "lm", "lumens": "lm", "lm": "lm",
    "kelvin": "K",
    "color rendering index": "CRI", "cri": "CRI",

    # Temperature
    "fahrenheit": "°F", "celsius": "°C", "°f": "°F", "°c": "°C",

    # Count
    "each": "EA", "ea": "EA",
    "percent": "%", "pct": "%",

    # Time
    "hour": "hr", "hours": "hr", "hr.": "hr",
    "minute": "min", "minutes": "min",
    "second": "sec", "seconds": "sec",
}

# Ultra-short abbreviations used in INVOICE_DESC (ALL CAPS, ≤40 char budget)
INVOICE_ABBREV: dict[str, str] = {
    "stainless steel": "SST",
    "stainless": "SST",
    "built-in": "BLTLN",
    "built in": "BLTLN",
    "cordless": "CDLS",
    "corded": "CORD",
    "battery": "BATT",
    "brushless": "BSHLS",
    "brushed": "BSHD",
    "impact": "IMPCT",
    "driver": "DRVR",
    "drill": "DRL",
    "sander": "SNDR",
    "circular": "CIRC",
    "reciprocating": "RECIP",
    "multi-tool": "MTOOL",
}


def normalize_unit(raw: str) -> str:
    """Return the approved UOM abbreviation, or the original string if unknown."""
    if not raw:
        return ""
    return UOM_TABLE.get(raw.strip().lower(), raw.strip())


def format_measurement(value: str, unit: str) -> str:
    """Format as '{value} {unit}' with a single space. Returns just value if unit is blank."""
    uom = normalize_unit(unit)
    if not uom:
        return value.strip()
    return f"{value.strip()} {uom}"
