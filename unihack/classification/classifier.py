"""
Product classifier: maps a raw Part_Desc to the taxonomy.

Two-stage approach to conserve Groq free-tier quota (100k tokens/day):
  Stage 1 — Rule-based keyword scoring (free, instant).
  Stage 2 — Groq LLM tool-call (only for ambiguous descriptions).

LLM calls are cached in unihack/data/cache/llm_cache.json keyed on
"{part_desc}::{mpn}" so identical descriptions never hit Groq twice.

Keyword tie-breaking: when multiple categories score the same number of hits,
the one with the longest individual matching keyword wins (more specific wins).
"""

import os
import json
from groq import Groq
from unihack.classification.taxonomy import (
    TAXONOMY, get_classpath, get_dept_class_fine,
    all_category_keys, taxonomy_prompt_text,
)
from unihack import llm_cache

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
                            "Specific product type in title case "
                            "(e.g. 'LED Filament Bulb', 'Framing Nailer', 'Gas Dryer'). "
                            "Use one of the product_types listed for the chosen category if possible."
                        ),
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["category_key", "product_type", "confidence"],
            },
        },
    }


def _rule_based_classify(part_desc: str) -> dict | None:
    """
    Keyword scoring with tie-breaking: (score, max_keyword_len) compared lexicographically.
    Returns a classification dict if we have a confident match; None to fall through to LLM.
    """
    desc_lower = part_desc.lower()

    # Score each category: (hit_count, longest_matching_keyword_length)
    best_key = None
    best_score = 0
    best_max_len = 0

    for key, entry in TAXONOMY.items():
        if key == "General Hardware":
            continue
        hit_count = 0
        max_kw_len = 0
        for kw in entry["keywords"]:
            if kw in desc_lower:
                hit_count += 1
                max_kw_len = max(max_kw_len, len(kw))
        if hit_count == 0:
            continue
        # Prefer higher hit count; break ties with longer matching keyword
        if (hit_count, max_kw_len) > (best_score, best_max_len):
            best_key = key
            best_score = hit_count
            best_max_len = max_kw_len

    if best_key is None:
        return None

    # Accept the rule result only if confident:
    #   - 2+ keyword hits, OR
    #   - 1 hit with a long/specific keyword (≥ 6 chars)
    if best_score < 2 and best_max_len < 6:
        return None

    entry = TAXONOMY[best_key]
    dept, cls, fine = get_dept_class_fine(best_key)
    return {
        "category_key": best_key,
        "product_type": entry["product_types"][0],
        "Dept": dept, "Class": cls, "Fine": fine,
        "Classpath": get_classpath(best_key),
        "confidence": "high",
        "method": "rule",
    }


def classify_product(part_desc: str, mfg_part_num: str = "") -> dict:
    """
    Classify a raw product description.

    Returns {category_key, product_type, Dept, Class, Fine, Classpath, confidence, method}.
      method="rule"  — keyword match, zero Groq tokens spent
      method="llm"   — Groq call (or cache hit)
    """
    rule_result = _rule_based_classify(part_desc)
    if rule_result:
        return rule_result

    # --- LLM classification (cache-first) ---
    cache_key = f"{part_desc}::{mfg_part_num}"
    cached = llm_cache.get("classify", cache_key)
    if cached is not None:
        return cached

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        entry = TAXONOMY["General Hardware"]
        dept, cls, fine = get_dept_class_fine("General Hardware")
        return {
            "category_key": "General Hardware",
            "product_type": "Product",
            "Dept": dept, "Class": cls, "Fine": fine,
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
        dept, cls, fine = get_dept_class_fine(key)

        result = {
            "category_key": key,
            "product_type": data.get("product_type", entry["product_types"][0]),
            "Dept": dept, "Class": cls, "Fine": fine,
            "Classpath": get_classpath(key),
            "confidence": data.get("confidence", "medium"),
            "method": "llm",
        }
        if hasattr(response, "usage") and response.usage:
            llm_cache.record_usage(response.usage.total_tokens)
        llm_cache.set("classify", cache_key, result)
        return result

    except Exception as e:
        entry = TAXONOMY["General Hardware"]
        dept, cls, fine = get_dept_class_fine("General Hardware")
        return {
            "category_key": "General Hardware",
            "product_type": "Product",
            "Dept": dept, "Class": cls, "Fine": fine,
            "Classpath": get_classpath("General Hardware"),
            "confidence": "low",
            "method": f"error:{e}",
        }
