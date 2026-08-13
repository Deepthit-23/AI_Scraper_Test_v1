"""
Product taxonomy reverse-engineered from the 200-row ground truth.

Each entry stores the full "classpath" string (matching GT format exactly) instead of
deriving it from 3 separate Dept/Class/Fine fields.  get_classpath() returns it directly;
get_dept_class_fine() splits the first three ">" segments for the output columns.

GT uses 4–5 level paths:
  "Tools & Equipment>Power Tools>Power Fastening Tools>Power Nailers>Cordless Nailers"
  "Electrical>Lamps & Lightings>Light Bulbs>LED Light Bulbs"
"""

TAXONOMY: dict[str, dict] = {

    # ── LED / Incandescent / Fluorescent / Halogen Bulbs ─────────────────────

    "LED Light Bulbs": {
        "classpath": "Electrical>Lamps & Lightings>Light Bulbs>LED Light Bulbs",
        "keywords": [
            "led filament", "led bulb", "led lamp", "led a19", "led a15", "led a21",
            "led par", "led mr", "led t8", "led t5", "led candelabra",
            "led spiral", "led r20", "led r30", "led br30", "led br40",
            "led med", "led st19", "led cand", "led b11", "led t9", "led edison",
        ],
        "product_types": ["LED Filament Bulb", "LED Bulb", "LED Lamp"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature", "Base Type", "Voltage Rating"],
    },
    "Incandescent Bulbs": {
        "classpath": "Electrical>Lamps & Lightings>Light Bulbs>Incandescent Light Bulbs",
        "keywords": [
            "incandescent bulb", "incandescent lamp", "halogen bulb", "halogen flood",
            "tungsten filament", "soft white bulb",
            "incan", "27k incan", "cand 27k",
        ],
        "product_types": ["Incandescent Light Bulb", "Halogen Light Bulb"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature", "Base Type"],
    },
    "Fluorescent Bulbs": {
        "classpath": "Electrical>Lamps & Lightings>Light Bulbs>Fluorescent Light Bulbs",
        "keywords": [
            "fluorescent bulb", "fluorescent lamp", "cfl bulb", "compact fluorescent",
            "t8 lamp", "t5 lamp", "pl lamp",
            "flor t12", "t12 flor", "flor t9", "t9 flor",
        ],
        "product_types": ["Fluorescent Bulb", "Compact Fluorescent Bulb"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature", "Base Type"],
    },
    "Halogen Bulbs": {
        "classpath": "Electrical>Lamps & Lightings>Light Bulbs>Halogen Light Bulbs",
        "keywords": [
            "halogen lamp", "mr16 halogen", "par halogen", "jc halogen",
            "halogen pin", "halogen t3", "halogen t4",
        ],
        "product_types": ["Halogen Light Bulb"],
        "expected_attributes": ["Wattage", "Lumens", "Base Type"],
    },

    # ── Indoor Lighting Fixtures ─────────────────────────────────────────────

    "Recessed Lighting": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Recessed Lighting>Recessed Lighting Fixtures",
        "keywords": [
            "downlight", "down light", "recessed light", "retrofit downlight", "canless downlight",
            "wafer downlight", "recessed fixture", "direct wire downlight", "led downlight",
        ],
        "product_types": [
            "Direct Wire Downlight", "Retrofit Downlight", "Canless Downlight",
            "Semi-Regressed Wafer Downlight", "Recessed Light Fixture",
        ],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature", "Trim Type"],
    },
    "Surface Mount Lighting": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Surface-Mount Fixtures",
        "keywords": [
            "cloud fixture", "wrap fixture", "surface mount fixture", "flush mount fixture",
            "surface-mount fixture", "flush mount", "led flush",
        ],
        "product_types": ["Cloud Fixture", "Wrap Fixture", "Surface-Mount Fixture"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature"],
    },
    "Indoor Ceiling Fixtures": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Indoor Ceiling Fixtures",
        "keywords": [
            "ceiling fixture", "indoor ceiling fixture", "ceiling mount light",
            "ceiling light", "led ceiling", "ceiling lt",
        ],
        "product_types": ["Fixture"],
        "expected_attributes": ["Wattage", "Voltage Rating", "Finish"],
    },
    "Accent Lighting": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Accent & Display Lighting",
        "keywords": [
            "connectable strip light", "display light strip", "under cabinet strip",
            "led strip light", "led strip",
        ],
        "product_types": ["Connectable Strip Light"],
        "expected_attributes": ["Wattage", "Voltage Rating"],
    },
    "Wraparound Lights": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Wraparound Lights",
        "keywords": [
            "wraparound light", "wrap around light", "industrial wraparound",
            "led wrap", "wrap lt",
        ],
        "product_types": ["Wrap Fixture"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature"],
    },
    "High Bay Lighting": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>High Bay Fixtures",
        "keywords": ["high bay fixture", "highbay fixture", "warehouse high bay", "highbay light", "high bay light"],
        "product_types": ["High Bay Fixture"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature"],
    },
    "Vanity Lights": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Bath & Vanity Lights",
        "keywords": ["vanity light", "bath light fixture", "bath vanity fixture"],
        "product_types": ["Vanity Light"],
        "expected_attributes": ["Wattage", "Voltage Rating", "Finish"],
    },
    "Tape Lighting": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Indoor Strip & Tape Lighting",
        "keywords": ["tape light", "led tape light", "led strip tape"],
        "product_types": ["Tape Light"],
        "expected_attributes": ["Wattage", "Color Temperature", "Length"],
    },
    "Panel Lights": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Panel & Troffer Light Fixtures",
        "keywords": ["flat panel light", "troffer fixture", "backlit flat panel", "flat panel", "led panel"],
        "product_types": ["Backlit Flat Panel"],
        "expected_attributes": ["Wattage", "Lumens", "Color Temperature"],
    },
    "Wall Sconces": {
        "classpath": "Electrical>Lamps & Lightings>Indoor Lighting>Wall Sconces",
        "keywords": ["wall sconce", "sconce fixture", "wall lt", "wall light fixture"],
        "product_types": ["Wall Sconce"],
        "expected_attributes": ["Wattage", "Voltage Rating", "Finish"],
    },
    "Headlamps": {
        "classpath": "Electrical>Lamps & Lightings>Portable & Temporary Lightings>Headlamps",
        "keywords": ["headlamp", "head lamp", "headlight flashlight", "headlight"],
        "product_types": ["Headlamp"],
        "expected_attributes": ["Lumens", "Battery Type"],
    },

    # ── Electrical Wiring / Devices ──────────────────────────────────────────

    "GFCI Receptacles": {
        "classpath": "Electrical>Wiring Devices>GFCI & AFCI Devices>GFCI & AFCI Receptacles",
        "keywords": [
            "gfci outlet", "afci outlet", "gfci receptacle", "ground fault outlet",
            "ground fault receptacle", "gfci tamper", "gfci wtr", "tamper resistant gfci",
            "15a outlet", "outlet", "gfci",
        ],
        "product_types": ["GFCI Outlet", "AFCI Outlet"],
        "expected_attributes": ["Amperage Rating", "Voltage Rating", "Color"],
    },
    "USB Outlets": {
        "classpath": "Electrical>Wiring Devices>Straight Blade Devices>Receptacles & USB Ports",
        "keywords": ["usb outlet", "usb receptacle", "usb charger outlet", "in-wall usb"],
        "product_types": ["USB In-Wall Charger Outlet"],
        "expected_attributes": ["Amperage Rating", "Voltage Rating"],
    },
    "Electrical Box Covers": {
        "classpath": "Electrical>Boxes & Enclosures>Electrical Boxes & Covers>Electrical Box Covers",
        "keywords": [
            "electrical box cover", "industrial surface cover", "gfci cover plate",
            "receptacle cover plate", "weatherproof cover",
            "box cover", "sq cover", "gfi box cover",
        ],
        "product_types": ["Industrial Surface Cover", "Electrical Box Cover"],
        "expected_attributes": ["Material", "Color"],
    },
    "Building Wires": {
        "classpath": "Electrical>Wires & Cables>Building Wires>Service Entrance & Underground Cables",
        "keywords": ["service entrance cable", "underground cable", "service entrance wire",
                     "entrance cable", "aluminum entrance"],
        "product_types": ["Entrance Cable"],
        "expected_attributes": ["Gauge", "Length", "Material"],
    },
    "Data Cables": {
        "classpath": "Electrical>Wires & Cables>Copper Data Cables",
        "keywords": ["cat5e cable", "cat6 cable", "cat 5 cable", "cat 6 cable", "data wire cable",
                     "cat5e wire", "cat5e"],
        "product_types": ["Low Voltage Wire Cable"],
        "expected_attributes": ["Length", "Gauge"],
    },
    "Battery Jump Starters": {
        "classpath": "Electrical>Batteries & Accessories>Battery Accessories>Battery Jump Starters",
        "keywords": ["battery jump starter", "jump starter pack", "jumpstart", "jump start"],
        "product_types": ["Battery Jump Starter"],
        "expected_attributes": ["Voltage Rating", "Amperage Rating"],
    },

    # ── Power Tools — Fastening ───────────────────────────────────────────────

    "Cordless Nailers": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Nailers>Cordless Nailers",
        "keywords": [
            "framing nailer", "finish nailer", "cordless nailer", "nailer kit",
            "angled nailer", "brad nailer", "nailer",
        ],
        "product_types": ["Framing Nailer", "Cordless Framing Nailer Kit", "Brushless Cordless Nailer"],
        "expected_attributes": ["Voltage Rating", "Nail Length", "Magazine Capacity"],
    },
    "Impact Drivers": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Wrenches & Ratchets>Cordless Impact Drivers",
        "keywords": ["cordless impact driver", "compact impact driver", "brushless impact driver",
                     "impact driver"],
        "product_types": ["Cordless High Torque Impact Driver", "Cordless Compact Impact Driver Kit"],
        "expected_attributes": ["Voltage Rating", "No-Load Speed", "Max Torque", "Battery Type"],
    },
    "Impact Wrenches": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Wrenches & Ratchets>Cordless Impact Wrenches",
        "keywords": ["impact wrench", "cordless impact wrench", "high torque impact",
                     "1/2\" impact", "3/4\" impact", "1/2 impact", "3/4 impact"],
        "product_types": ["Cordless High Torque Impact Wrench", "Subcompact Impact Wrench"],
        "expected_attributes": ["Voltage Rating", "Drive Size", "Max Torque", "Battery Type"],
    },
    "Cordless Ratchets": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Wrenches & Ratchets>Cordless Ratchet Wrenches",
        "keywords": [
            "cordless ratchet", "ratchet wrench", "extended reach ratchet", "sealed head ratchet",
            "ratchet", "rachet",
        ],
        "product_types": ["Ratchet", "Sealed Head Ratchet", "Cordless Extended Reach Ratchet"],
        "expected_attributes": ["Voltage Rating", "Drive Size", "No-Load Speed", "Battery Type"],
    },
    "Cordless Staplers": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Staplers & Riveters>Cordless Staplers",
        "keywords": ["cordless stapler", "brushless stapler", "stapler"],
        "product_types": ["Brushless Cordless Stapler"],
        "expected_attributes": ["Voltage Rating", "Staple Size"],
    },
    "Nut Drivers": {
        "classpath": "Tools & Equipment>Power Tools>Power Fastening Tools>Power Screwdrivers>Power Nut Setters & Bit Holders",
        "keywords": ["impact nut driver set", "magnetic nut driver set", "nut setter set"],
        "product_types": ["6-Piece Impact-Duty Magnetic Nut Driver Set"],
        "expected_attributes": ["Drive Size", "Piece Count"],
    },

    # ── Power Tools — Drills ──────────────────────────────────────────────────

    "Cordless Drills": {
        "classpath": "Tools & Equipment>Power Tools>Power Drills>Cordless Drills",
        "keywords": [
            "cordless drill", "drill driver kit", "subcompact drill", "compact drill driver",
            "multi-head drill", "drill driver", "drill",
        ],
        "product_types": ["Subcompact Brushless Drill/Driver", "Multi-Head Drill/Driver"],
        "expected_attributes": ["Voltage Rating", "No-Load Speed", "Chuck Size", "Max Torque"],
    },
    "Hammer Drills": {
        "classpath": "Tools & Equipment>Power Tools>Power Drills>Cordless Hammer Drills",
        "keywords": ["hammer drill", "rotary hammer", "sds drill", "sds-plus"],
        "product_types": ["Hammer Drill"],
        "expected_attributes": ["Voltage Rating", "No-Load Speed", "Chuck Size"],
    },

    # ── Power Tools — Saws ────────────────────────────────────────────────────

    "Miter Saws": {
        "classpath": "Tools & Equipment>Power Tools>Power Saws>Miter Saws>Cordless Miter Saws",
        "keywords": ["miter saw", "sliding miter saw", "compound miter saw", "dual bevel miter"],
        "product_types": [
            "Double Bevel Fixed Miter Saw", "Double Bevel Sliding Miter Saw",
            "Cordless Dual-Bevel Sliding Compound Miter Saw Kit",
        ],
        "expected_attributes": ["Voltage Rating", "Blade Diameter", "Bevel Range"],
    },
    "Circular Saws": {
        "classpath": "Tools & Equipment>Power Tools>Power Saws>Circular Saws>Cordless Circular Saws",
        "keywords": ["cordless circular saw", "circular saw kit", "circ saw"],
        "product_types": ["Circular Saw Kit"],
        "expected_attributes": ["Voltage Rating", "Blade Diameter"],
    },
    "Jig Saws": {
        "classpath": "Tools & Equipment>Power Tools>Power Saws>Jig Saws>Cordless Jig Saws",
        "keywords": ["cordless jig saw", "jigsaw kit", "cordless jigsaw", "jig saw"],
        "product_types": ["Jig Saw"],
        "expected_attributes": ["Voltage Rating", "Stroke Length"],
    },
    "Band Saws": {
        "classpath": "Tools & Equipment>Power Tools>Power Saws>Band Saws>Corded Band Saws",
        "keywords": ["band saw", "corded band saw", "portable band saw", "bandsaw"],
        "product_types": ["Bandsaw"],
        "expected_attributes": ["Voltage Rating", "Blade Speed", "Throat Size"],
    },

    # ── Power Tools — Blades ──────────────────────────────────────────────────

    "Diamond Blades": {
        "classpath": "Tools & Equipment>Power Tools>Power Saw Blades>Diamond Saw Blades",
        "keywords": [
            "diamond blade", "tile diamond blade", "diamond tile blade",
            "segmented diamond blade", "tile blade", "diamond",
        ],
        "product_types": ["Tile Diamond Blade"],
        "expected_attributes": ["Blade Diameter", "Arbor Size", "Material"],
    },
    "Circular Saw Blades": {
        "classpath": "Tools & Equipment>Power Tools>Power Saw Blades>Circular Saw Blades",
        "keywords": ["circular saw blade", "framing saw blade", "carbide circular blade",
                     "saw blade", "circ saw blade"],
        "product_types": ["Circular Saw Blade"],
        "expected_attributes": ["Blade Diameter", "Tooth Count", "Arbor Size"],
    },
    "Planer Blades": {
        "classpath": "Tools & Equipment>Power Tools>Power Saw Blades>Planer Blades",
        "keywords": [
            "planer blade", "planer knife", "reversible insert knife",
            "planer and jointer knife", "insert knife set", "planer knives",
        ],
        "product_types": ["Reversible Insert Knife", "Planer and Joint Knife"],
        "expected_attributes": ["Blade Length", "Blade Width", "Pack Quantity"],
    },
    "Hole Saws": {
        "classpath": "Tools & Equipment>Power Tools>Power Saw Blades>Hole Saws & Accessories>Hole Saw Sets",
        "keywords": ["hole saw kit", "hole dozer set", "hole saw set", "hole dozer", "quik-lock hole"],
        "product_types": ["Hole Saw Kit"],
        "expected_attributes": ["Diameter", "Material", "Piece Count"],
    },

    # ── Power Tools — Finishing ───────────────────────────────────────────────

    "Die Grinders": {
        "classpath": "Tools & Equipment>Power Tools>Power Finishing Tools>Power Grinders>Cordless Die & Straight Grinders",
        "keywords": ["die grinder", "right angle die grinder", "cordless die grinder",
                     "angle grinder"],
        "product_types": ["Right Angle Die Grinder", "Die Grinder"],
        "expected_attributes": ["Voltage Rating", "No-Load Speed", "Collet Size"],
    },
    "Oscillating Pads": {
        "classpath": "Tools & Equipment>Power Tools>Oscillating Tools>Oscillating Tool Sandpaper & Sanding Pads",
        "keywords": ["oscillating sanding pad", "hook and loop sanding pad", "abranet"],
        "product_types": ["Sanding Pad"],
        "expected_attributes": ["Size", "Grit", "Pack Quantity"],
    },
    "Dust Extractor Bags": {
        "classpath": "Tools & Equipment>Power Tools>Power Tool Accessories>Dust Collector Accessories",
        "keywords": ["paper bag", "dust bag", "dust extractor bag", "vacuum bag"],
        "product_types": ["Dust Bag", "Paper Dust Bag"],
        "expected_attributes": ["Compatibility", "Pack Quantity"],
    },
    "Cordless Polishers": {
        "classpath": "Tools & Equipment>Power Tools>Power Finishing Tools>Power Buffers & Polishers>Cordless Buffers & Polishers",
        "keywords": ["cordless polisher", "cordless buffer", "brushless cordless sander", "polisher"],
        "product_types": ["Brushless Cordless Sander"],
        "expected_attributes": ["Voltage Rating", "Orbits Per Minute"],
    },

    # ── Power Tool Accessories ────────────────────────────────────────────────

    "Cordless Tool Batteries": {
        "classpath": "Tools & Equipment>Power Tools>Power Tool Accessories>Cordless Tool Batteries",
        "keywords": ["ah battery", "lithium battery pack", "cordless battery pack", "battery", "starter kit"],
        "product_types": ["Battery", "Battery Pack"],
        "expected_attributes": ["Voltage Rating", "Battery Amp-Hours", "Battery Type"],
    },
    "Battery Chargers": {
        "classpath": "Tools & Equipment>Power Tools>Power Tool Accessories>Cordless Tool Battery Chargers",
        "keywords": [
            "rapid charger", "gangbox charger", "sequential charger", "multi-bay charger",
            "battery charger", "charger",
        ],
        "product_types": ["Gangbox Rapid Charger"],
        "expected_attributes": ["Voltage Rating", "Charge Time"],
    },
    "Tool Power Supplies": {
        "classpath": "Tools & Equipment>Power Tools>Power Tool Accessories>Cordless Tool Power Supplies & Battery Adapters",
        "keywords": ["power supply charger", "charger and power supply", "tool power supply", "power supply"],
        "product_types": ["Power Supply and Charger"],
        "expected_attributes": ["Voltage Rating", "Amperage Rating"],
    },
    "Tool Combo Kits": {
        "classpath": "Tools & Equipment>Power Tools>Power Tool Combination Kits",
        "keywords": [
            "drill driver combo kit", "2-tool combo kit", "brushless combo kit",
            "drill impact combo", "combo kit", "combo-kit", "combination kit",
        ],
        "product_types": ["Brushless Compact Drill/Driver and Impact Driver Combo Kit"],
        "expected_attributes": ["Voltage Rating", "Includes", "Battery Type"],
    },
    "Cordless Blowers": {
        "classpath": "Tools & Equipment>Power Tools>Cordless Tools>Cordless Blowers",
        "keywords": ["cordless blower", "precision blower", "brushless blower"],
        "product_types": ["Brushless Precision Blower"],
        "expected_attributes": ["Voltage Rating", "Air Volume"],
    },

    # ── Woodworking Machinery ─────────────────────────────────────────────────

    "Woodworking Planers": {
        "classpath": "Tools & Equipment>Woodworking Tools & Machinery>Woodworking Machinery>Woodworking Planer Machines",
        "keywords": [
            "benchtop planer", "thickness planer", "helical planer", "woodworking planer",
            "helical cutterhead planer", "planer",
        ],
        "product_types": ["Helical Cutterhead Planer", "Benchtop Helical Cutterhead Planer"],
        "expected_attributes": ["Amperage Rating", "Cutting Width", "Cutting Depth"],
    },

    # ── Hand Tools ────────────────────────────────────────────────────────────

    "Snips": {
        "classpath": "Tools & Equipment>Hand Tools>Snips & Shears>Snips",
        "keywords": ["tin snip", "aviation snip", "compound snip", "mini snip"],
        "product_types": ["Mini Snip", "Snip"],
        "expected_attributes": ["Length", "Cut Type"],
    },
    "Hex Key Sets": {
        "classpath": "Tools & Equipment>Hand Tools>Hex, Torx & Spline Keys>Hex Key Sets",
        "keywords": ["hex key set", "allen key set", "l-key set", "t-handle hex", "hex plus"],
        "product_types": ["L-Key Set", "Hex Key Set"],
        "expected_attributes": ["Piece Count"],
    },

    # ── Measurement & Layout ──────────────────────────────────────────────────

    "Laser Levels": {
        "classpath": "Test & Measurement>Measuring & Layout Tools>Levels>Rotary & Straight Line Laser Levels",
        "keywords": [
            "laser level", "line laser", "cross line laser", "spot laser level",
            "green laser level", "red laser level", "cross line",
        ],
        "product_types": [
            "Cross Line Laser Level", "Cross Line Laser", "Green Laser Level",
            "Cordless 5-Spot Green Line Laser", "3x360 Line Laser",
        ],
        "expected_attributes": ["Range", "Accuracy", "Power Source"],
    },
    "Mason Lines": {
        "classpath": "Test & Measurement>Measuring & Layout Tools>Marking & Layout Tools>Mason's Lines",
        "keywords": [
            "mason line", "braided mason line", "mason cord", "twisted mason line",
            "line reel", "line roll", "stringliner",
        ],
        "product_types": ["Braided Mason Line Reel", "Braided Mason Line Roll", "Twisted Mason Line Roll"],
        "expected_attributes": ["Length", "Diameter", "Color", "Material"],
    },

    # ── Safety ────────────────────────────────────────────────────────────────

    "Safety Glasses": {
        "classpath": "Safety>Eye Protection>Safety Glasses",
        "keywords": [
            "safety glasses", "safety eyewear", "protective eyewear",
            "safety spectacles", "vapor shield",
        ],
        "product_types": ["Safety Glass"],
        "expected_attributes": ["Lens Color", "Frame Material", "ANSI Rating"],
    },
    "Fire Extinguishers": {
        "classpath": "Safety>Fire Protection>Fire Extinguishers & Accessories>Fire Extinguishers",
        "keywords": ["fire extinguisher"],
        "product_types": ["Fire Extinguisher"],
        "expected_attributes": ["Fire Class", "Weight", "Discharge Time"],
    },

    # ── Laundry Appliances ────────────────────────────────────────────────────

    "Gas Dryers": {
        "classpath": "Appliances & Consumer Electronics>Laundry Appliances>Gas Dryers",
        "keywords": ["gas dryer"],
        "product_types": ["Gas Dryer", "Sanitizing Gas Dryer"],
        "expected_attributes": ["Capacity", "Energy Source", "Cycles", "Size"],
    },
    "Electric Dryers": {
        "classpath": "Appliances & Consumer Electronics>Laundry Appliances>Electric Dryers",
        "keywords": ["elect dryer", "electric dryer"],
        "product_types": ["Electric Dryer", "Sanitizing Electric Dryer"],
        "expected_attributes": ["Capacity", "Voltage Rating", "Cycles", "Size"],
    },
    "Top Load Washers": {
        "classpath": "Appliances & Consumer Electronics>Laundry Appliances>Top Loading Washers",
        "keywords": ["elect washer", "electric washer", "top load washer", "agitator washer", "washer", "speed queen washer"],
        "product_types": ["Electric Top Load Washer", "Residential Agitator Washer"],
        "expected_attributes": ["Capacity", "Voltage Rating", "Cycles", "Size"],
    },

    # ── Kitchen Appliances ────────────────────────────────────────────────────

    "Dishwashers": {
        "classpath": "Appliances & Consumer Electronics>Kitchen Appliances>Built-In Dishwashers",
        "keywords": ["dishwasher", "dish washer", "built-in dishwasher"],
        "product_types": ["Dishwasher", "Built-In Dishwasher"],
        "expected_attributes": [
            "Voltage Rating", "Amperage Rating", "Number of Wash Cycles", "Sound Level", "Size",
        ],
    },
    "Electric Cooktops": {
        "classpath": "Food Preparation Equipment & Supplies>Food Equipment>Cooking Equipment>Electric Cooktops",
        "keywords": ["electric cooktop", "radiant cooktop", "smoothtop cooktop", "cooktop"],
        "product_types": ["Built-In Cooktop", "Electric Cooktop"],
        "expected_attributes": ["Burner Count", "Voltage Rating", "Size"],
    },
    "Induction Cooktops": {
        "classpath": "Food Preparation Equipment & Supplies>Food Equipment>Cooking Equipment>Induction Cooktops",
        "keywords": ["induction cooktop", "induction range"],
        "product_types": ["Built-In Induction Cooktop"],
        "expected_attributes": ["Burner Count", "Voltage Rating", "Size"],
    },
    "Built-In Microwaves": {
        "classpath": "Food Preparation Equipment & Supplies>Food Equipment>Cooking Equipment>Built-In Microwaves",
        "keywords": ["built-in microwave", "microwave oven"],
        "product_types": ["Built-In Microwave"],
        "expected_attributes": ["Capacity", "Wattage", "Voltage Rating"],
    },
    "Beverage Coolers": {
        "classpath": "Food Preparation Equipment & Supplies>Bar Supplies>Beverage & Wine Coolers>Beverage Coolers",
        "keywords": ["beverage cooler", "beverage center", "drink cooler refrigerator"],
        "product_types": ["Tall Beverage Center", "Beverage Cooler"],
        "expected_attributes": ["Capacity", "Voltage Rating"],
    },
    "Wine Coolers": {
        "classpath": "Food Preparation Equipment & Supplies>Bar Supplies>Beverage & Wine Coolers>Wine Coolers",
        "keywords": ["wine cooler", "wine refrigerator", "wine chiller"],
        "product_types": ["Dual Zone Wine Cooler", "Wine Cooler"],
        "expected_attributes": ["Capacity", "Zones", "Voltage Rating"],
    },

    # ── Building Materials ────────────────────────────────────────────────────

    "Patio Doors": {
        "classpath": "Building Materials>Doors & Windows>Exterior Doors>Patio Doors",
        "keywords": [
            "patio door", "sliding patio door", "gliding patio door", "tempered patio door",
            "patio dr", "gliding door",
        ],
        "product_types": ["Sliding Patio Door", "Gliding Patio Door"],
        "expected_attributes": ["Width", "Height", "Material", "Glass Type"],
    },
    "Access Doors": {
        "classpath": "Building Materials>Doors & Windows>Exterior Doors>Access Doors",
        "keywords": ["attic access door", "access panel door"],
        "product_types": ["Attic Access Door"],
        "expected_attributes": ["Width", "Height", "Material"],
    },
    "Fixed Skylights": {
        "classpath": "Building Materials>Doors & Windows>Skylights>Fixed Skylights",
        "keywords": ["fixed skylight", "roof skylight", "skylt", "velux"],
        "product_types": ["Fixed Skylight"],
        "expected_attributes": ["Width", "Height", "Glass Type"],
    },
    "Deck Railing Kits": {
        "classpath": "Building Materials>Decking>Deck & Porch Railings>Deck Railing Kits",
        "keywords": ["t-rail kit", "rail kit railing", "deck rail kit", "aluminum rail kit", "baluster"],
        "product_types": ["T-Rail Kit", "Rail Kit"],
        "expected_attributes": ["Length", "Color", "Material"],
    },
    "Deck Stair Railings": {
        "classpath": "Building Materials>Decking>Deck Stairs>Deck Stair Railing Kits",
        "keywords": ["stair rail kit", "stair railing kit", "deck stair rail"],
        "product_types": ["Rail Kit"],
        "expected_attributes": ["Length", "Color", "Material"],
    },
    "Post Sleeves": {
        "classpath": "Building Materials>Decking>Deck Posts & Deck Sleeves>Deck Post Sleeves",
        "keywords": ["post sleeve", "deck post sleeve"],
        "product_types": ["Post Sleeve"],
        "expected_attributes": ["Length", "Size", "Color"],
    },
    "Support Posts": {
        "classpath": "Building Materials>Decking>Deck Posts & Deck Sleeves>Deck Posts",
        "keywords": ["support post", "deck post anchor"],
        "product_types": ["Support Post"],
        "expected_attributes": ["Length", "Size", "Color"],
    },
    "Thresholds": {
        "classpath": "Building Materials>Flooring>Floor Moulding & Trims>Thresholds",
        "keywords": ["threshold strip", "door threshold", "floor threshold", "threshold"],
        "product_types": ["Threshold"],
        "expected_attributes": ["Length", "Width", "Material", "Color"],
    },
    "Oriented Strand Board": {
        "classpath": "Building Materials>Lumber & Composites>Plywood>Oriented Strand Board (OSB)",
        "keywords": ["oriented strand board", "osb panel", "subfloor", "plusosb"],
        "product_types": ["Oriented Strand Board"],
        "expected_attributes": ["Length", "Width", "Thickness"],
    },
    "House Wraps": {
        "classpath": "Building Materials>House Wraps & Tapes>House Wraps",
        "keywords": ["house wrap", "rainscreen wrap", "rainscreen"],
        "product_types": ["Rainscreen"],
        "expected_attributes": ["Width", "Length"],
    },

    # ── Lawn / Garden ─────────────────────────────────────────────────────────

    "Gate Hardware": {
        "classpath": "Lawn, Garden & Patio>Fencing>Gate Openers & Hardware>Gate Latches & Slide Bolts",
        "keywords": ["gate latch", "gravity latch", "double gate latch"],
        "product_types": ["Gravity Latch"],
        "expected_attributes": ["Material", "Mounting"],
    },

    # ── Hardware ──────────────────────────────────────────────────────────────

    "Cabinet Hardware": {
        "classpath": "Hardware & Fasteners>Cabinet & Drawer Hardware>Cabinet Hardware>Cabinet Hardware Installation Templates",
        "keywords": ["cabinet hardware drilling jig", "hardware drilling template", "cabinet jig"],
        "product_types": ["Cabinet Hardware and Drilling Jig"],
        "expected_attributes": [],
    },

    # ── Fallback ──────────────────────────────────────────────────────────────

    "General Hardware": {
        "classpath": "Hardware>General Hardware>Miscellaneous",
        "keywords": [],
        "product_types": ["Product"],
        "expected_attributes": [],
    },
}


def get_classpath(category_key: str) -> str:
    """Return the full GT-format classpath for a category key."""
    e = TAXONOMY.get(category_key, TAXONOMY["General Hardware"])
    return e["classpath"]


def get_dept_class_fine(category_key: str) -> tuple[str, str, str]:
    """Split the classpath into (Dept, Class, Fine) — the first three '>'-separated segments."""
    cp = get_classpath(category_key)
    parts = cp.split(">")
    dept  = parts[0] if len(parts) > 0 else ""
    cls   = parts[1] if len(parts) > 1 else ""
    fine  = parts[2] if len(parts) > 2 else ""
    return dept, cls, fine


def all_category_keys() -> list[str]:
    return list(TAXONOMY.keys())


def taxonomy_prompt_text() -> str:
    """One-line-per-category text for embedding in LLM prompts."""
    lines = []
    for k in TAXONOMY:
        if k == "General Hardware":
            continue
        lines.append(f"  {k}: {get_classpath(k)}")
    return "\n".join(lines)
