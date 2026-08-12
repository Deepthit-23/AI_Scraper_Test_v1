# AI-Powered Product Intelligence

A two-part pipeline that transforms raw industrial product catalog data into fully
enriched, structured records — using AI only where rules can't do the job.

**Built with:** Python · Groq (Llama 3.3 70B, free tier) · Trafilatura · DuckDuckGo · Streamlit

---

## What it does

Takes this:

```
MPN:      PDSH4816AF
Desc:     Dishwasher SS Display Only
Supplier: Appliance Dealers Cooperative (APPDE)
```

Produces this:

```
MANUFACTURER_NAME:  Rheem Manufacturing
BRAND_NAME:         FRIGIDAIRE®
Classpath:          Appliances & Consumer Electronics > Kitchen Appliances > Built-In Dishwashers
INVOICE_DESC:       DISHWASHER LEG 5 SST 120V 15A 50-1/4IN   (≤40 chars, ALL CAPS)
MOBILE_DESC:        Rheem Manufacturing FRIGIDAIRE, Dishwasher, Professional Series, PDSH4816AF
SHORT_DESC:         FRIGIDAIRE® Professional Series PDSH4816AF Dishwasher With CleanBoost™
... + attributes, units, fraction-formatted dimensions
```

---

## Setup

```bash
cd product-intel
python -m venv venv
venv\Scripts\activate        # Mac/Linux: source venv/bin/activate
python -m pip install -r requirements.txt

cp .env.example .env
# Edit .env and paste your GROQ_API_KEY
# Free key, no credit card: https://console.groq.com/keys
```

---

## Part 1 — Core pipeline (single product)

Scrapes a product URL or PDF and extracts structured JSON with confidence scores
and source citations for every field.

```bash
# Test the scraper (no API call)
python scraper/web_scraper.py

# Test PDF extraction
python scraper/pdf_ingest.py path/to/datasheet.pdf

# Full pipeline: scrape → extract → validate → save JSON
python pipeline.py

# Batch mode: process a CSV of URLs/PDFs
python batch_pipeline.py inputs.csv --delay 1.0

# Visual review UI (inspect extracted fields, confidence, source snippets)
streamlit run review_ui.py
```

Edit the `SOURCES` dict in `pipeline.py` to point at your own URLs and PDFs.

---

## Part 2 — Unihack enrichment pipeline (bulk catalog)

Processes a 1,000-row industrial catalog CSV through 9 modules: manufacturer
normalization → taxonomy classification → web enrichment → unit normalization →
fraction conversion → description generation → evaluation.

```bash
cd product-intel

# Score against ground truth (fast, ~10s, no web scraping)
python -m unihack.unihack_pipeline --eval-only

# Enrich 20 drill-related rows with live web scraping (~3 min)
python -m unihack.unihack_pipeline --limit 20 --category drill

# Same but skip web scraping (fast, ~30s)
python -m unihack.unihack_pipeline --limit 20 --category drill --no-enrich

# Filter by any keyword: impact, dishwasher, sanding, lighting …
python -m unihack.unihack_pipeline --limit 20 --category impact

# Verify all modules without any API calls
python unihack\test_smoke.py
```

**Input files** (place before running):
```
unihack/data/input/Sample_1000_Items.csv
unihack/data/ground_truth/expected_output_2rows.csv
```

**Output:** `unihack/data/output/enriched_products.csv`

---

## Project layout

```
product-intel/
├── pipeline.py              Core pipeline: scrape → extract → validate → JSON
├── batch_pipeline.py        Batch mode: run over a CSV of sources
├── review_ui.py             Streamlit review UI (confidence + source snippets)
│
├── scraper/
│   ├── web_scraper.py       Generic webpage fetch + Trafilatura content extraction
│   ├── pdf_ingest.py        PDF text + table extraction (pdfplumber)
│   └── image_ingest.py      Vision input via Groq Llama 4 Scout
│
├── extractor/
│   ├── llm_extractor.py     Groq tool-calling extraction → structured JSON
│   └── validator.py         Conflict detection, fuzzy completeness scoring
│
├── schema/
│   └── product_schema.py    Pydantic ProductRecord + Attribute shapes
│
├── unihack/                 Bulk enrichment pipeline (9 modules)
│   ├── unihack_pipeline.py  Orchestrator (reads CSV, calls all modules, writes output)
│   ├── test_smoke.py        Quick smoke test (no API calls)
│   │
│   ├── normalization/
│   │   ├── manufacturer_lookup.py   MPN prefix + canonical table + LLM fallback
│   │   ├── uom_table.py             Unit normalization ("volts" → "V", "SST", etc.)
│   │   └── fraction_decimal.py      50.25 → "50-1/4 in" (GCD lookup table)
│   │
│   ├── classification/
│   │   ├── taxonomy.py              23-category taxonomy definition
│   │   └── classifier.py            Keyword scoring → Groq LLM fallback
│   │
│   ├── enrichment/
│   │   └── manufacturer_finder.py   Direct URL → DuckDuckGo → scrape specs
│   │
│   ├── description/
│   │   └── generator.py             5 description types via hybrid template + AI
│   │
│   └── evaluation/
│       └── scorer.py                Fuzzy similarity scoring vs ground truth
│
├── data/
│   ├── samples/             Test data
│   └── output/              Extracted product JSONs
│
├── requirements.txt
└── .env.example
```

---

## How the Unihack pipeline works

Every row flows through these steps:

```
Input CSV row
    │
    ▼
[1] Manufacturer Lookup
    MPN prefix (PDSH→FRIGIDAIRE®) → brand columns → Groq LLM last resort
    │
    ▼
[2] Product Classifier
    Keyword scoring (free, instant) → Groq tool-calling for ambiguous cases
    → Classpath: "Tools > Power Tools & Accessories > Drills & Drivers"
    │
    ▼
[3] Web Enrichment
    Direct URL template → DuckDuckGo search → Trafilatura scrape
    → attributes, series name, mounting type, dimensions
    │
    ▼
[4–5] Unit + Fraction Normalization
    "volts" → "V"  |  50.25 → "50-1/4 in"
    │
    ▼
[6] Description Generator (hybrid template + AI)
    INVOICE_DESC  ≤40 chars, ALL CAPS, no brand, no MPN
    MOBILE_DESC   60–80 chars sentence case
    SHORT_DESC    Title case with features and top attributes
    LONG_DESC1    Full spec dump
    RETAIL_DESC   No brand, no MPN
    │
    ▼
[7] Evaluator
    Fuzzy similarity vs ground truth → EXACT / CLOSE / PARTIAL / MISS
    │
    ▼
enriched_products.csv
```

---

## Key design decisions

**Templates over pure AI for descriptions** — LLMs can't reliably hit a 40-char
limit across 1,000 rows. Templates guarantee format rules; the AI only picks
which 4 attributes to feature when there are 12 to choose from.

**Two-stage classification** — keyword scoring handles ~70% of products for free
in milliseconds. Groq is only called for genuinely ambiguous descriptions.

**MPN prefix lookup before LLM** — LLM manufacturer inference is non-deterministic
(same prompt → different answer each run). A hardcoded rule like PDSH → FRIGIDAIRE®
is deterministic and always correct.

**DuckDuckGo, not Google** — Google's Custom Search API requires payment after
100 daily queries. DuckDuckGo's HTML endpoint is free and unmetered.

**Groq free tier** — Llama 3.3 70B, ~6,000 requests/day, no credit card needed.
Supports tool-calling (forced structured JSON output) for reliable extraction.

---

## Current accuracy (2 ground-truth rows)

| Field | Score |
|---|---|
| MANUFACTURER_NAME | 100% |
| BRAND_NAME | 100% |
| Classpath | 100% |
| INVOICE_DESC format (drill batch) | 13/13 |
| MOBILE_DESC format (drill batch) | 7/13 |
| Overall exact + close (GT eval) | 55% |

Description quality improves significantly when web enrichment succeeds —
"Display Only" items block scraping, so series name and specs must come from
the manufacturer page.
