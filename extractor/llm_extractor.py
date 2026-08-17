"""
This is the heart of the whole pipeline.

Given cleaned text from ANY source (webpage, PDF, image OCR) it asks the LLM to:
  1. Identify the product's core info (name, category, manufacturer, model numbers)
  2. Pull out every attribute it can find (spec name + value + unit)
  3. For EVERY attribute, quote the exact sentence it came from (source_snippet)
  4. Give a confidence level (high/medium/low)

We FORCE this shape using tool/function-calling (instead of hoping the model
replies in valid JSON) -- this is much more reliable at scale, which matters
when you're processing a whole catalog, not just one demo product.

PROVIDER: Groq (free tier, no credit card needed, includes Llama 3.3 70B which
supports tool calling). If you later get Anthropic credits, switching back to
Claude is a ~10 line change -- see the commented block at the bottom of this file.
"""

import os
import json
from groq import Groq
from schema.product_schema import ProductRecord, Attribute

MODEL = "openai/gpt-oss-120b"

# Overhead budget (system prompt + tool definition + user-message prefix) ≈ 1,000 tokens.
# Hard cap on source_text leaves ~6,000 tokens for content, staying well under the
# 8,000 TPM limit.  Trafilatura already removed nav/boilerplate, so a head-first
# truncation keeps the product-spec region which appears near the top of clean_text.
_MAX_SOURCE_CHARS = 24_000

# This is the "shape" we force the model to fill in.
# It mirrors schema/product_schema.py -- keep them in sync.
EXTRACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "record_product_data",
        "description": "Record structured product information extracted from source text.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "category": {"type": "string", "description": "e.g. thermocouple, sensor, valve, motor"},
                "manufacturer": {
                    "type": "string",
                    "description": "Manufacturer name. Use empty string '' if not mentioned in the source."
                },
                "model_numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only model numbers that appear VERBATIM in the source text. Use empty array [] if none found. Never infer or complete a series."
                },
                "short_description": {"type": "string"},
                "attributes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "unit": {
                                "type": "string",
                                "description": "Unit if applicable (e.g. 'W', 'V', 'Hz', 'lm/W'). Use empty string '' when no unit applies (e.g. for text attributes like Color or Dimmable)."
                            },
                            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            "source_snippet": {
                                "type": "string",
                                "description": "The exact original sentence/phrase this value came from. Must be a real quote from the source text, not paraphrased."
                            },
                        },
                        "required": ["name", "value", "confidence", "source_snippet"],
                    },
                },
            },
            "required": ["product_name", "attributes"],
        },
    },
}

SYSTEM_PROMPT = """You are a product data extraction specialist for industrial/commercial products.

Rules:
- Only extract information EXPLICITLY stated in the source text. Never invent, infer, or extrapolate values.
- The attribute VALUE must be derived ONLY from the source_snippet — if the snippet does not support the full value, shorten the value to match it exactly.
- model_numbers MUST be explicitly listed in the source text. Do NOT infer variants (e.g. do not add -72 or -120 suffixes unless they appear verbatim).
- If a value is ambiguous, incomplete, or you are inferring it indirectly, mark confidence as "low" or "medium" instead of "high".
- Every attribute MUST include a source_snippet that is an exact verbatim quote from the source text.
- Extract ALL measurable/specifiable facts including response time, ratings, dimensions, materials, certifications.
- The source text is often a spec table rendered as flat lines: attribute name on one line, value on the next (e.g. "Color\\nMatte Black" or "Capacity\\n7.0"). Treat each such name/value pair as one attribute — do NOT skip Color, Finish, or material entries.
- Always extract Color and Finish attributes when present — they are high-priority product identifiers.
- Normalize units where obvious (e.g. keep both metric and imperial if the source gives both).
- Do not extract marketing fluff ("easy to use", "best in class") — only concrete, measurable/specifiable facts.
- If the source text is clearly NOT about a single specific product (e.g. it's a category listing page), still extract what you can but note it in short_description.
"""


def get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com/keys "
            "(no credit card needed), then create a .env file (see .env.example) "
            "or export it in your shell before running this."
        )
    return Groq(api_key=api_key)


def _build_record(data: dict, source_id: str) -> ProductRecord:
    """Build a ProductRecord from the raw LLM tool-call dict (cached or live)."""
    attributes = [
        Attribute(
            name=a["name"],
            value=a["value"],
            unit=a.get("unit"),
            confidence=a["confidence"],
            source_snippet=a["source_snippet"],
            source_id=source_id,
            needs_review=(a["confidence"] == "low"),
        )
        for a in data.get("attributes", [])
    ]
    return ProductRecord(
        product_name=data.get("product_name", "Unknown"),
        category=data.get("category"),
        manufacturer=data.get("manufacturer"),
        model_numbers=data.get("model_numbers", []),
        short_description=data.get("short_description"),
        attributes=attributes,
        sources=[source_id],
    )


def extract_product(source_text: str, source_id: str) -> ProductRecord:
    """
    source_text: cleaned text from a webpage, PDF, or OCR'd image
    source_id: an identifier for where this came from, e.g. "omega.com/pptst/SA1.html"
                or "datasheet_page3.pdf" -- used for traceability

    Results are cached in llm_cache keyed on source_id (URL) so re-running the
    pipeline on already-extracted pages never re-spends Groq quota.
    """
    try:
        from unihack import llm_cache as _cache
        cached = _cache.get("extract", source_id)
        if cached is not None:
            return _build_record(cached, source_id)
    except Exception:
        pass

    client = get_client()

    # Truncate to avoid hitting the 8,000 TPM limit on openai/gpt-oss-120b.
    # Trafilatura clean_text has no nav/boilerplate; product specs appear near
    # the top, so head-first truncation preserves the highest-value content.
    if len(source_text) > _MAX_SOURCE_CHARS:
        source_text = source_text[:_MAX_SOURCE_CHARS] + "\n[content truncated]"

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Extract structured product data from this source (source_id: {source_id}):\n\n{source_text}",
            },
        ],
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_product_data"}},
    )

    if hasattr(response, "usage") and response.usage:
        try:
            from unihack import llm_cache as _cache
            _cache.record_usage(response.usage.total_tokens)
        except Exception:
            pass

    tool_call = response.choices[0].message.tool_calls[0]
    data = json.loads(tool_call.function.arguments)

    try:
        from unihack import llm_cache as _cache
        _cache.set("extract", source_id, data)
    except Exception:
        pass

    return _build_record(data, source_id)


if __name__ == "__main__":
    # Run this on your own machine with a real free Groq key set:
    #   export GROQ_API_KEY=gsk_...
    #   python extractor/llm_extractor.py
    with open("data/samples/omega_sa1_webpage.txt") as f:
        text = f.read()

    record = extract_product(text, source_id="in.omega.com/pptst/SA1.html")
    print(record.model_dump_json(indent=2))

# ---------------------------------------------------------------------------
# OPTIONAL: switch to Claude later if you get Anthropic credits.
# Claude tends to give slightly more careful/accurate extractions and citations
# than open-source models, so it's worth trying if you can. To switch:
#
#   pip install anthropic
#   import anthropic
#   client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
#   response = client.messages.create(
#       model="claude-sonnet-4-6", max_tokens=2000, system=SYSTEM_PROMPT,
#       tools=[{  # note: Claude's tool schema has no "type"/"function" wrapper
#           "name": EXTRACTION_TOOL["function"]["name"],
#           "description": EXTRACTION_TOOL["function"]["description"],
#           "input_schema": EXTRACTION_TOOL["function"]["parameters"],
#       }],
#       tool_choice={"type": "tool", "name": "record_product_data"},
#       messages=[{"role": "user", "content": f"...{source_text}"}],
#   )
#   data = next(b for b in response.content if b.type == "tool_use").input
# ---------------------------------------------------------------------------
