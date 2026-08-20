# AI-Powered Product Intelligence

A pipeline that transforms raw industrial product catalog data into fully enriched,
structured records — using AI only where rules can't do the job.

**Built with:** Python · FastAPI · Groq (`openai/gpt-oss-120b`) · Tavily · pdfplumber · Streamlit · Railway

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
MANUFACTURER_NAME:  GE Appliances
BRAND_NAME:         GE®
Classpath:          Appliances & Consumer Electronics > Kitchen Appliances > Built-In Dishwashers
INVOICE_DESC:       DISHWASHER BUILT-IN SS 24IN                 (≤40 chars, ALL CAPS)
MOBILE_DESC:        GE Appliances GE, Dishwasher, PDSH4816AF, Built-In  (60–80 chars)
SHORT_DESC:         GE® PDSH4816AF Dishwasher
... + up to 10 attribute triplets (label / value / unit)
```

---

## Setup

```bash
cd product-intel
python -m venv venv
venv\Scripts\activate        # Mac/Linux: source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add to .env:
#   GROQ_API_KEY=...      (free tier: https://console.groq.com/keys)
#   TAVILY_API_KEY=...    (free tier: https://app.tavily.com)
#   SCRAPERAPI_KEY=...    (optional, for Stage 3 fallback)
```

---

## Running the pipeline

### Unihack enrichment pipeline (bulk catalog)

```bash
# Fast baseline — no web enrichment, ~10s
python -m unihack.unihack_pipeline --eval-mini --no-enrich

# Ad-hoc run, first 20 drill rows with live enrichment
python -m unihack.unihack_pipeline --limit 20 --category drill

# Filter by keyword: impact, dishwasher, sanding, lighting …
python -m unihack.unihack_pipeline --limit 10 --category milwaukee

# Smoke test — verifies all modules, no API calls
python unihack/test_smoke.py
```

**Output:** `unihack/data/output/enriched_products.csv` (ad-hoc) or `enriched_200rows.csv` (eval-full)

### FastAPI backend + web UI

```bash
cd product-intel
uvicorn api.main:app --reload
# → http://localhost:8000
```

Upload a CSV, choose start/end rows (max 50 per run due to Groq quota), toggle web enrichment, stream results row-by-row.

### Streamlit dashboard

```bash
streamlit run unihack_dashboard.py
```

### Railway deployment

The FastAPI server deploys directly to Railway. The LLM cache (`unihack/data/cache/llm_cache.json`) is committed to git and present on every deploy — rows with cached extractions cost zero Groq tokens.

---

## How the enrichment pipeline works

```
Input CSV row
    │
    ▼
[1] Manufacturer / Brand Normalization           free, rule-based
    MPN prefix table → numeric code → name table → LLM last resort
    │
    ▼
[2] Product Classifier                           free for rule hits; Groq tokens for LLM
    Keyword scoring → Groq tool-call for ambiguous cases
    → Classpath: "Tools & Equipment > Power Tools > Drills & Drivers"
    │
    ▼
[3] Web Enrichment (4 stages)
    Stage 1  — Direct URL template (DeWALT, Milwaukee, Makita, …)   free
    Stage 2  — Tavily search + 3 quality gates                       Tavily credits
    Stage 2.5— MPN cache replay (prior extraction, no API call)      free
    Stage 3  — ScraperAPI + DDG fallback (last resort)               ScraperAPI credits
    │
    ▼
[4] Attribute Extraction                         Groq tokens (most expensive step)
    LLM tool-call on scraped page text → up to 10 named attribute triplets
    Cached by source URL — same page never calls Groq twice
    │
    ▼
[5] PDF Supplementation                          Groq tokens
    Discovers spec-sheet PDFs linked from the accepted page
    pdfplumber extracts text + tables → same LLM extractor
    _merge_pdf_attributes() fills gaps or upgrades lower-confidence HTML attrs
    │
    ▼
[6] Description Generation                       free, template-based
    INVOICE_DESC  ALL CAPS ≤40 chars
    MOBILE_DESC   60–80 chars, sentence case
    SHORT_DESC    Title case, brand + MPN + type
    LONG_DESC1    Full spec dump, comma-separated
    RETAIL_DESC   Title case, no brand / no MPN
    │
    ▼
enriched_products.csv / enriched_200rows.csv
```

### Three quality gates (applied to every candidate page)

| Gate | What it rejects |
|---|---|
| Brand mismatch | Page that mentions a different brand than the target MPN |
| Wrong page type | Installation guides, support articles, blog posts |
| Promo/rebate | Promotional or marketing-only pages |

---

## Measured results (200-row run)

Source: `unihack/data/output/enriched_200rows.csv` — 200 rows, live enrichment,
Groq key exhausted at ~row 93.

| Metric | Result |
|---|---|
| Web-enriched | 68 / 200 (34%) — quota hit at ~row 93 |
| Brand resolved | 186 / 200 (93%) |
| Non-misc classpath | 90 / 200 (45%) |
| MPN verified on enriched rows | 49 / 68 (72%) |
| `INVOICE_DESC` pass (≤40 chars, ALL CAPS) | 200 / 200 (100%) |
| `MOBILE_DESC` pass (60–80 chars) | 81 / 200 (40.5%) — all failures on unenriched rows |
| Enriched source tier | manufacturer 43, retailer 24 |

**MOBILE_DESC note:** Every failure is on an unenriched row. Without spec attributes, the template output is `"{Mfr}, {Type}, {MPN}"` which is consistently under 60 characters. All enriched rows pass.

**Groq quota:** 200,000 tokens per 24-hour rolling window (not a fixed midnight UTC reset). Each enriched row costs ~3,000–7,000 tokens. The web UI and Streamlit dashboard both enforce a 50-row hard cap per run.

---

## Key design decisions

**Rule-based before LLM** — Manufacturer lookup and classification both try rules first. Groq is only called for genuinely ambiguous cases. On the 200-row run: 19/200 classified by rule (free, instant); 72 by LLM.

**Tavily replaced DuckDuckGo** — Tavily pre-fetches and scores results; DDG returned bare URLs that were frequently 403'd on first request and had no relevance signal.

**MPN cache replay (Stage 2.5)** — Before calling Groq, the pipeline checks whether a prior run already extracted this MPN. 50/68 enriched rows in the 200-row run were eligible for cache replay.

**Templates over pure AI for descriptions** — LLMs can't reliably hit a 40-char limit. Templates guarantee format compliance; the AI selects which attributes to feature only when there are more than 10 available (currently disabled — `use_llm=False`).

**`ALLOW_RETAILER_SOURCES = True`** — Stage 2 currently accepts retailer URLs (AJ Madison, The Brick, etc.) alongside manufacturer and distributor pages. 35% of enriched rows come from retailer-tier sources. Can be set to False in `manufacturer_finder.py:35` to restrict to manufacturer/distributor only.

---

## Project layout

```
product-intel/
├── api/
│   ├── main.py              FastAPI backend (upload, run, SSE progress, download)
│   └── static/index.html    Web UI (vanilla JS, no framework)
│
├── scraper/
│   ├── web_scraper.py       HTTP fetch + content extraction
│   ├── pdf_discovery.py     Discovers spec-sheet PDF links in page HTML
│   ├── pdf_ingest.py        PDF text + table extraction (pdfplumber)
│   └── image_ingest.py      Vision input via Groq Llama 4 Scout (utility only)
│
├── extractor/
│   ├── llm_extractor.py     Groq tool-calling → structured ProductRecord
│   └── validator.py         Conflict detection, fuzzy completeness scoring
│
├── schema/
│   └── product_schema.py    Pydantic ProductRecord + Attribute shapes
│
├── unihack/
│   ├── unihack_pipeline.py  Main orchestrator (normalize → classify → enrich → describe)
│   ├── llm_cache.py         JSON cache for extract + classify results
│   ├── unihack_dashboard.py Streamlit UI
│   │
│   ├── normalization/
│   │   ├── manufacturer_lookup.py   MPN prefix table + canonical lookup + LLM fallback
│   │   └── uom_table.py             Unit normalization ("volts" → "V")
│   │
│   ├── classification/
│   │   ├── taxonomy.py              38+ category taxonomy (self-derived from input data)
│   │   └── classifier.py            Keyword scoring → Groq LLM fallback
│   │
│   ├── enrichment/
│   │   └── manufacturer_finder.py   4-stage enrichment (direct URL / Tavily / cache / ScraperAPI)
│   │
│   ├── description/
│   │   └── generator.py             5 description types, template-based
│   │
│   ├── evaluation/
│   │   └── scorer.py                Fuzzy similarity scoring vs ground truth
│   │
│   └── data/
│       ├── input/                   Sample_1000_Items.csv, next_200rows.csv
│       ├── output/                  enriched_200rows.csv, enriched_products.csv
│       ├── cache/llm_cache.json     LLM extraction + classification cache (committed to git)
│       └── ground_truth/            expected_output_2rows.csv
│
├── PIPELINE_AUDIT.md        Full technical audit with cited accuracy numbers
├── requirements.txt
└── .env.example
```

---

## Known limitations

- **Groq TPD quota** caps enrichment at ~30–60 rows per fresh run before 429 errors begin.
- **Bot-blocked manufacturer sites:** `frigidaire.com`, `whirlpool.com`, `kichler.com`, `philips.com` return 403 on direct HTTP. Tavily finds retailer alternatives; ScraperAPI partially mitigates.
- **55% of the 200-row test batch classifies as Miscellaneous** — these are Parksite and Boise Cascade building material SKUs with opaque Part_Desc values that don't match any taxonomy keywords.
- **No headless browser** — pages requiring JavaScript to render content are not scraped in Stages 1 or 2 (ScraperAPI's JS rendering covers Stage 3 only).
- **PDF extraction** is fully implemented and wired in but end-to-end success has not been confirmed in a live run.

See [PIPELINE_AUDIT.md](PIPELINE_AUDIT.md) for the full audit with file citations.
