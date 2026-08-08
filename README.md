# AI-Powered Product Intelligence — Starter Pipeline

Turns messy product sources (webpages, PDF datasheets) into structured,
validated, source-cited product records.

## How it works

```
Webpage URL  ──┐
               ├──> scraper (fetch + clean, no per-site rules) ──┐
PDF datasheet ─┘                                                 │
                                                                   ▼
                                              extractor/llm_extractor.py
                                    (Claude reads cleaned text, outputs
                                     structured JSON with a source quote
                                     + confidence for every field)
                                                                   │
                                                                   ▼
                                              extractor/validator.py
                                (checks for conflicts, missing fields,
                                 computes a completeness score)
                                                                   │
                                                                   ▼
                                    data/output/<product_name>.json
```

## Setup (run this on your own machine, not a sandboxed environment)

```bash
cd product-intel
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste your real GROQ_API_KEY
# get a free key (no credit card needed) at https://console.groq.com/keys
```

## Run it

```bash
# Test the scraper alone (prints cleaned text, no API call needed)
python scraper/web_scraper.py

# Test the PDF reader alone
python scraper/pdf_ingest.py path/to/some_datasheet.pdf

# Run the full pipeline (scrape/read -> extract -> validate -> save JSON)
python pipeline.py
```

Edit the `SOURCES` dict at the bottom of `pipeline.py` to point at your own
product URLs and PDF paths.

## Project layout

```
scraper/
  web_scraper.py   - generic webpage fetch + clean
  pdf_ingest.py     - PDF text + table extraction
extractor/
  llm_extractor.py  - the core AI extraction step (structured + cited output)
  validator.py      - conflict detection, completeness scoring
schema/
  product_schema.py - the shared data shape everything conforms to
pipeline.py          - wires it all together
data/
  samples/           - test data
  output/            - generated product JSON records land here
```

## What's next (not yet built)

- **Vision/image input**: same pattern — OCR or feed image directly to Claude's
  vision capability, get clean text, pass to the SAME `extract_product()` function.
- **RAG enrichment**: when a field is missing, search similar already-processed
  products / category docs to fill gaps intelligently.
- **Knowledge graph**: enforce category-level rules across the catalog
  (e.g. all "valve" products must report a pressure rating).
- **Review UI**: a simple frontend showing each product, confidence-flagged
  fields, and their source snippet, with an approve/edit button.
- **Batch mode**: run pipeline.py over a whole folder of PDFs / a CSV of URLs
  to demonstrate catalog-scale processing.
