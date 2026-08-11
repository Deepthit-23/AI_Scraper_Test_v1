"""
Product classifier: maps a raw Part_Desc to our taxonomy.

Design: two-stage approach to conserve Groq free-tier quota.
  Stage 1 — Rule-based keyword scoring (free, instant).
             If any category scores ≥2 keyword hits, we trust it and skip the LLM.
  Stage 2 — Groq LLM with tool-calling that forces the model to pick from our
             exact category_key enum. This prevents hallucinated categories and
             makes the output deterministic enough for batch processing.

One LLM call per ambiguous product, zero calls when keywords are decisive.
"""

import os
import json
from groq import Groq
from unihack.classification.taxonomy import TAXONOMY, get_classpath, all_category_keys, taxonomy_prompt_text

_MODEL = "llama-3.3-70b-versatile"


def _classification_tool(category_keys: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "classify_product",
            "description": "Classify a product into the correct taxonomy category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category_key": {
                        "type": "string",
                        "enum": category_keys,
                        "description": "The single best matching taxonomy category key.",
                    },
                    "product_type": {
                        "type": "string",
                        "description": (
                            "Normalized product type in title case "
                            "(e.g. 'Impact Driver', 'Dishwasher', 'Sanding Belt'). "
                            "Use one of the product_types listed for the chosen category if possible."
                        ),
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "How confident you are in the classification.",
                    },
                },
                "required": ["category_key", "product_type", "confidence"],
            },
        },
    }


def _rule_based_classify(part_desc: str) -> dict | None:
    """
    Keyword scoring. Returns a classification dict if any category scores ≥2 hits;
    otherwise returns None to signal the LLM should be used.

    Scoring multiple keyword hits (rather than just first match) avoids mis-firing
    on descriptions like "Impact Drill Driver" (would score both "Impact Drivers"
    and "Drills & Drivers" — we pick the higher scorer).
    """
    desc_lower = part_desc.lower()
    scores: dict[str, int] = {}
    for key, entry in TAXONOMY.items():
        if key == "General Hardware":
            continue
        score = sum(1 for kw in entry["keywords"] if kw in desc_lower)
        if score > 0:
            scores[key] = score

    if not scores:
        return None

    best_key = max(scores, key=lambda k: scores[k])
    best_score = scores[best_key]

    # Single-keyword match is enough when the keyword is specific (>= 7 chars).
    # Short keywords like "saw", "bit" need 2 hits to avoid false positives.
    best_keywords = TAXONOMY[best_key]["keywords"]
    long_kw_hit = any(
        kw in desc_lower and len(kw) >= 7
        for kw in best_keywords
    )
    if best_score < 2 and not long_kw_hit:
        return None

    entry = TAXONOMY[best_key]
    return {
        "category_key": best_key,
        "product_type": entry["product_types"][0],
        "Dept": entry["Dept"],
        "Class": entry["Class"],
        "Fine": entry["Fine"],
        "Classpath": get_classpath(best_key),
        "confidence": "high",
        "method": "rule",
    }


def classify_product(part_desc: str, mfg_part_num: str = "") -> dict:
    """
    Classify a raw product description into the taxonomy.

    Returns:
        {category_key, product_type, Dept, Class, Fine, Classpath, confidence, method}

    method="rule"  -> keyword match, no LLM call consumed
    method="llm"   -> Groq call used (ambiguous description)
    """
    rule_result = _rule_based_classify(part_desc)
    if rule_result:
        return rule_result

    # --- LLM classification ---
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        # Graceful degradation: return General Hardware if no API key
        entry = TAXONOMY["General Hardware"]
        return {
            "category_key": "General Hardware",
            "product_type": "Product",
            "Dept": entry["Dept"], "Class": entry["Class"], "Fine": entry["Fine"],
            "Classpath": get_classpath("General Hardware"),
            "confidence": "low",
            "method": "fallback_no_key",
        }

    client = Groq(api_key=api_key)
    keys = all_category_keys()

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a product taxonomy specialist for an industrial/retail distributor. "
                        "Classify the product into exactly one category from the allowed list. "
                        "Available categories:\n" + taxonomy_prompt_text()
                    ),
                },
                {
                    "role": "user",
                    "content": f"MPN: {mfg_part_num}\nDescription: {part_desc}",
                },
            ],
            tools=[_classification_tool(keys)],
            tool_choice={"type": "function", "function": {"name": "classify_product"}},
        )

        tool_call = response.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments)
        key = data.get("category_key", "General Hardware")
        if key not in TAXONOMY:
            key = "General Hardware"
        entry = TAXONOMY[key]

        return {
            "category_key": key,
            "product_type": data.get("product_type", entry["product_types"][0]),
            "Dept": entry["Dept"],
            "Class": entry["Class"],
            "Fine": entry["Fine"],
            "Classpath": get_classpath(key),
            "confidence": data.get("confidence", "medium"),
            "method": "llm",
        }

    except Exception as e:
        entry = TAXONOMY["General Hardware"]
        return {
            "category_key": "General Hardware",
            "product_type": "Product",
            "Dept": entry["Dept"], "Class": entry["Class"], "Fine": entry["Fine"],
            "Classpath": get_classpath("General Hardware"),
            "confidence": "low",
            "method": f"error:{e}",
        }
