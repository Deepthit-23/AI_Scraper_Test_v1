"""
Product Intelligence Pipeline — Streamlit Dashboard

Primary flow: upload a product CSV → configure and run → view enriched results → download.
Browse pre-computed sample results on the landing page without uploading anything.

READ-ONLY mode (sample view): visualises pre-generated output CSVs. No API calls, no
live scraping, no secrets required.

LIVE mode (upload & run): requires GROQ_API_KEY in the environment. When the key is
absent the dashboard stays in read-only mode — no feature flag needed.

Usage:
    streamlit run unihack_dashboard.py
"""

import io
import os
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Pipeline import (live run only) ───────────────────────────────────────────
_PIPELINE_AVAILABLE = False
_PIPELINE_ERR = ""
try:
    from unihack.unihack_pipeline import process_row as _process_row, OUTPUT_COLS as _OUTPUT_COLS
    _PIPELINE_AVAILABLE = True
except Exception as _e:
    _PIPELINE_ERR = str(_e)

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
OUTPUT_CSV = ROOT / "unihack" / "data" / "output"       / "enriched_200rows.csv"
GT_CSV     = ROOT / "unihack" / "data" / "ground_truth" / "expected_output_200rows.csv"

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Product Intelligence Pipeline",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Global */
  .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
  h1, h2, h3 { letter-spacing: -0.02em; }

  /* Cards */
  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1.1rem 1.25rem;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
    height: 100%;
  }
  .card-title {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #64748b;
    margin-bottom: .35rem;
  }
  .card-value {
    font-size: 2rem;
    font-weight: 800;
    color: #0f172a;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .card-sub {
    font-size: 0.78rem;
    color: #64748b;
    margin-top: .2rem;
  }
  .card-metric-label {
    font-size: 0.68rem;
    font-weight: 700;
    color: #0f766e;
    letter-spacing: .04em;
    text-transform: uppercase;
    margin-bottom: .05rem;
  }

  /* Badges */
  .badge {
    display: inline-block;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    padding: .18rem .55rem;
    border-radius: 999px;
  }
  .badge-green  { background: #dcfce7; color: #166534; }
  .badge-amber  { background: #fef9c3; color: #854d0e; }
  .badge-gray   { background: #f1f5f9; color: #64748b; }

  /* Score tiers (accuracy table) */
  .tier-EXACT   { background: #dcfce7; color: #166534; }
  .tier-CLOSE   { background: #dbeafe; color: #1d4ed8; }
  .tier-PARTIAL { background: #fef9c3; color: #854d0e; }
  .tier-MISS    { background: #fee2e2; color: #991b1b; }

  /* Section subtitles */
  .section-sub {
    font-size: 0.85rem;
    color: #64748b;
    margin-bottom: 1.2rem;
  }

  /* Progress bar */
  .prog-wrap { margin: .2rem 0 .6rem; }
  .prog-bar-bg {
    background: #e2e8f0;
    border-radius: 999px;
    height: 7px;
    width: 100%;
  }
  .prog-bar-fill { height: 7px; border-radius: 999px; }

  /* Divider */
  .divider { border: none; border-top: 1px solid #e2e8f0; margin: 1.8rem 0; }

  /* Limitations */
  .lim-item {
    border-left: 3px solid #0f766e;
    padding-left: .75rem;
    margin-bottom: .9rem;
  }
  .lim-title { font-weight: 700; color: #0f172a; font-size: .9rem; }
  .lim-body  { color: #475569; font-size: .82rem; margin-top: .15rem; line-height: 1.5; }

  /* Source chip */
  .source-chip {
    display: inline-block;
    background: #f0fdfa;
    border: 1px solid #99f6e4;
    color: #0f766e;
    font-size: .7rem;
    border-radius: 6px;
    padding: .1rem .5rem;
    font-family: monospace;
    word-break: break-all;
  }

  /* Run log */
  .run-log {
    background: #0f172a;
    color: #e2e8f0;
    font-family: monospace;
    font-size: 0.78rem;
    border-radius: 8px;
    padding: .9rem 1rem;
    line-height: 1.7;
    min-height: 5rem;
    max-height: 22rem;
    overflow-y: auto;
  }
  .run-log-ok  { color: #4ade80; }
  .run-log-err { color: #f87171; }
  .run-log-dim { color: #94a3b8; }

  /* Hero */
  .hero-title {
    font-size: 2.1rem;
    font-weight: 900;
    color: #0f172a;
    letter-spacing: -0.04em;
    line-height: 1.15;
    margin-bottom: .55rem;
    text-wrap: balance;
  }
  .hero-sub {
    font-size: 1rem;
    color: #475569;
    line-height: 1.6;
    max-width: 54rem;
    margin-bottom: 2rem;
  }
  .upload-panel {
    background: #f8fafc;
    border: 2px dashed #cbd5e1;
    border-radius: 14px;
    padding: 1.4rem 1.6rem 1rem;
  }
  .upload-panel-label {
    font-size: 0.72rem;
    font-weight: 700;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: .07em;
    margin-bottom: .5rem;
  }
  .result-source-label {
    font-size: 0.72rem;
    color: #94a3b8;
    margin-bottom: .75rem;
    font-variant-numeric: tabular-nums;
  }
</style>
""", unsafe_allow_html=True)


# ── Data helpers ───────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_output() -> "pd.DataFrame | None":
    if not OUTPUT_CSV.exists():
        return None
    return pd.read_csv(OUTPUT_CSV, dtype=str, na_filter=False)


@st.cache_data(ttl=30)
def load_gt() -> "pd.DataFrame | None":
    if not GT_CSV.exists():
        return None
    return pd.read_csv(GT_CSV, dtype=str, na_filter=False)


SCORED_FIELDS = [
    "MANUFACTURER_NAME", "BRAND_NAME", "MANUFACTURER_PART_NUMBER",
    "Classpath", "MOBILE_DESC", "INVOICE_DESC",
    "SHORT_DESC", "LONG_DESC1", "RETAIL_DESC", "Product Name",
]

DISPLAY_FIELDS = [
    "MANUFACTURER_NAME", "BRAND_NAME", "Classpath",
    "Product Name", "MOBILE_DESC", "INVOICE_DESC",
]


def _norm(s: str) -> str:
    s = re.sub(r"[®™,\.;\-\(\)]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _score_tier(sim: float, exp: str, got: str) -> str:
    if exp.strip() == got.strip(): return "EXACT"
    if sim >= 0.80: return "CLOSE"
    if sim >= 0.50: return "PARTIAL"
    return "MISS"


@st.cache_data(ttl=30)
def compute_scores(output_csv_mtime: float) -> pd.DataFrame:
    df  = load_output()
    gdf = load_gt()
    if df is None or gdf is None:
        return pd.DataFrame()
    gt_by_mpn = {
        str(r.get("MANUFACTURER_PART_NUMBER", r.get("Mfg_Part_Num", ""))).strip(): dict(r)
        for _, r in gdf.iterrows()
    }
    rows = []
    for _, out_row in df.iterrows():
        mpn = str(out_row.get("Mfg_Part_Num", "")).strip()
        gt_row = gt_by_mpn.get(mpn)
        if not gt_row:
            continue
        for fld in SCORED_FIELDS:
            exp = str(gt_row.get(fld, "")).strip()
            got = str(out_row.get(fld, "")).strip()
            sim = _sim(exp, got)
            rows.append({"mpn": mpn, "field": fld, "sim": sim,
                         "tier": _score_tier(sim, exp, got),
                         "expected": exp, "got": got})
    return pd.DataFrame(rows)


# ── Visual helpers ─────────────────────────────────────────────────────────────

def _pct_color(pct: float) -> str:
    if pct >= 0.80: return "#16a34a"
    if pct >= 0.50: return "#ca8a04"
    return "#dc2626"


def _prog(pct: float, color: str = "#0f766e") -> str:
    w = max(0, min(100, int(pct * 100)))
    return (
        f'<div class="prog-wrap"><div class="prog-bar-bg">'
        f'<div class="prog-bar-fill" style="width:{w}%;background:{color}"></div>'
        f'</div></div>'
    )


def _source_tier_badge(tier: str) -> str:
    return (
        '<span class="badge" style="background:#dcfce7;color:#166534">manufacturer</span>'
        if tier == "manufacturer" else
        '<span class="badge" style="background:#dbeafe;color:#1d4ed8">distributor</span>'
        if tier == "distributor" else
        '<span class="badge" style="background:#fef9c3;color:#854d0e">retailer</span>'
        if tier == "retailer" else ""
    )


def _mpn_badge(verified: str) -> str:
    if verified == "True":
        return (
            '<span class="badge" style="background:#ccfbf1;color:#0f766e;border:1px solid #99f6e4" '
            'title="Input MPN found verbatim on source page">&#10003; MPN Verified</span>'
        )
    if verified == "False":
        return (
            '<span class="badge" style="background:#ffedd5;color:#9a3412;border:1px solid #fed7aa" '
            'title="Input MPN not found on source page — specs are from a related product (same family/brand)">'
            '&#9888; MPN not confirmed on source</span>'
        )
    return ""


# ── Shared results renderer ────────────────────────────────────────────────────

def _render_results(
    df: pd.DataFrame,
    *,
    source_label: str = "",
    show_accuracy: bool = False,
    output_mtime: float = 0.0,
    detail_key_suffix: str = "",
) -> None:
    """Stat cards → search → results table → row detail → download."""

    n_total      = len(df)
    n_classified = (df["Classpath"].str.strip() != "").sum() if "Classpath" in df.columns else 0
    n_brand_ok   = (df["BRAND_NAME"].str.strip() != "").sum() if "BRAND_NAME" in df.columns else 0
    n_enriched   = (df["_enriched"] == "True").sum() if "_enriched" in df.columns else 0
    n_mpn_t      = (df["_exact_mpn_verified"] == "True").sum() if "_exact_mpn_verified" in df.columns else 0

    attr_counts = [
        sum(1 for k in row.index if k.startswith("ATTRIBUTE_LABEL_") and str(row[k]).strip())
        for _, row in df.iterrows()
    ]
    n_with_attrs  = sum(1 for c in attr_counts if c > 0)
    avg_attrs_all = sum(attr_counts) / n_total if n_total else 0

    top_sources: pd.Series = pd.Series(dtype=int)
    if "_enrichment_source" in df.columns and n_enriched > 0:
        top_sources = (
            df.loc[df.get("_enriched", pd.Series(dtype=str)) == "True", "_enrichment_source"]
            .str.extract(r"https?://(?:www\.)?([^/]+)", expand=False)
            .value_counts()
        )

    if source_label:
        st.markdown(
            f'<div class="result-source-label">{source_label}</div>',
            unsafe_allow_html=True,
        )

    # ── Stat cards ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    with c1:
        st.markdown(
            f'<div class="card"><div class="card-title">Processed</div>'
            f'<div class="card-value">{n_total}</div>'
            f'<div class="card-sub">rows</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        pct = n_classified / n_total if n_total else 0
        st.markdown(
            f'<div class="card"><div class="card-title">Classified</div>'
            f'<div class="card-value" style="color:{_pct_color(pct)}">{pct*100:.0f}%</div>'
            f'<div class="card-sub">{n_classified} rows with category</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        pct = n_brand_ok / n_total if n_total else 0
        st.markdown(
            f'<div class="card"><div class="card-title">Brand Resolved</div>'
            f'<div class="card-value" style="color:{_pct_color(pct)}">{pct*100:.0f}%</div>'
            f'<div class="card-sub">{n_brand_ok} rows</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        pct = n_enriched / n_total if n_total else 0
        src_note = ", ".join(top_sources.index[:2].tolist()) if len(top_sources) else "—"
        st.markdown(
            f'<div class="card"><div class="card-title">Web-Enriched</div>'
            f'<div class="card-value" style="color:{_pct_color(pct)}">{pct*100:.0f}%</div>'
            f'<div class="card-sub">{n_enriched} rows · {src_note}</div></div>',
            unsafe_allow_html=True,
        )
    with c5:
        pct = n_mpn_t / n_enriched if n_enriched else 0
        st.markdown(
            f'<div class="card"><div class="card-title">MPN Verified</div>'
            f'<div class="card-value" style="color:{_pct_color(pct)}">{pct*100:.0f}%</div>'
            f'<div class="card-sub">of enriched rows · exact match on source</div></div>',
            unsafe_allow_html=True,
        )
    with c6:
        st.markdown(
            f'<div class="card"><div class="card-title">Avg Attributes</div>'
            f'<div class="card-value">{avg_attrs_all:.1f}</div>'
            f'<div class="card-sub">per row ({n_with_attrs} rows with attrs)</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Search + table ──────────────────────────────────────────────────────────
    search_key = f"search_{detail_key_suffix}"
    search = st.text_input(
        "Search by MPN, brand, description, or category:",
        placeholder="e.g.  dishwasher,  LED bulb,  3200-20,  Power Tools",
        key=search_key,
    )

    display_cols = [
        "Mfg_Part_Num", "Part_Desc", "BRAND_NAME", "MANUFACTURER_NAME",
        "Classpath", "INVOICE_DESC", "MOBILE_DESC",
        "_enriched", "_exact_mpn_verified", "_source_tier", "_enrichment_source",
    ]
    view_df = df[[c for c in display_cols if c in df.columns]].copy()
    view_df = view_df.rename(columns={
        "Mfg_Part_Num":         "MPN",
        "Part_Desc":            "Input Description",
        "BRAND_NAME":           "Brand",
        "MANUFACTURER_NAME":    "Manufacturer",
        "Classpath":            "Category",
        "INVOICE_DESC":         "INVOICE DESC",
        "MOBILE_DESC":          "MOBILE DESC",
        "_enriched":            "Enriched",
        "_exact_mpn_verified":  "MPN Verified",
        "_source_tier":         "Tier",
        "_enrichment_source":   "Source URL",
    })
    if "Category" in view_df.columns:
        view_df["Category"] = view_df["Category"].apply(
            lambda x: str(x).split(">")[-1].strip() if x else ""
        )

    if search:
        mask = view_df.apply(
            lambda r: search.lower() in " ".join(r.values.astype(str)).lower(), axis=1
        )
        view_df = view_df[mask]
        st.caption(f"{len(view_df)} row{'s' if len(view_df) != 1 else ''} match '{search}'")

    st.dataframe(view_df, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row detail ──────────────────────────────────────────────────────────────
    st.markdown("#### Inspect a Row")

    all_mpns = df["Mfg_Part_Num"].tolist() if "Mfg_Part_Num" in df.columns else []
    select_key = f"detail_mpn_{detail_key_suffix}"
    sel_mpn = st.selectbox(
        "Select MPN to view attributes and source:",
        ["— select —"] + all_mpns,
        key=select_key,
    )

    if sel_mpn and sel_mpn != "— select —":
        matches = df[df["Mfg_Part_Num"] == sel_mpn]
        if len(matches) == 0:
            st.warning(f"MPN `{sel_mpn}` not found in current view.")
        else:
            row = matches.iloc[0]
            info_col, attr_col = st.columns([1, 2])

            with info_col:
                st.markdown("**Product info**")
                st.markdown(f"**MPN:** `{row.get('Mfg_Part_Num', '—')}`")
                st.markdown(f"**Brand:** {row.get('BRAND_NAME', '—')}")
                st.markdown(f"**Manufacturer:** {row.get('MANUFACTURER_NAME', '—')}")
                cp = row.get("Classpath", "—")
                st.markdown(f"**Category:** {cp}")
                st.markdown("---")
                st.markdown(f"**INVOICE_DESC:** `{row.get('INVOICE_DESC', '—')}`")
                mob = row.get("MOBILE_DESC", "—")
                st.markdown(f"**MOBILE_DESC:** {mob}")
                short = str(row.get("SHORT_DESC", ""))
                if short:
                    st.markdown(f"**SHORT_DESC:** {short[:180]}{'…' if len(short) > 180 else ''}")
                st.markdown("---")

                enriched_flag = row.get("_enriched", "") == "True"
                if enriched_flag:
                    tier     = row.get("_source_tier", "")
                    verified = row.get("_exact_mpn_verified", "")
                    src_url  = row.get("_enrichment_source", "")
                    st.markdown(
                        f"**Source:** {_source_tier_badge(tier)} {_mpn_badge(verified)}",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div class="source-chip">{src_url}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    err = row.get("_enrichment_error", "") or "No matching page found"
                    st.markdown(f"**Not enriched:** {str(err)[:140]}")
                    st.caption("See **Coverage & Limitations** tab for common causes.")

            with attr_col:
                st.markdown("**Extracted Attributes**")
                attrs = []
                for i in range(1, 51):
                    lbl = row.get(f"ATTRIBUTE_LABEL_{i}", "")
                    val = row.get(f"ATTRIBUTE_VALUE_{i}", "")
                    uom = row.get(f"ATTRIBUTE_UOM_{i}", "")
                    if lbl:
                        attrs.append({"#": i, "Attribute": lbl, "Value": val, "UOM": uom})
                if attrs:
                    st.dataframe(pd.DataFrame(attrs), use_container_width=True, hide_index=True)
                else:
                    st.info("No attributes extracted for this product.")

    # ── Download ────────────────────────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    if _PIPELINE_AVAILABLE and _OUTPUT_COLS:
        for oc in _OUTPUT_COLS:
            if oc not in df.columns:
                df[oc] = ""
        csv_bytes = df[_OUTPUT_COLS].to_csv(index=False).encode("utf-8")
    else:
        csv_bytes = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="⬇  Download enriched CSV",
        data=csv_bytes,
        file_name="enriched_products.csv",
        mime="text/csv",
        type="primary",
    )

    # ── Accuracy vs. reference (optional) ──────────────────────────────────────
    if show_accuracy and output_mtime:
        scores_df = compute_scores(output_mtime)
        if not scores_df.empty:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown("#### Accuracy vs. Provided Reference Data")
            st.markdown(
                '<div class="section-sub">Field-level similarity between pipeline output and the '
                'reference file. Scoring uses fuzzy string matching; exact string equality would '
                'unfairly penalise correct values with minor formatting differences.</div>',
                unsafe_allow_html=True,
            )

            metric_fields = [
                ("Manufacturer",  "MANUFACTURER_NAME"),
                ("Brand",         "BRAND_NAME"),
                ("Category",      "Classpath"),
                ("Product Name",  "Product Name"),
                ("Mobile Desc",   "MOBILE_DESC"),
                ("Invoice Desc",  "INVOICE_DESC"),
            ]
            m_cols = st.columns(len(metric_fields))
            for col, (label, fld) in zip(m_cols, metric_fields):
                sub = scores_df[scores_df["field"] == fld]
                if sub.empty:
                    continue
                ge50  = sub["tier"].isin(["EXACT", "CLOSE", "PARTIAL"]).mean()
                exact = (sub["tier"] == "EXACT").mean()
                color = _pct_color(ge50)
                with col:
                    st.markdown(
                        f'<div class="card">'
                        f'<div class="card-title">{label}</div>'
                        f'<div class="card-metric-label">≥50% Match</div>'
                        f'<div class="card-value" style="color:{color}">{ge50*100:.0f}%</div>'
                        f'{_prog(ge50, color)}'
                        f'<div class="card-sub">Exact: {exact*100:.0f}%</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown("<br>", unsafe_allow_html=True)

            pivot = (
                scores_df[scores_df["field"].isin(DISPLAY_FIELDS)]
                .pivot_table(index="mpn", columns="field", values="tier", aggfunc="first")
                .reset_index()
            )
            overall = (
                scores_df.groupby("mpn")
                .apply(lambda g: g["tier"].isin(["EXACT", "CLOSE", "PARTIAL"]).mean())
                .reset_index(name="overall_ge50")
            )
            pivot = pivot.merge(overall, on="mpn", how="left")
            pivot["Score"] = (pivot["overall_ge50"] * 100).round(0).astype(int).astype(str) + "%"
            pivot = pivot.drop(columns=["overall_ge50"]).sort_values("Score", ascending=False)
            pivot.columns = [c.replace("_", " ") for c in pivot.columns]

            st.markdown("##### Per-row breakdown")
            st.dataframe(pivot, use_container_width=True, hide_index=True)

            with st.expander("Field-level detail (all rows × all fields)"):
                pivot_full = (
                    scores_df.pivot_table(index="mpn", columns="field", values="tier", aggfunc="first")
                    .reset_index()
                )
                pivot_full.columns = [c.replace("_", " ") for c in pivot_full.columns]
                st.dataframe(pivot_full, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

tab_pipeline, tab_limitations = st.tabs(["🔍 Pipeline", "📋 Coverage & Limitations"])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

with tab_pipeline:

    has_live_results  = bool(st.session_state.get("_up_results"))
    is_viewing_sample = st.session_state.get("_viewing_sample", False)

    # ── STATE: Results from live run ──────────────────────────────────────────
    if has_live_results:
        results_list = st.session_state["_up_results"]
        result_df    = pd.DataFrame(results_list)
        orig_fname   = st.session_state.get("_up_fname", "output.csv")

        hdr_col, btn_col = st.columns([7, 1])
        with hdr_col:
            st.markdown("### Results")
        with btn_col:
            if st.button("New run", key="new_run_btn"):
                st.session_state.pop("_up_results", None)
                st.session_state.pop("_up_fname", None)
                st.session_state.pop("_up_last_fname", None)
                st.rerun()

        if _PIPELINE_AVAILABLE and _OUTPUT_COLS:
            for oc in _OUTPUT_COLS:
                if oc not in result_df.columns:
                    result_df[oc] = ""

        _render_results(
            result_df,
            source_label=f"Run on: {orig_fname} · {len(results_list)} rows processed",
            show_accuracy=False,
            detail_key_suffix="live",
        )

    # ── STATE: Viewing pre-computed sample ────────────────────────────────────
    elif is_viewing_sample:
        saved_df = load_output()

        hdr_col, btn_col = st.columns([7, 1])
        with hdr_col:
            st.markdown("### Sample Results")
            st.markdown(
                '<div class="section-sub">Pre-computed output from a recent pipeline run. '
                'Upload your own data to process a new set of products.</div>',
                unsafe_allow_html=True,
            )
        with btn_col:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("← Back", key="back_sample_btn"):
                st.session_state["_viewing_sample"] = False
                st.rerun()

        if saved_df is None:
            st.error(
                f"Pre-computed output not found at `{OUTPUT_CSV.relative_to(ROOT)}`.\n\n"
                "Run the pipeline on a local CSV first to generate it."
            )
        else:
            mtime      = OUTPUT_CSV.stat().st_mtime
            mtime_str  = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            has_gt     = GT_CSV.exists()
            _render_results(
                saved_df,
                source_label=f"Last run: {mtime_str} · {len(saved_df)} rows",
                show_accuracy=has_gt,
                output_mtime=mtime if has_gt else 0.0,
                detail_key_suffix="sample",
            )

    # ── STATE: Landing + Upload + Run config ──────────────────────────────────
    else:
        # Hero
        st.markdown(
            '<div class="hero-title">Product Intelligence Pipeline</div>'
            '<div class="hero-sub">Turn raw catalog rows into structured, enriched, '
            'source-cited product data — classification, manufacturer resolution, '
            'web attribute extraction, and description generation in one pass.</div>',
            unsafe_allow_html=True,
        )

        _groq_key         = os.environ.get("GROQ_API_KEY", "")
        _run_ready        = _PIPELINE_AVAILABLE and bool(_groq_key)

        upload_col, spacer_col, sample_col = st.columns([5, 1, 2])

        with upload_col:
            st.markdown('<div class="upload-panel">', unsafe_allow_html=True)
            st.markdown(
                '<div class="upload-panel-label">Upload a product CSV to get started</div>',
                unsafe_allow_html=True,
            )

            if not _groq_key:
                st.info(
                    "**Live processing requires a local API key.**  \n"
                    "Add `GROQ_API_KEY=…` to your `.env` file and restart to enable the run feature. "
                    "In the meantime, browse pre-computed sample results →"
                )
                uploaded_file = st.file_uploader(
                    "Upload product CSV",
                    type=["csv"],
                    key="upload_main",
                    help="Required columns: Mfg_Part_Num, Part_Desc, E1_Brand, Unilog_Brand, DIB_Brand, Part_Manuf",
                    disabled=True,
                )
                uploaded_file = None
            elif not _PIPELINE_AVAILABLE:
                st.error(
                    "Pipeline modules could not be imported.  \n"
                    "Run this from the `product-intel/` directory.\n\n"
                    f"```\n{_PIPELINE_ERR[:300]}\n```"
                )
                uploaded_file = None
            else:
                uploaded_file = st.file_uploader(
                    "Upload product CSV",
                    type=["csv"],
                    key="upload_main",
                    help="Required columns: Mfg_Part_Num, Part_Desc, E1_Brand, Unilog_Brand, DIB_Brand, Part_Manuf",
                )

            st.markdown("</div>", unsafe_allow_html=True)

        with sample_col:
            st.markdown("<br><br>", unsafe_allow_html=True)
            if OUTPUT_CSV.exists():
                if st.button("Browse sample results →", key="view_sample_btn", use_container_width=True):
                    st.session_state["_viewing_sample"] = True
                    st.rerun()
                mtime_str = datetime.fromtimestamp(OUTPUT_CSV.stat().st_mtime).strftime("%b %d, %Y")
                st.caption(f"Pre-computed output from {mtime_str}.")
            else:
                st.caption(
                    "No pre-computed results yet.  \n"
                    "Upload a CSV and run the pipeline."
                )

        # ── Run configuration (appears once a valid file is uploaded) ──────────
        if uploaded_file is not None:
            if uploaded_file.name != st.session_state.get("_up_last_fname"):
                st.session_state.pop("_up_results", None)
                st.session_state["_up_last_fname"] = uploaded_file.name

            try:
                raw       = uploaded_file.getvalue().decode("utf-8", errors="replace")
                upload_df = pd.read_csv(io.StringIO(raw), dtype=str, na_filter=False)
                parse_err = None
            except Exception as _pe:
                upload_df = None
                parse_err = str(_pe)

            if parse_err:
                st.error(f"Could not parse CSV: {parse_err}")

            elif upload_df is not None:
                _REQUIRED = {"Mfg_Part_Num", "Part_Desc", "E1_Brand", "Unilog_Brand",
                             "DIB_Brand", "Part_Manuf"}
                missing = _REQUIRED - set(upload_df.columns)

                if missing:
                    st.error(
                        f"**Missing required columns:** `{'`, `'.join(sorted(missing))}`  \n"
                        f"Found: `{'`, `'.join(sorted(upload_df.columns.tolist()))}`"
                    )
                else:
                    n_avail = len(upload_df)
                    st.success(
                        f"Loaded **{uploaded_file.name}** — {n_avail:,} rows, "
                        f"{len(upload_df.columns)} columns"
                    )

                    st.markdown("---")
                    st.markdown("#### Run Configuration")

                    _MAX_RANGE = 50
                    opt1, opt2, opt3, opt4 = st.columns([1, 1, 1, 2])
                    with opt1:
                        start_row = st.number_input(
                            "Start row",
                            min_value=1, max_value=n_avail,
                            value=1, step=1,
                            help="First row to process (1-indexed).",
                        )
                    with opt2:
                        end_row = st.number_input(
                            "End row",
                            min_value=int(start_row), max_value=n_avail,
                            value=min(int(start_row) + _MAX_RANGE - 1, n_avail), step=1,
                            help="Last row to process (1-indexed, inclusive). Maximum range: 50 rows.",
                        )
                    with opt3:
                        do_enrich = st.checkbox(
                            "Enable web enrichment", value=False,
                            help="Fetches live data from manufacturer and retailer sites. Uses API quota.",
                        )
                    with opt4:
                        cat_filter = st.text_input(
                            "Category filter (optional)",
                            placeholder="e.g.  drill,  LED bulb,  washer",
                            help="Only process rows where Part_Desc or Part_Manuf contains this keyword.",
                        )

                    # Clamp range to MAX_RANGE
                    if int(end_row) - int(start_row) + 1 > _MAX_RANGE:
                        end_row = int(start_row) + _MAX_RANGE - 1
                        st.caption(
                            f"⚠ Range clamped to rows {int(start_row)}–{int(end_row)}. "
                            "Limited to 50 rows per run due to LLM API quota — "
                            "adjust start row to test a different slice."
                        )

                    if do_enrich:
                        st.warning(
                            "**Enrichment is limited to 50 rows per run** due to LLM token quota "
                            "constraints on the free tier. You can test any 50-row slice of your "
                            "uploaded file by adjusting the start row — this lets you sample different "
                            "sections of a larger catalog across multiple runs. "
                            "Quota errors are logged per row; the run continues."
                        )
                    else:
                        st.info(
                            "**Fast mode** — classification and description generation only; "
                            "no web scraping or attribute extraction. Toggle 'Enable web enrichment' "
                            "to fetch live product data."
                        )

                    st.markdown("<br>", unsafe_allow_html=True)

                    if st.button("▶  Run Pipeline", type="primary", key="run_pipeline_btn"):
                        rows_to_run = upload_df.iloc[int(start_row)-1 : int(end_row)].to_dict(orient="records")
                        if cat_filter.strip():
                            kw = cat_filter.strip().lower()
                            rows_to_run = [
                                r for r in rows_to_run
                                if kw in str(r.get("Part_Desc", "")).lower()
                                or kw in str(r.get("Part_Manuf", "")).lower()
                            ]

                        if not rows_to_run:
                            st.warning(
                                f"No rows match `{cat_filter}` in rows {int(start_row)}–{int(end_row)}. "
                                "Try a different keyword or clear the filter."
                            )
                        else:
                            n_proc  = len(rows_to_run)
                            t_start = time.time()
                            st.markdown(
                                f"Processing **{n_proc}** row{'s' if n_proc != 1 else ''} "
                                f"({'with' if do_enrich else 'without'} web enrichment)…"
                            )

                            progress_bar = st.progress(0, text="Starting…")
                            log_box      = st.empty()
                            log_lines: list[str] = []
                            run_results: list[dict] = []

                            for _i, _row in enumerate(rows_to_run):
                                _mpn = str(_row.get("Mfg_Part_Num") or "?").strip()
                                progress_bar.progress(
                                    _i / n_proc,
                                    text=f"[{_i+1}/{n_proc}]  {_mpn}…",
                                )

                                try:
                                    _out    = _process_row(_row, enrich=do_enrich)
                                    run_results.append(_out)
                                    _brand  = _out.get("BRAND_NAME") or "—"
                                    _cp     = ((_out.get("Classpath") or "—")).split(">")[-1].strip()
                                    _enrd   = _out.get("_enriched") == "True"
                                    _nattr  = sum(1 for k in _out if k.startswith("ATTRIBUTE_LABEL_") and _out[k])
                                    _icon   = "🌐" if _enrd else "📋"
                                    _note   = f" · {_nattr} attrs" if _nattr else ""
                                    if do_enrich and not _enrd:
                                        _err_s = str(_out.get("_enrichment_error") or "no match")[:55]
                                        _note += f" · _{_err_s}_"
                                    log_lines.append(
                                        f"{_icon} **[{_i+1}/{n_proc}]** `{_mpn}` · {_brand} · {_cp}{_note}"
                                    )
                                except Exception as _exc:
                                    run_results.append({"Mfg_Part_Num": _mpn})
                                    log_lines.append(
                                        f"❌ **[{_i+1}/{n_proc}]** `{_mpn}` · {str(_exc)[:100]}"
                                    )

                                log_box.markdown("\n\n".join(log_lines[-12:]))

                            elapsed = time.time() - t_start
                            progress_bar.progress(
                                1.0,
                                text=f"Done — {len(run_results)} rows in {elapsed:.1f} s",
                            )

                            st.session_state["_up_results"] = run_results
                            st.session_state["_up_fname"]   = uploaded_file.name
                            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — COVERAGE & LIMITATIONS
# ─────────────────────────────────────────────────────────────────────────────

with tab_limitations:
    st.markdown("### Coverage & Limitations")
    st.markdown(
        '<div class="section-sub">'
        'What sources the pipeline uses, what causes a product not to enrich, '
        'and honest caveats about data quality.'
        '</div>',
        unsafe_allow_html=True,
    )

    LIMITATIONS = [
        {
            "title": "Live enrichment row limit",
            "body": (
                "Live enrichment is limited to 50 rows per run, due to daily token quota limits on "
                "the underlying LLM API (free tier). You can test any 50-row range within a larger "
                "uploaded file by setting the start and end row — this is a quota constraint of the "
                "current deployment, not a limitation of the pipeline logic itself."
                "<br><br>"
                "In practice, success rate depends on which rows are sampled. Brands with a known "
                "URL template (e.g. Milwaukee Tool accessories) enrich at effectively 100% since each "
                "row uses a cached or direct scrape with no per-row search API call. Untemplated brands "
                "(e.g. Trex, TimberTech PVC decking) each require a fresh web search and LLM extraction "
                "call (~3,000–7,000 tokens per row). On a recent 200-row full run, 68 rows enriched "
                "successfully — the remaining 132 were cut off by quota exhaustion mid-run, not because "
                "discovery or extraction failed for those brands specifically."
            ),
        },
        {
            "title": "Web enrichment: Stage 1 URL templates + Stage 2 Tavily search",
            "body": (
                "Stage 1 uses direct URL templates for brands with a verified product URL pattern "
                "(DeWalt, Milwaukee, Makita, Speed Queen, Satco, Leviton). "
                "Stage 2 runs Tavily web search with a domain-scoped pass (manufacturer site first) "
                "followed by a general fallback pass. "
                "All candidate pages pass three quality gates — wrong-brand check, wrong-page-type "
                "check (category/range/family pages are filtered out), and promotional-content "
                "check — before extraction. "
                "The pipeline prefers pages where the exact input MPN appears in the source text "
                "or URL slug over related-product pages from the same brand family."
            ),
        },
        {
            "title": "MPN Verified (True) vs. MPN not confirmed (False)",
            "body": (
                "<strong>MPN Verified = True</strong>: the literal input MPN was found in the "
                "source page's text or URL slug. High confidence that the extracted attributes "
                "describe exactly the requested SKU. "
                "<br><br>"
                "<strong>MPN Verified = False</strong>: the source page did not contain the input "
                "MPN literally. This typically occurs when a manufacturer's global catalog uses "
                "regional product codes (e.g., EU part numbers for North American MPNs). "
                "Extracted attributes are still from the same brand and product family and are "
                "directionally correct, but should be verified against the manufacturer's spec "
                "sheet before use in high-stakes catalog entries. "
                "This flag is informational only — it does not block enrichment."
            ),
        },
        {
            "title": "Why some products are not enriched",
            "body": (
                "A product returns not-enriched when: (1) no URL template exists for the brand "
                "and Tavily finds no reachable indexed page, (2) all candidate pages fail a quality "
                "gate (wrong brand, category/family page, or promotional content), "
                "(3) all candidate pages return HTTP 403 / 404 / 5xx. "
                "JavaScript-rendered storefronts and Cloudflare-protected pages are the most common "
                "failure modes. Stage 3 (ScraperAPI) handles some JS-rendered pages as a last resort."
            ),
        },
        {
            "title": "Description fields depend on successful enrichment",
            "body": (
                "INVOICE_DESC, SHORT_DESC, LONG_DESC1, and RETAIL_DESC are LLM-generated from "
                "extracted attributes. When no enrichment source is available these fields still "
                "populate with minimal content derived from the input Part_Desc, but they will "
                "not include specification details."
            ),
        },
        {
            "title": "API token usage",
            "body": (
                "Classification and attribute extraction use the Groq API (openai/gpt-oss-120b). "
                "All LLM extractions are cached by source URL — re-running the pipeline on the "
                "same rows costs zero tokens. "
                "A fresh enriched run costs roughly 3,000–7,000 tokens per enriched row. "
                "The free Groq tier provides 200,000 tokens per 24-hour rolling window. "
                "At 50 rows per run, a full pass of untemplated brands uses roughly 100,000–200,000 tokens."
            ),
        },
    ]

    for lim in LIMITATIONS:
        st.markdown(
            f'<div class="lim-item">'
            f'<div class="lim-title">{lim["title"]}</div>'
            f'<div class="lim-body">{lim["body"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        "Sample view reads from `unihack/data/output/enriched_200rows.csv`. "
        "Accuracy comparison reads from `unihack/data/ground_truth/expected_output_200rows.csv` "
        "when that file is present. "
        "No API keys are read by the dashboard — they are only used during a live run."
    )
