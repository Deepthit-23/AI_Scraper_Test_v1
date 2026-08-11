"""
Fractional inch formatting to match industrial product spec conventions.

Ground truth example: "50-1/4 in" not "50.25 in", "24-1/4 in D" not "24.25 in D".
The format is: {whole}-{fraction} in   (whole omitted if 0, dash omitted if no fraction)

We programmatically generate the full 1/64-to-63/64 lookup table rather than
shipping a static CSV file — simpler, no file I/O dependency, and correct by construction.
"""

import re
from math import gcd


def _build_fraction_table() -> tuple[dict, dict]:
    """
    Returns (decimal_to_frac, frac_to_decimal) lookup dicts.
    Covers all reduced fractions with denominator that's a power of 2, up to 64ths.
    e.g. 0.25 <-> "1/4",  0.0625 <-> "1/16",  0.03125 <-> "1/32"
    """
    d2f: dict[float, str] = {}
    f2d: dict[str, float] = {}
    for num in range(1, 64):
        denom = 64
        common = gcd(num, denom)
        rn, rd = num // common, denom // common
        frac_str = f"{rn}/{rd}"
        decimal = round(num / 64, 10)
        d2f[decimal] = frac_str
        f2d[frac_str] = decimal
    return d2f, f2d


_DECIMAL_TO_FRAC, _FRAC_TO_DECIMAL = _build_fraction_table()
_TOLERANCE = 1e-6


def decimal_to_fraction(value: float) -> str:
    """0.25 -> "1/4",  0.5 -> "1/2",  0.0 -> "" (no fraction for whole numbers)."""
    for dec, frac in _DECIMAL_TO_FRAC.items():
        if abs(value - dec) < _TOLERANCE:
            return frac
    return ""


def fraction_to_decimal(frac_str: str) -> float:
    """
    "1/4" -> 0.25.  Returns 0.0 on parse failure.
    Handles "3/4" but NOT "1-3/4" — use parse_dimension_string for compound forms.
    """
    return _FRAC_TO_DECIMAL.get(frac_str.strip(), 0.0)


def format_dimension(value_inches: float, include_unit: bool = True) -> str:
    """
    Format a decimal inch value to industrial standard:
      50.25  ->  "50-1/4 in"
      24.0   ->  "24 in"
      0.75   ->  "3/4 in"
      1.5    ->  "1-1/2 in"
    Set include_unit=False to get "50-1/4" without the " in" suffix.
    """
    whole = int(value_inches)
    remainder = round(value_inches - whole, 10)
    frac = decimal_to_fraction(remainder)

    if frac:
        formatted = f"{whole}-{frac}" if whole > 0 else frac
    elif abs(remainder) < _TOLERANCE:
        formatted = str(whole)
    else:
        # No clean 64th-inch fraction — fall back to decimal, strip trailing zeros
        formatted = f"{value_inches:g}"

    return f"{formatted} in" if include_unit else formatted


def parse_dimension_string(s: str) -> float:
    """
    Parse "50-1/4", "50.25", "1/2", "50-1/4 in", "50-1/4\"" -> float.
    Returns 0.0 on failure.
    """
    s = re.sub(r'\s*in\.?$|"$', "", s.strip())
    # "whole-frac" e.g. "50-1/4"
    m = re.match(r"^(\d+)-(\d+/\d+)$", s)
    if m:
        return int(m.group(1)) + fraction_to_decimal(m.group(2))
    # Pure fraction "1/4"
    if "/" in s:
        return fraction_to_decimal(s)
    # Decimal or integer
    try:
        return float(s)
    except ValueError:
        return 0.0
