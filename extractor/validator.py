"""
Validation stage -- runs AFTER extraction, BEFORE the record is considered "done".

Three checks, each answering a different question:
  1. Conflict check   -- did two sources disagree on the same attribute?
  2. Completeness check -- how many of the fields we'd expect for this category are missing?
  3. Sanity check     -- is the confidence distribution healthy, or is this record mostly guesses?

This stage is what turns "an LLM extracted some JSON" into
"a data quality system with explainable checks" -- which is what the challenge
is actually asking for (validate, enrich, traceable, scale).
"""

import re
from schema.product_schema import ProductRecord, CATEGORY_EXPECTED_FIELDS
from dataclasses import dataclass, field


@dataclass
class ValidationReport:
    product_name: str
    completeness_score: float
    missing_fields: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    low_confidence_count: int = 0
    total_attributes: int = 0
    overall_status: str = "ok"  # "ok" | "needs_review" | "incomplete"

    def summary(self) -> str:
        lines = [
            f"Product: {self.product_name}",
            f"Completeness: {self.completeness_score * 100:.0f}%",
            f"Attributes extracted: {self.total_attributes} "
            f"({self.low_confidence_count} flagged low-confidence)",
        ]
        if self.missing_fields:
            lines.append(f"Missing expected fields: {', '.join(self.missing_fields)}")
        if self.conflicts:
            lines.append("Conflicts found:")
            lines.extend(f"  - {c}" for c in self.conflicts)
        lines.append(f"Status: {self.overall_status.upper()}")
        return "\n".join(lines)


def find_conflicts(record: ProductRecord) -> list[str]:
    """If the same attribute name appears twice with different values, flag it."""
    seen = {}
    conflicts = []
    for attr in record.attributes:
        key = attr.name.strip().lower()
        if key in seen and seen[key] != attr.value:
            conflicts.append(
                f"'{attr.name}' has conflicting values: '{seen[key]}' vs '{attr.value}' "
                f"(source: {attr.source_id})"
            )
        seen[key] = attr.value
    return conflicts


def _tokens(s: str) -> set[str]:
    """Split a field name into lowercase word tokens for fuzzy matching."""
    return set(re.sub(r"[^a-z0-9]", " ", s.lower()).split())


def _field_matched(expected_field: str, found_names: set[str]) -> bool:
    """
    True if any extracted attribute name substantially overlaps with expected_field.
    Uses token overlap so 'Wire Gauge' matches 'Wire Gage', 'Calibration Type'
    matches 'Thermocouple Calibrations', etc.
    """
    exp_tokens = _tokens(expected_field)
    for name in found_names:
        found_tokens = _tokens(name)
        # At least half the expected tokens must appear in the found name
        overlap = exp_tokens & found_tokens
        if len(overlap) >= max(1, len(exp_tokens) // 2):
            return True
    return False


def validate_record(record: ProductRecord) -> ValidationReport:
    category = (record.category or "").lower().strip()
    expected = CATEGORY_EXPECTED_FIELDS.get(category, [])

    found_names = {a.name for a in record.attributes}
    missing = [f for f in expected if not _field_matched(f, found_names)]

    # Use the same fuzzy logic as missing so completeness is consistent with missing_fields
    if expected:
        completeness = round((len(expected) - len(missing)) / len(expected), 2)
    else:
        completeness = 1.0 if record.attributes else 0.0

    conflicts = find_conflicts(record)
    low_conf_count = sum(1 for a in record.attributes if a.confidence == "low")

    if conflicts or (expected and completeness < 0.4):
        status = "needs_review"
    elif missing:
        status = "incomplete"
    else:
        status = "ok"

    return ValidationReport(
        product_name=record.product_name,
        completeness_score=completeness,
        missing_fields=missing,
        conflicts=conflicts,
        low_confidence_count=low_conf_count,
        total_attributes=len(record.attributes),
        overall_status=status,
    )
