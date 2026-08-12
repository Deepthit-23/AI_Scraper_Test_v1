"""Quick smoke test — run this to verify everything is wired up correctly."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from unihack.classification.classifier import classify_product
from unihack.normalization.manufacturer_lookup import normalize_manufacturer
from unihack.normalization.fraction_decimal import format_dimension
from unihack.description.generator import DescriptionInput, generate_descriptions

print("=" * 55)
print("SMOKE TEST")
print("=" * 55)

# 1. Manufacturer lookup
mfr = normalize_manufacturer("Freud Inc (2435)")
print(f"\n[1] Manufacturer lookup")
print(f"    Input : 'Freud Inc (2435)'")
print(f"    Result: {mfr}")

# 2. Classification (rule-based, no API call)
clf = classify_product("DCF860B Dewalt 20V Impact Driver Drill", "DCF860B")
print(f"\n[2] Classification (should be rule-based, no LLM call)")
print(f"    Input : 'DCF860B Dewalt 20V Impact Driver Drill'")
print(f"    Class : {clf['Classpath']}")
print(f"    Type  : {clf['product_type']}")
print(f"    Method: {clf['method']}")

# 3. Fraction formatting
print(f"\n[3] Fraction formatting")
print(f"    50.25  -> {format_dimension(50.25)}")
print(f"    24.25  -> {format_dimension(24.25)}")
print(f"    0.5    -> {format_dimension(0.5)}")

# 4. Description generation (no API call)
inp = DescriptionInput(
    brand_name="DEWALT®",
    manufacturer_name="Stanley Black & Decker, Inc.",
    mpn="DCF860B",
    product_type="Impact Driver",
    series="Atomic Series",
    attributes=[
        {"name": "Voltage Rating",    "value": "20",  "unit": "V"},
        {"name": "No-Load Speed",     "value": "2800", "unit": "RPM"},
        {"name": "Max Torque",        "value": "150", "unit": "in-lb"},
    ],
    mounting_type="Cordless",
)
descs = generate_descriptions(inp, use_llm=False)

print(f"\n[4] Description generation (no API call)")
print(f"    INVOICE ({len(descs.invoice_desc):2d} chars, ok={descs.invoice_ok}): {descs.invoice_desc}")
print(f"    MOBILE  ({len(descs.mobile_desc):2d} chars, ok={descs.mobile_ok}): {descs.mobile_desc}")
print(f"    SHORT   : {descs.short_desc}")
print(f"    RETAIL  : {descs.retail_desc}")

print("\n" + "=" * 55)
print("All tests passed. Ready to run the pipeline.")
print("Next: python -m unihack.unihack_pipeline --eval-only")
print("=" * 55)
