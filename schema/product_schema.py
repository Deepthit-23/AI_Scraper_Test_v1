"""
This file defines the SHAPE of our output data.
Every product, no matter where it came from (PDF, webpage, image),
gets turned into this same structure.

Key idea: every single attribute carries its own confidence score
and a pointer back to the exact source text it came from.
This is what makes the output "traceable" and "explainable" --
a human (or judge) can always ask "why do you believe this?" and get an answer.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal


class Attribute(BaseModel):
    name: str = Field(..., description="Attribute name, e.g. 'Maximum Temperature'")
    value: str = Field(..., description="The extracted value, e.g. '175'")
    unit: Optional[str] = Field(None, description="Unit if applicable, e.g. 'degC'")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="How sure the model is about this value"
    )
    source_snippet: str = Field(
        ..., description="The exact sentence/phrase this value was extracted from"
    )
    source_id: str = Field(
        ..., description="Which source document/page this came from (traceability)"
    )
    needs_review: bool = Field(
        default=False, description="True if this should be flagged for a human to check"
    )


class ProductRecord(BaseModel):
    product_name: str
    category: Optional[str] = None
    manufacturer: Optional[str] = None
    model_numbers: list[str] = Field(default_factory=list)
    short_description: Optional[str] = None
    attributes: list[Attribute] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="All source_ids used")

    def completeness_score(self, expected_fields: list[str]) -> float:
        """Simple scale metric: what fraction of expected fields did we manage to fill?"""
        found = {a.name.lower() for a in self.attributes}
        if not expected_fields:
            return 1.0
        hits = sum(1 for f in expected_fields if f.lower() in found)
        return round(hits / len(expected_fields), 2)

    def flagged_for_review(self) -> list[Attribute]:
        return [a for a in self.attributes if a.confidence == "low" or a.needs_review]


# A category schema is just a list of attribute names we EXPECT for that category.
# This powers both validation (what's missing?) and enrichment (what should we look for?).
CATEGORY_EXPECTED_FIELDS = {
    "thermocouple": [
        "Maximum Temperature", "Minimum Temperature", "Calibration Type",
        "Wire Gauge", "Lead Length", "Insulation Material", "Response Time"
    ],
    "sensor": [
        "Measurement Range", "Accuracy", "Output Signal", "Operating Temperature",
        "Power Supply", "Housing Material", "IP Rating"
    ],
    "valve": [
        "Pressure Rating", "Material", "Connection Size", "Flow Coefficient (Cv)",
        "Temperature Range", "Actuation Type"
    ],
    # Unihack categories
    "power tools & accessories": [
        "Voltage Rating", "Battery Type", "Battery Amp-Hours", "Chuck Size",
        "Max Torque", "No-Load Speed", "Tool Type", "Includes", "Weight"
    ],
    "impact drivers": [
        "Voltage Rating", "No-Load Speed", "Max Torque", "Chuck Size",
        "Battery Type", "Battery Amp-Hours", "Tool Type", "Weight"
    ],
    "drills & drivers": [
        "Voltage Rating", "No-Load Speed", "Chuck Size", "Max Torque",
        "Battery Type", "Battery Amp-Hours", "Tool Type", "Weight"
    ],
    "dishwashers": [
        "Voltage Rating", "Amperage Rating", "Number of Wash Cycles",
        "Sound Level", "Mounting Type", "Material", "Size", "Series"
    ],
    "led bulbs": [
        "Wattage", "Lumens", "Color Temperature", "Base Type", "Voltage Rating"
    ],
    "abrasives": ["Grit", "Size", "Material", "Pack Quantity"],
}
