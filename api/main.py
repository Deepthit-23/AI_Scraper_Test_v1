"""
FastAPI backend for the Product Intelligence Pipeline.

Wraps the existing pipeline (unihack/unihack_pipeline.py) with a REST API.
No pipeline logic lives here — this file only orchestrates, streams, and stores.

Endpoints:
  POST /upload                  validate CSV, return job_id
  POST /run/{job_id}            start pipeline in background, stream via SSE
  GET  /progress/{job_id}       SSE stream of per-row events
  GET  /results/{job_id}        all results as JSON
  GET  /results/{job_id}/download  enriched CSV
  GET  /sample                  pre-computed output CSV as JSON
  GET  /health                  liveness + groq key check
  GET  /                        serve frontend (api/static/index.html)
"""

import asyncio
import csv
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── Project root on sys.path so pipeline imports resolve ──────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from unihack.unihack_pipeline import OUTPUT_COLS, process_row

# ── Paths ──────────────────────────────────────────────────────────────────────
_UNIHACK   = _PROJECT_ROOT / "unihack"
OUTPUT_CSV  = _UNIHACK / "data" / "output" / "enriched_200rows.csv"
FALLBACK_CSV = _UNIHACK / "data" / "output" / "enriched_products.csv"
_STATIC_DIR = Path(__file__).parent / "static"

# ── Constants ─────────────────────────────────────────────────────────────────
REQUIRED_COLS = {"Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand", "DIB_Brand", "Part_Manuf"}
JOB_TTL = 7_200  # seconds; stale jobs pruned lazily on next upload

# ── In-memory job store ────────────────────────────────────────────────────────
# Each job: {status, filename, rows, results, events, total, csv_bytes, created_at}
jobs: dict[str, dict] = {}


def _prune_jobs() -> None:
    cutoff = time.time() - JOB_TTL
    stale = [jid for jid, j in jobs.items() if j["created_at"] < cutoff]
    for jid in stale:
        del jobs[jid]


# ── Pydantic models ────────────────────────────────────────────────────────────
class RunConfig(BaseModel):
    row_limit: Optional[int] = None
    enrich: bool = False
    category_filter: str = ""


# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Product Intelligence API", docs_url=None, redoc_url=None)


# ── Upload ─────────────────────────────────────────────────────────────────────
@app.post("/upload")
async def upload_csv(file: UploadFile = File(...)):
    """Parse and validate the uploaded CSV. Returns a job_id for subsequent calls."""
    _prune_jobs()

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # strip BOM if present
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        columns = list(reader.fieldnames or [])
    except Exception as exc:
        raise HTTPException(400, f"Could not parse CSV: {exc}")

    missing = REQUIRED_COLS - set(columns)
    if missing:
        raise HTTPException(
            422,
            {"error": "missing_columns", "missing": sorted(missing), "found": sorted(columns)},
        )

    if not rows:
        raise HTTPException(400, "CSV has no data rows.")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status":     "waiting",
        "filename":   file.filename or "upload.csv",
        "rows":       rows,
        "results":    [],
        "events":     [],
        "total":      0,
        "csv_bytes":  None,
        "created_at": time.time(),
    }
    return {"job_id": job_id, "rows": len(rows), "columns": sorted(columns)}


# ── Background pipeline runner ────────────────────────────────────────────────
async def _run_pipeline(job_id: str, config: RunConfig) -> None:
    job = jobs[job_id]
    rows: list[dict] = list(job["rows"])

    # Mirror Streamlit: take head(row_limit) first, then apply category filter
    if config.row_limit:
        rows = rows[: config.row_limit]
    if config.category_filter:
        kw = config.category_filter.lower()
        rows = [
            r for r in rows
            if kw in (r.get("Part_Desc") or "").lower()
            or kw in (r.get("Part_Manuf") or "").lower()
        ]

    if not rows:
        job["events"].append({"type": "error", "message": "No rows match the current filters."})
        job["status"] = "error"
        return

    job["total"]  = len(rows)
    job["status"] = "running"
    t0 = time.time()

    for i, row in enumerate(rows):
        mpn  = (row.get("Mfg_Part_Num") or "").strip()
        desc = (row.get("Part_Desc") or "")[:60]
        row_t0 = time.time()
        try:
            result  = await asyncio.to_thread(process_row, row, config.enrich)
            enriched   = result.get("_enriched") == "True"
            mpn_ver    = result.get("_exact_mpn_verified") == "True"
            attr_count = sum(
                1 for k in result if k.startswith("ATTRIBUTE_LABEL_") and result[k]
            )
            job["results"].append(result)
            job["events"].append({
                "type":        "row",
                "i":           i + 1,
                "total":       job["total"],
                "mpn":         mpn,
                "desc":        desc,
                "enriched":    enriched,
                "mpn_verified": mpn_ver,
                "tier":        result.get("_source_tier") or "",
                "attrs":       attr_count,
                "elapsed":     round(time.time() - row_t0, 1),
                "error":       None,
            })
        except Exception as exc:
            job["events"].append({
                "type":        "row",
                "i":           i + 1,
                "total":       job["total"],
                "mpn":         mpn,
                "desc":        desc,
                "enriched":    False,
                "mpn_verified": False,
                "tier":        "",
                "attrs":       0,
                "elapsed":     round(time.time() - row_t0, 1),
                "error":       str(exc)[:300],
            })

    n_enriched = sum(1 for r in job["results"] if r.get("_enriched") == "True")
    job["events"].append({
        "type":     "done",
        "total":    len(job["results"]),
        "enriched": n_enriched,
        "runtime":  round(time.time() - t0),
    })
    job["status"] = "done"

    # Build download CSV once, upfront
    if job["results"]:
        df = pd.DataFrame(job["results"])
        for col in OUTPUT_COLS:
            if col not in df.columns:
                df[col] = ""
        job["csv_bytes"] = df[OUTPUT_COLS].to_csv(index=False).encode("utf-8")


# ── Run ────────────────────────────────────────────────────────────────────────
@app.post("/run/{job_id}")
async def run_job(job_id: str, config: RunConfig):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found — re-upload your CSV.")
    if job["status"] != "waiting":
        raise HTTPException(409, f"Job is already {job['status']}.")
    if config.enrich and not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(
            400,
            "GROQ_API_KEY is not set on the server. Disable web enrichment or add the key.",
        )
    asyncio.create_task(_run_pipeline(job_id, config))
    return {"status": "started", "job_id": job_id}


# ── Progress SSE ───────────────────────────────────────────────────────────────
@app.get("/progress/{job_id}")
async def stream_progress(job_id: str):
    """Server-Sent Events stream. Replays all events on reconnect."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    async def generate():
        yield ": connected\n\n"
        seen = 0
        while True:
            events = job["events"]
            while seen < len(events):
                yield f"data: {json.dumps(events[seen])}\n\n"
                seen += 1
            if job["status"] in ("done", "error"):
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Results ────────────────────────────────────────────────────────────────────
@app.get("/results/{job_id}")
async def get_results(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return {"status": job["status"], "results": job["results"]}


@app.get("/results/{job_id}/download")
async def download_results(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.get("csv_bytes"):
        raise HTTPException(404, "Results not ready or job not found.")
    stem = Path(job.get("filename", "output.csv")).stem
    return Response(
        content=job["csv_bytes"],
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}_enriched.csv"'},
    )


# ── Sample ─────────────────────────────────────────────────────────────────────
@app.get("/sample")
async def get_sample():
    path = OUTPUT_CSV if OUTPUT_CSV.exists() else (
        FALLBACK_CSV if FALLBACK_CSV.exists() else None
    )
    if path is None:
        raise HTTPException(404, "No pre-computed sample available. Run the pipeline first.")
    df = pd.read_csv(path, dtype=str, na_filter=False)
    return {"results": df.to_dict(orient="records"), "source": path.name}


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "ok": True,
        "groq_key_set": bool(os.environ.get("GROQ_API_KEY")),
        "sample_available": OUTPUT_CSV.exists() or FALLBACK_CSV.exists(),
    }


# ── Frontend ───────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse(_STATIC_DIR / "index.html")


if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
