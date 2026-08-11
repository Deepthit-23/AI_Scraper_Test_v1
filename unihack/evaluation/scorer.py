"""
Evaluation scorer: field-by-field comparison against expected_output_2rows.csv.

Honesty note: N=2 is too small for a real accuracy claim. We frame this as a
"sanity check" — a quick diagnostic to see if our pipeline is in the right
ballpark before scaling to the full 1000-row dataset. The report includes this
caveat explicitly, which the challenge brief itself endorses ("real data is
imperfect — say so").

Scoring tiers:
  EXACT  — character-perfect match after stripping trailing whitespace
  CLOSE  — ≥80% sequence similarity after normalizing case/punctuation
  PARTIAL— ≥50% similarity (output has the right gist, wrong format)
  MISS   — <50% similarity

Also checks character-limit compliance for INVOICE_DESC and MOBILE_DESC,
independent of ground truth (these rules apply to all 1000 rows).
"""

import csv
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Fields we score against ground truth (subset we can actually populate)
SCORED_FIELDS = [
    "MANUFACTURER_NAME",
    "BRAND_NAME",
    "MANUFACTURER_PART_NUMBER",
    "Classpath",
    "MOBILE_DESC",
    "INVOICE_DESC",
    "SHORT_DESC",
    "LONG_DESC1",
    "RETAIL_DESC",
    "Product Name",
]

# Format rules: field -> (min_len, max_len, required_case)
CHAR_LIMIT_RULES: dict[str, tuple] = {
    "INVOICE_DESC": (1, 40, "upper"),
    "MOBILE_DESC": (60, 80, "any"),
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    field: str
    expected: str
    got: str
    similarity: float
    tier: str   # "EXACT" | "CLOSE" | "PARTIAL" | "MISS"
    format_note: str = ""


@dataclass
class ProductScore:
    mpn: str
    field_results: list[FieldResult] = field(default_factory=list)
    char_limit_checks: dict = field(default_factory=dict)

    @property
    def exact_count(self) -> int:
        return sum(1 for f in self.field_results if f.tier == "EXACT")

    @property
    def close_count(self) -> int:
        return sum(1 for f in self.field_results if f.tier in ("EXACT", "CLOSE"))

    @property
    def total(self) -> int:
        return len(self.field_results)


# ── Scoring logic ─────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Lowercase, strip trademark symbols, collapse whitespace and punctuation."""
    s = re.sub(r"[®™,\.;\-\(\)]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _tier(sim: float, expected: str, got: str) -> str:
    if expected.strip() == got.strip():
        return "EXACT"
    if sim >= 0.80:
        return "CLOSE"
    if sim >= 0.50:
        return "PARTIAL"
    return "MISS"


def score_field(field_name: str, expected: str, got: str) -> FieldResult:
    sim = _similarity(expected, got)
    t = _tier(sim, expected, got)

    note = ""
    if field_name in CHAR_LIMIT_RULES:
        lo, hi, case = CHAR_LIMIT_RULES[field_name]
        if got and not (lo <= len(got) <= hi):
            note += f"len={len(got)} (want {lo}-{hi}); "
        if case == "upper" and got and got != got.upper():
            note += "not ALL CAPS; "

    return FieldResult(field_name, expected, got, sim, t, note.strip())


def check_char_limits(row: dict) -> dict:
    """Format-rule check for all rules, independent of ground truth."""
    results = {}
    for fname, (lo, hi, case) in CHAR_LIMIT_RULES.items():
        val = row.get(fname, "")
        length_ok = lo <= len(val) <= hi if val else False
        case_ok = (val == val.upper()) if (case == "upper" and val) else True
        results[fname] = {
            "value": val,
            "length": len(val),
            "length_ok": length_ok,
            "case_ok": case_ok,
            "pass": length_ok and case_ok,
        }
    return results


def score_product(mpn: str, expected_row: dict, our_row: dict) -> ProductScore:
    ps = ProductScore(mpn=mpn)
    for f in SCORED_FIELDS:
        exp = str(expected_row.get(f, "")).strip()
        got = str(our_row.get(f, "")).strip()
        ps.field_results.append(score_field(f, exp, got))
    ps.char_limit_checks = check_char_limits(our_row)
    return ps


# ── CSV loaders ───────────────────────────────────────────────────────────────

def load_ground_truth(path: str) -> dict[str, dict]:
    """Returns {mpn: row_dict} from the expected_output_2rows.csv file."""
    records: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mpn = (
                    row.get("Mfg_Part_Num")
                    or row.get("MANUFACTURER_PART_NUMBER", "")
                ).strip()
                if mpn:
                    records[mpn] = row
    except FileNotFoundError:
        pass
    return records


# ── Report printer ────────────────────────────────────────────────────────────

_TIER_ICON = {"EXACT": "✓", "CLOSE": "~", "PARTIAL": "≈", "MISS": "✗"}


def print_report(scores: list[ProductScore]) -> None:
    print("\n" + "=" * 65)
    print("EVALUATION REPORT  (N=2 sanity check, not an accuracy benchmark)")
    print("=" * 65)

    for ps in scores:
        exact_pct = ps.exact_count / ps.total * 100 if ps.total else 0
        close_pct = ps.close_count / ps.total * 100 if ps.total else 0
        print(f"\n── {ps.mpn}  |  exact={exact_pct:.0f}%  close={close_pct:.0f}%")

        for fr in ps.field_results:
            icon = _TIER_ICON[fr.tier]
            print(f"   [{icon}] {fr.field:<30}  sim={fr.similarity:.0%}  {fr.format_note}")
            if fr.tier not in ("EXACT",):
                # Show first 90 chars of expected vs got for context
                print(f"         EXP: {fr.expected[:90]}")
                print(f"         GOT: {fr.got[:90]}")

        print("\n   Char-limit checks:")
        for fname, chk in ps.char_limit_checks.items():
            icon = "✓" if chk["pass"] else "✗"
            print(f"   [{icon}] {fname}: len={chk['length']}  "
                  f"length_ok={chk['length_ok']}  case_ok={chk['case_ok']}")
            print(f"         Value: {chk['value'][:80]}")

    # Aggregate summary
    all_fields = [fr for ps in scores for fr in ps.field_results]
    total = len(all_fields)
    exact = sum(1 for f in all_fields if f.tier == "EXACT")
    close = sum(1 for f in all_fields if f.tier in ("EXACT", "CLOSE"))
    char_checks = [chk for ps in scores for chk in ps.char_limit_checks.values()]
    char_pass = sum(1 for c in char_checks if c["pass"])

    print("\n" + "=" * 65)
    print("AGGREGATE  (N=2 — diagnostic only)")
    print(f"  Exact match:          {exact}/{total}  ({exact/total*100:.0f}%)")
    print(f"  Close match (≥80%):   {close}/{total}  ({close/total*100:.0f}%)")
    print(f"  Char-limit pass:      {char_pass}/{len(char_checks)}")
    print()
    print("  NOTE: With N=2 any % figure has ±50 pp confidence interval.")
    print("  Run on the full 1000-row dataset for meaningful accuracy numbers.")
    print("=" * 65 + "\n")
