"""
Product taxonomy covering the categories actually present in Sample_1000_Items.csv.

We lack the official Unilog/Salsify taxonomy files, so this is reverse-engineered
from the data plus the two ground-truth examples. Classpath separator is ">" to match
the ground truth: "Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers"

Each entry has:
  - Dept / Class / Fine  (the three classpath levels)
  - keywords             (for fast rule-based pre-filter before spending an LLM call)
  - product_types        (first entry = default product_type for that category)
  - expected_attributes  (feeds into the validator — what fields should a full record have?)
"""

TAXONOMY: dict[str, dict] = {

    # ── TOOLS ──────────────────────────────────────────────────────────────────

    "Impact Drivers": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Impact Drivers",
        "keywords": ["impact driver", "impact wrench"],
        "product_types": ["Impact Driver", "Impact Wrench"],
        "expected_attributes": [
            "Voltage Rating", "No-Load Speed", "Max Torque", "Chuck Size",
            "Battery Type", "Battery Amp-Hours", "Tool Type", "Weight",
        ],
    },
    "Drills & Drivers": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Drills & Drivers",
        "keywords": ["drill", "driver", "hammer drill", "rotary hammer"],
        "product_types": ["Drill/Driver", "Drill", "Hammer Drill", "Rotary Hammer"],
        "expected_attributes": [
            "Voltage Rating", "No-Load Speed", "Chuck Size", "Max Torque",
            "Battery Type", "Battery Amp-Hours", "Tool Type", "Weight",
        ],
    },
    "Sanders & Grinders": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Sanders & Grinders",
        "keywords": ["sander", "grinder", "polisher", "orbital", "palm sander", "angle grinder"],
        "product_types": ["Sander", "Grinder", "Polisher", "Orbital Sander"],
        "expected_attributes": [
            "Voltage Rating", "Orbits Per Minute", "Pad Size", "Tool Type", "Weight",
        ],
    },
    "Saws": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Saws",
        "keywords": ["circular saw", "jig saw", "reciprocating saw", "track saw", "miter saw", "saw"],
        "product_types": ["Circular Saw", "Jig Saw", "Reciprocating Saw", "Track Saw", "Miter Saw"],
        "expected_attributes": [
            "Voltage Rating", "No-Load Speed", "Blade Diameter", "Tool Type", "Weight",
        ],
    },
    "Saw Blades": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Saw Blades",
        "keywords": ["saw blade", "blade", "carbide blade"],
        "product_types": ["Saw Blade", "Circular Saw Blade"],
        "expected_attributes": ["Blade Diameter", "Tooth Count", "Arbor Size", "Material"],
    },
    "Drill Bits & Accessories": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Drill Bits & Accessories",
        "keywords": ["drill bit", "bit set", "router bit", "forstner bit"],
        "product_types": ["Drill Bit", "Bit Set", "Router Bit"],
        "expected_attributes": ["Diameter", "Length", "Material", "Shank Size"],
    },
    "Abrasives": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Abrasives",
        "keywords": ["sanding belt", "sanding disc", "sandpaper", "abrasive", "grit"],
        "product_types": ["Sanding Belt", "Sanding Disc", "Sandpaper"],
        "expected_attributes": ["Grit", "Size", "Material", "Pack Quantity"],
    },
    "Batteries & Chargers": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Batteries & Chargers",
        "keywords": ["battery", "charger", "ah battery", "starter kit"],
        "product_types": ["Battery", "Charger", "Battery Kit"],
        "expected_attributes": ["Voltage Rating", "Battery Amp-Hours", "Battery Type", "Charge Time"],
    },
    "Tool Combo Kits": {
        "Dept": "Tools", "Class": "Power Tools & Accessories", "Fine": "Combo & Tool Sets",
        "keywords": ["combo kit", "tool kit", "tool set"],
        "product_types": ["Combo Kit", "Tool Set", "Tool Kit"],
        "expected_attributes": ["Voltage Rating", "Includes", "Battery Type", "Weight"],
    },
    "Hand Tools": {
        "Dept": "Tools", "Class": "Hand Tools & Equipment", "Fine": "Hand Tools",
        "keywords": ["wrench", "plier", "hammer", "screwdriver", "socket", "ratchet", "clamp", "level"],
        "product_types": ["Wrench", "Pliers", "Hammer", "Screwdriver"],
        "expected_attributes": [],
    },

    # ── BUILDING MATERIALS ───────────────────────────────────────────────────

    "Decking": {
        "Dept": "Building Materials", "Class": "Decking & Railing", "Fine": "Decking",
        "keywords": ["decking", "deck board", "composite deck"],
        "product_types": ["Deck Board", "Decking"],
        "expected_attributes": ["Length", "Width", "Thickness", "Color", "Material"],
    },
    "Railing": {
        "Dept": "Building Materials", "Class": "Decking & Railing", "Fine": "Railing",
        "keywords": ["railing", "rail", "baluster", "post cap", "post"],
        "product_types": ["Railing", "Rail", "Baluster", "Post"],
        "expected_attributes": ["Length", "Color", "Material"],
    },
    "PVC Trim": {
        "Dept": "Building Materials", "Class": "Trim & Molding", "Fine": "PVC Trim",
        "keywords": ["pvc trim", "trim board", "fascia", "soffit", "pvc"],
        "product_types": ["Trim Board", "Fascia", "Soffit", "PVC Trim"],
        "expected_attributes": ["Length", "Width", "Thickness", "Color"],
    },
    "Siding & Panels": {
        "Dept": "Building Materials", "Class": "Siding & Exterior", "Fine": "Siding",
        "keywords": ["siding", "panel", "lap siding", "shingle"],
        "product_types": ["Siding", "Panel", "Lap Siding"],
        "expected_attributes": ["Length", "Width", "Color", "Material"],
    },

    # ── APPLIANCES ──────────────────────────────────────────────────────────

    "Dishwashers": {
        "Dept": "Appliances & Consumer Electronics",
        "Class": "Kitchen Appliances",
        "Fine": "Built-In Dishwashers",
        "keywords": ["dishwasher", "dish washer"],
        "product_types": ["Dishwasher", "Built-In Dishwasher"],
        "expected_attributes": [
            "Voltage Rating", "Amperage Rating", "Number of Wash Cycles",
            "Sound Level", "Mounting Type", "Material", "Size", "Series",
        ],
    },
    "Refrigerators": {
        "Dept": "Appliances & Consumer Electronics",
        "Class": "Kitchen Appliances",
        "Fine": "Refrigerators",
        "keywords": ["refrigerator", "fridge", "freezer", "french door", "side-by-side"],
        "product_types": ["Refrigerator", "Freezer"],
        "expected_attributes": ["Voltage Rating", "Capacity", "Material", "Size"],
    },
    "Ranges & Cooktops": {
        "Dept": "Appliances & Consumer Electronics",
        "Class": "Kitchen Appliances",
        "Fine": "Ranges & Cooktops",
        "keywords": ["range", "cooktop", "oven", "stove"],
        "product_types": ["Range", "Cooktop", "Oven"],
        "expected_attributes": ["Voltage Rating", "Fuel Type", "Burner Count", "Size"],
    },
    "Washers & Dryers": {
        "Dept": "Appliances & Consumer Electronics",
        "Class": "Laundry Appliances",
        "Fine": "Washers & Dryers",
        "keywords": ["washer", "dryer", "laundry"],
        "product_types": ["Washer", "Dryer"],
        "expected_attributes": ["Voltage Rating", "Capacity", "Mounting Type"],
    },

    # ── ELECTRICAL ──────────────────────────────────────────────────────────

    "LED Bulbs": {
        "Dept": "Electrical", "Class": "Lighting", "Fine": "LED Bulbs",
        "keywords": ["led bulb", "led lamp", "bulb", "lamp", "led a19", "led par", "led mr", "cfl"],
        "product_types": ["LED Bulb", "LED Lamp", "Bulb"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature", "Base Type", "Voltage Rating"],
    },
    "Light Fixtures": {
        "Dept": "Electrical", "Class": "Lighting", "Fine": "Light Fixtures",
        "keywords": ["fixture", "chandelier", "pendant", "sconce", "ceiling light", "recessed light"],
        "product_types": ["Light Fixture", "Chandelier", "Pendant Light", "Sconce"],
        "expected_attributes": ["Wattage", "Voltage Rating", "Finish", "Number of Lights"],
    },
    "Outdoor Lighting": {
        "Dept": "Electrical", "Class": "Lighting", "Fine": "Outdoor Lighting",
        "keywords": ["outdoor light", "exterior light", "flood light", "path light", "post light"],
        "product_types": ["Outdoor Fixture", "Flood Light", "Path Light"],
        "expected_attributes": ["Wattage", "Voltage Rating", "IP Rating", "Finish"],
    },
    "Wiring & Devices": {
        "Dept": "Electrical", "Class": "Wiring & Connectivity", "Fine": "Wiring & Devices",
        "keywords": ["outlet", "switch", "receptacle", "wire", "cable", "conduit", "breaker"],
        "product_types": ["Outlet", "Switch", "Receptacle", "Wire", "Cable"],
        "expected_attributes": ["Voltage Rating", "Amperage Rating", "Color", "Material"],
    },

    # ── FALLBACK ─────────────────────────────────────────────────────────────

    "General Hardware": {
        "Dept": "Hardware", "Class": "General Hardware", "Fine": "Miscellaneous",
        "keywords": [],
        "product_types": ["Product"],
        "expected_attributes": [],
    },
}


def get_classpath(category_key: str) -> str:
    """Build ">"-separated classpath matching the ground truth format."""
    e = TAXONOMY.get(category_key, TAXONOMY["General Hardware"])
    return f"{e['Dept']}>{e['Class']}>{e['Fine']}"


def all_category_keys() -> list[str]:
    return list(TAXONOMY.keys())


def taxonomy_prompt_text() -> str:
    """One-line-per-category text for embedding in an LLM prompt."""
    return "\n".join(
        f"  {k}: {get_classpath(k)}"
        for k in TAXONOMY
        if k != "General Hardware"
    )
