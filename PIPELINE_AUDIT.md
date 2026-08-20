# Pipeline Status Report

Technical audit of the product-intel pipeline. Every number cites the run that produced it. Every claim cites the file that implements it.

---

## Section 1 — What the pipeline actually does, step by step

### 1. Brand / Manufacturer Normalization
**Files:** `unihack/normalization/manufacturer_lookup.py`, `unihack/unihack_pipeline.py:108–133`
**Cost:** Free — rule-based only

`_resolve_brand()` reads E1/Unilog/DIB columns in priority order, ignoring placeholder strings. The resulting brand seeds `normalize_manufacturer()`, which runs a four-level lookup: MPN prefix → numeric code from Part_Manuf → normalized name match → LLM fallback. Returns `manufacturer_name` and `brand_name`.

---

### 2. Classification
**Files:** `unihack/classification/classifier.py`, `unihack/classification/taxonomy.py`
**Cost:** Free for rule hits; Groq tokens for LLM fallback

Rule-based keyword scoring first: scores each taxonomy category by (hit_count, max_keyword_length) for tie-breaking. If no category exceeds the confidence threshold, falls through to a Groq LLM tool call. LLM results cached in `llm_cache.json` keyed on `"{desc}::{mpn}"`. Model: `openai/gpt-oss-120b`.

---

### 3a. Enrichment — Direct URL (Stage 1)
**File:** `unihack/enrichment/manufacturer_finder.py` — `_BRAND_DOMAINS` table, line ~82
**Cost:** Free

Looks up brand key in `_BRAND_DOMAINS`. If `product_url` is set, builds the URL from a format string with `{mpn}` / `{mpn_lower}`.

| Has direct URL | No direct URL (bot-blocked / no pattern) |
|---|---|
| DeWALT, Milwaukee, Makita, Diablo, Speed Queen, SATCO, Leviton | Frigidaire, Whirlpool, Kichler, Philips, 3M, Southwire |

---

### 3b. Enrichment — Tavily Search (Stage 2)
**File:** `unihack/enrichment/manufacturer_finder.py` — Stage 2, line ~1090
**Cost:** Tavily API credits (1,000 free/month)

Queries Tavily with `"{brand} {mpn} {product_type} specifications"`. Receives scored, pre-fetched candidates. Each candidate passes through three quality gates before being accepted (see Section 3). Top gate-passing candidate (exact MPN match preferred) proceeds to LLM extraction.

---

### 3c. Enrichment — MPN Cache Replay (Stage 2.5)
**File:** `unihack/enrichment/manufacturer_finder.py:1185–1208`
**Cost:** Free — no network, no LLM

If no URL found yet, scans `llm_cache.json` extract namespace for any key containing the MPN string. On hit, calls `extract_product("", source_id=cached_url)` — returns the cached `ProductRecord` without any API call. Sets `result["enriched"] = True` and returns early.

---

### 3d. Enrichment — ScraperAPI Fallback (Stage 3)
**File:** `unihack/enrichment/manufacturer_finder.py` — `_scraperapi_stage3()`
**Cost:** ScraperAPI credits

Last resort. Uses ScraperAPI's JS-rendering proxy + DuckDuckGo to find and scrape pages that blocked direct HTTP. Result passes the same three quality gates as Stage 2.

---

### 4. Attribute Extraction
**File:** `extractor/llm_extractor.py`
**Cost:** Groq TPD tokens (most expensive step)

Sends cleaned page text to Groq (`openai/gpt-oss-120b`) via a structured tool call. Returns a `ProductRecord` with named attributes, values, and units. Cached in `llm_cache.json` keyed by source URL — same URL never calls Groq twice. Attributes stamped with `source_type="html"`.

---

### 5. PDF Supplementation
**Files:** `scraper/pdf_discovery.py`, `scraper/pdf_ingest.py`, `manufacturer_finder.py:1289`
**Cost:** Groq TPD tokens
**Status:** Fully wired in — no confirmed successful live extraction in test history

After HTML extraction, scans raw HTML for `<a>` links with `.pdf` hrefs or spec-sheet keywords. Downloads up to 3 candidates. Runs `is_pdf_spec_sheet()` gate (rejects warranty cards, installation manuals by reject/spec signal counting). Extracts text with `pdfplumber` (tables flattened to "Column: Value" lines). Calls same LLM extractor. `_merge_pdf_attributes()` adds PDF-only attributes or replaces lower-confidence HTML ones. Attributes stamped with `source_type="pdf"`.

---

### 6. Description Generation
**Files:** `unihack/description/generator.py`, `unihack/unihack_pipeline.py:184`
**Cost:** Free — `use_llm=False` is hardcoded in `unihack_pipeline.py:184`

Fully template-based in production. Generates five description types:

| Field | Rule |
|---|---|
| `INVOICE_DESC` | ALL CAPS, ≤40 chars |
| `MOBILE_DESC` | 60–80 chars, sentence case |
| `SHORT_DESC` | Title case, brand + series + MPN + type |
| `LONG_DESC1` | Full spec dump, comma-separated |
| `RETAIL_DESC` | Title case, no brand/MPN |

An optional LLM call exists in the generator code to rank attributes when >10 are available, but is disabled. Post-generation: sets `_invoice_desc_ok` / `_mobile_desc_ok`.

---

### 7. UOM Normalization
**File:** `unihack/normalization/uom_table.py`
**Cost:** Free

Rule table maps common abbreviation variants to canonical forms. Applied to every `ATTRIBUTE_UOM_N` column before CSV write.

---

### 8. LLM Caching
**File:** `unihack/llm_cache.py`, `unihack/data/cache/llm_cache.json`
**Cost:** None — prevents cost

JSON file with two namespaces:
- `"extract"` — 171 entries, keyed by source URL
- `"classify"` — 90 entries, keyed by `"{desc}::{mpn}"`

> **Important:** Caching is cost avoidance only. It does not improve data quality. If the original extraction was wrong, the cache stores and replays the wrong answer.

---

## Section 2 — Measured accuracy numbers

Source: `unihack/data/output/enriched_200rows.csv` — 200 rows from `next_200rows.csv` run with `enrich=True`, Groq key exhausted at ~row 93. Figures are pipeline metadata fields (`_enriched`, `_invoice_desc_ok`, etc.).

### Top-level stats

| Metric | Result | Note |
|---|---|---|
| Web-enriched rows | **68 / 200 (34%)** | Quota exhausted at ~row 93 |
| Brand resolved | **186 / 200 (93%)** | 14 rows resolved as "unknown" |
| Non-misc classpath | **90 / 200 (45%)** | 110 rows fall to Miscellaneous |
| MPN verified (enriched rows) | **49 / 68 (72%)** | MPN string confirmed in URL or page text |
| `INVOICE_DESC` pass | **200 / 200 (100%)** | ALL CAPS ≤40 chars |
| `MOBILE_DESC` pass | **81 / 200 (40.5%)** | All 119 failures are on unenriched rows |

### Breakdown

| Metric | Result | Detail |
|---|---|---|
| Brand resolution method | brand_hint: 98, direct_lookup: 60, mpn_prefix: 17, llm_inferred: 11, unknown: 14 | brand_hint = E1/Unilog/DIB column used; mpn_prefix = DeWALT/Milwaukee/GE prefix table hit |
| Classification method | rule: 19, llm: 72+, error (quota): 3+ | 3+ rows show raw Groq 429 error in `_classification_method` |
| Classification confidence | high: 54, medium: 26, low: 120 | 60% low-confidence; mostly obscure building material SKUs |
| Enriched source tier | manufacturer: 43, retailer: 24, blank: 1 | 63% manufacturer-tier on enriched rows |
| Failure causes (unenriched) | quota-429: 97, 403 blocked: 12, brand mismatch: 7, other: 16 | 97 rows hit Groq 200K TPD limit |
| LLM cache state | extract: 171, classify: 90 | 50/68 enriched rows have MPN in extract cache; 72/200 rows hit classify cache |

---

## Section 3 — Engineering decisions and why

### Rule-based logic runs before any LLM call
Both classification and brand resolution attempt rule-based paths first. For classification: keyword scoring is tried before Groq (`classifier.py:62–90`). For manufacturer lookup: MPN prefix, numeric code, and name tables are checked before LLM fallback. The comment in `classifier.py:4–6` states this explicitly — Groq's free tier was the driver.

### Tavily replaced DDG for Stage 2 search
Documented in `manufacturer_finder.py:7` docstring: "Tavily web search (replaces DDG)." Tavily pre-fetches and scores results; bare DDG URLs still needed individual scraping and were frequently 403'd on first request. Tavily also accepts regional TLD exclusions, reducing non-US retailer noise.

### Three quality gates on every candidate page
Stage 2 runs all three gates on each Tavily candidate; Stage 1 and Stage 3 results run them after scraping.

| Gate | Function | Confirmed example |
|---|---|---|
| Brand mismatch | `_is_wrong_brand()` — checks if page text/URL names a different brand | Frigidaire MPN search returning a Whirlpool page |
| Wrong page type | `_is_wrong_page_type()` — rejects install guides, support articles, blog posts | `owner.frigidaire.com/support-articles/…` rejected as "installation or support article, not a product spec page" (live test, PDSH4816AF) |
| Promo/rebate | `_is_promo_content()` — rejects promotional/marketing pages | `manufacturer_finder.py:1250`: "Page is promotional/rebate content…" |

### `_exact_mpn_verified` — what it protects against
Set True when the MPN string appears verbatim in the page URL or scraped text. Guards against enriching a product with a spec page for a similar but different SKU (e.g., DCF887 confused with DCF889 — same brand, same category, passes all three gates). 49/68 enriched rows have this True in the 200-row run.

### `ALLOW_RETAILER_SOURCES = True` (current setting)
Set at `manufacturer_finder.py:35`. When True, Stage 2 accepts retailer URLs alongside manufacturer and distributor pages. 24/68 enriched rows (35%) came from retailer-tier sources. Retailer data is less authoritative — attribute values may be incomplete or marketing-flavored. Can be set False to restrict to manufacturer/distributor only, but this would drop the enrichment rate significantly.

### Caching: what it does and does not do
The JSON cache prevents re-paying Groq for URLs and descriptions already extracted. It does not improve accuracy — a wrong extraction is cached and replayed exactly as wrong. Stage 2.5 cache replay works by scanning extract keys for the MPN substring and serving the prior result without any network request or LLM call.

**Deployment note:** `llm_cache.json` is committed to git. When deployed (e.g., Railway), the cache is present from clone. New extractions during live runs append in-place. Entries added during a deployed run are lost on the next redeploy unless committed back.

---

## Section 4 — Known limitations

### Groq free-tier daily token quota
200,000 tokens per 24-hour rolling window (not a fixed midnight UTC reset). The 200-row run was aborted at ~row 93. Exact error seen in output: *"Rate limit reached… Limit 200000, Used 198,872, Requested 2976."* Each enriched row costs approximately 3,000–7,000 tokens. This limits a fresh run to roughly 30–60 enriched rows before failures begin. 97 of 132 unenriched rows in the 200-row output failed with this error.

### Manufacturer sites confirmed bot-blocked
`frigidaire.com` and `whirlpool.com` return 403 on direct HTTP — confirmed in Stage 2 logs during live testing. Both have `product_url: None` in `_BRAND_DOMAINS`. Also without direct URL templates: `kichler.com`, `lighting.philips.com`, `3m.com`, `southwire.com`. Facebook/Instagram URLs returned by Tavily also fail — no extractable content. Stage 3 (ScraperAPI) partially mitigates Cloudflare blocks but is not guaranteed.

### MOBILE_DESC fails on all unenriched rows
119/200 rows have `_mobile_desc_ok=False`. All 119 are unenriched rows. Without attributes from web enrichment, the template produces `"{Mfr}, {Type}, {MPN}"` which is consistently under the 60-character minimum. Enriched rows: 0/68 failures.

### 110/200 rows classified as Miscellaneous
55% of the 200-row run output lands in `Hardware>General Hardware>Miscellaneous`. Affected manufacturers: Parksite (45 rows), Boise Cascade Building Materials (41 rows), Rees Cast Stone (4 rows), V&V Appliance Parts. These are building material distributors whose `Part_Desc` values are bare part numbers or product codes with no recognizable category keywords.

### No official LOV / taxonomy provided
`classification/taxonomy.py:1–10` states: *"Product taxonomy reverse-engineered from the 200-row ground truth."* The category schema (38+ categories, classpaths, keywords, product_types, expected_attributes) was self-derived from the 2-row GT's format and the broader input data's Part_Desc patterns. No official List of Values or taxonomy document was provided.

### PDF extraction: wired in, no confirmed success
All three PDF modules are wired into the live pipeline at `manufacturer_finder.py:1289–1299`. However, no live run has produced a complete successful path: discover PDF → download → pass `is_pdf_spec_sheet()` → LLM extract → attributes merged. The failure path (403 on download, "content too sparse") has been observed. The success path has not been confirmed end-to-end.

### Bugs found and fixed this session

| Bug | Fix location |
|---|---|
| GE/Haier brand misattribution — "Haier" resolved to `manufacturer_name="Haier"` | `manufacturer_lookup.py` — Haier entries added to `MANUFACTURER_CANONICAL` |
| GE Profile/Café MPN prefix routing — PDD/PTD/PEP/CHP unrecognized | `manufacturer_lookup.py` — added to `_MPN_PREFIX_MAP` |
| Whirlpool sub-brands missing — Maytag, KitchenAid, Amana, JennAir not in canonical table | `manufacturer_lookup.py` |
| Tier badge showing on unenriched rows (UI) | `api/static/index.html` |
| Stale `_enrichment_error` on successful rows — Stage 2 failure message showing despite `_enriched=True` | `unihack_pipeline.py:214` — `"" if enrichment.get("enriched") else (enrichment.get("error") or "")` |
| LLM HTTP-400 on malformed tool-call JSON | Caught and logged; row falls through unenriched |

---

## Section 5 — What is NOT built

### JS-rendered page scraping
No headless browser (Playwright, Selenium, Puppeteer). `scrape_product_page()` in `web_scraper.py` uses plain `requests` + `BeautifulSoup`. Pages requiring JavaScript to render are either skipped or handled by ScraperAPI's JS rendering proxy (Stage 3 only — not available in Stages 1 or 2).

### Automatic URL pattern learning
Every entry in `_BRAND_DOMAINS` was manually verified and hardcoded. There is no mechanism to infer new URL templates from Tavily results or successful Stage 3 scrapes. Adding a new brand requires a code edit.

### Multi-language support
Not mentioned or attempted anywhere in the codebase. All processing assumes English-language product descriptions and page content.

### Image extraction — built as utility, not wired into pipeline
`scraper/image_ingest.py` exists. It calls Groq's `meta-llama/llama-4-scout-17b-16e-instruct` vision model, extracts text from a product image, and passes it to `extract_product()`. However, `manufacturer_finder.py` has no code path that calls `image_ingest`. It cannot be reached from the live pipeline.

### Batch parallelism
`_process_rows()` in `unihack_pipeline.py:274–299` processes rows sequentially with `time.sleep(1.0)` between enriched rows. No concurrent row processing.

### Standard identifier fields
The ground truth schema includes UPC, EAN, GTIN, UNSPSC, Country of Origin, List Price, Selling UOM, and physical dimensions (LENGTH, WIDTH, HEIGHT, WEIGHT). None are populated by the pipeline.

### Per-attribute source tracking in output CSV
Individual attributes have `source_type` ("html" vs "pdf") and `source_tier` set internally, but these are not written to output CSV columns. The output only has `_enrichment_source` (URL) and `_source_tier` at the row level. Which specific attributes came from PDF vs HTML is not visible in the output CSV.
