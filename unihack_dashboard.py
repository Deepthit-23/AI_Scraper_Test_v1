"""
Unihack Product Intelligence Review Dashboard
Run: streamlit run unihack_dashboard.py
"""
import sys
import os
import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from unihack.evaluation.scorer import (
    load_ground_truth,
    score_product,
    SCORED_FIELDS,
    CHAR_LIMIT_RULES,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
ENRICHED_CSV = _ROOT / "unihack" / "data" / "output" / "enriched_products.csv"
GT_CSV = _ROOT / "unihack" / "data" / "ground_truth" / "expected_output_2rows.csv"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Unihack Pipeline Dashboard",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Base */
.stApp { background: #F8FAFC; }
[data-testid="metric-container"] {
    background: white; border: 1px solid #E2E8F0;
    border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
h2, h3 { color: #1E293B !important; }
[data-testid="stExpander"] { border: 1px solid #E2E8F0!important; border-radius: 10px!important; background: white; }

/* Tier badges */
.badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.04em; }
.b-exact   { background:#DCFCE7; color:#15803D; }
.b-close   { background:#DBEAFE; color:#1D4ED8; }
.b-partial { background:#FEF3C7; color:#B45309; }
.b-miss    { background:#FEE2E2; color:#DC2626; }
.b-ok   { background:#DCFCE7; color:#15803D; }
.b-fail { background:#FEE2E2; color:#DC2626; }

/* Progress bar */
.pb-wrap { background:#E2E8F0; border-radius:999px; height:7px; overflow:hidden; margin-top:5px; }
.pb-fill  { height:100%; border-radius:999px; }
.pb-g { background:#22C55E; }
.pb-a { background:#F59E0B; }
.pb-r { background:#EF4444; }

/* Stats bar */
.stats-bar {
    display:flex; gap:12px; flex-wrap:wrap;
    background:white; border:1px solid #E2E8F0; border-radius:10px;
    padding:14px 20px; margin:8px 0 16px;
    box-shadow:0 1px 2px rgba(0,0,0,.04);
}
.si { text-align:center; min-width:70px; }
.sv { font-size:1.35rem; font-weight:800; color:#1E293B; }
.sl { font-size:10px; color:#64748B; text-transform:uppercase; letter-spacing:.06em; margin-top:1px; }

/* Mini card */
.mcard {
    background:white; border:1px solid #E2E8F0; border-radius:10px;
    padding:18px; text-align:center;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
}
.mc-val  { font-size:1.8rem; font-weight:800; color:#1E293B; }
.mc-sub  { font-size:12px; color:#94A3B8; margin-bottom:8px; }
.mc-lbl  { font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:#64748B; margin-bottom:6px; }

/* N=2 warning */
.n2box {
    background:#FFFBEB; border:1px solid #FDE68A; border-radius:8px;
    padding:8px 14px; font-size:13px; color:#92400E;
    display:inline-block; margin-bottom:14px;
}

/* Attr table row */
.atr { display:flex; gap:8px; align-items:center; padding:5px 0; border-bottom:1px solid #F1F5F9; font-size:13px; }
.atr:last-child { border-bottom:none; }
.atr-n { flex:1; color:#475569; }
.atr-v { font-weight:700; color:#1E293B; min-width:80px; }
.atr-u { color:#94A3B8; font-size:11px; min-width:36px; }
.atr-wrap { background:white; border:1px solid #E2E8F0; border-radius:8px; padding:8px 14px; }

/* Field row in breakdown */
.fr-exp { color:#15803D; }
.fr-got-close { color:#1D4ED8; }
.fr-got-partial { color:#B45309; }
.fr-got-miss { color:#DC2626; }

/* Enrichment status */
.enrich-ok   { background:#F0FDF4; border:1px solid #BBF7D0; border-radius:8px; padding:10px 14px; font-size:13px; }
.enrich-fail { background:#FFF7F7; border:1px solid #FEC5C5; border-radius:8px; padding:10px 14px; font-size:13px; color:#7F1D1D; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def badge(tier: str) -> str:
    cls = {"EXACT": "b-exact", "CLOSE": "b-close", "PARTIAL": "b-partial", "MISS": "b-miss"}.get(tier, "b-miss")
    return f'<span class="badge {cls}">{tier}</span>'

def ok_badge(ok: bool) -> str:
    return f'<span class="badge {"b-ok" if ok else "b-fail"}">{"✓ PASS" if ok else "✗ FAIL"}</span>'

def pbar(pct: float) -> str:
    cls = "pb-g" if pct >= 80 else ("pb-a" if pct >= 50 else "pb-r")
    return f'<div class="pb-wrap"><div class="pb-fill {cls}" style="width:{min(pct,100):.0f}%"></div></div>'

def metric_card(label: str, pct: float, n: int, d: int) -> str:
    return f"""<div class="mcard">
  <div class="mc-lbl">{label}</div>
  <div class="mc-val">{pct:.0f}%</div>
  <div class="mc-sub">{n}/{d} fields</div>
  {pbar(pct)}
</div>"""

def stat_item(val, lbl) -> str:
    return f'<div class="si"><div class="sv">{val}</div><div class="sl">{lbl}</div></div>'

def got_color(tier: str) -> str:
    return {"EXACT": "#15803D", "CLOSE": "#1D4ED8", "PARTIAL": "#B45309", "MISS": "#DC2626"}.get(tier, "#94A3B8")


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_data():
    enriched = pd.read_csv(ENRICHED_CSV, dtype=str).fillna("")
    gt_dict = load_ground_truth(str(GT_CSV))
    return enriched, gt_dict


# ── Guard ─────────────────────────────────────────────────────────────────────

if not ENRICHED_CSV.exists():
    st.error(
        f"**Enriched CSV not found:** `{ENRICHED_CSV}`\n\n"
        "Run the pipeline first:\n```\npython -m unihack.unihack_pipeline --eval-only\n```"
    )
    st.stop()

enriched_df, gt_dict = load_data()
mtime = ENRICHED_CSV.stat().st_mtime
last_updated = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

# ── Page header ───────────────────────────────────────────────────────────────
st.markdown("## 🔬 Unihack Product Intelligence — Pipeline Review")
st.caption(f"Last updated: **{last_updated}** &nbsp;·&nbsp; `{ENRICHED_CSV.name}` &nbsp;·&nbsp; {len(enriched_df)} rows loaded")
st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — EVALUATION VS GROUND TRUTH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📊 Evaluation vs Ground Truth")

gt_mpns = set(gt_dict.keys())
matched_df = enriched_df[enriched_df["Mfg_Part_Num"].isin(gt_mpns)]
n_matched = len(matched_df)
n_gt = len(gt_dict)

st.caption(f"{n_matched}/{n_gt} ground-truth parts found in this run")
st.markdown('<div class="n2box">⚠️ N=2 — diagnostic sanity check only, not a statistical accuracy claim</div>',
            unsafe_allow_html=True)

if n_matched == 0:
    st.warning("No GT rows found in enriched CSV. Run: `python -m unihack.unihack_pipeline --eval-only`")
else:
    # Score all matched rows
    scored = []
    for _, our_row in matched_df.iterrows():
        mpn = our_row["Mfg_Part_Num"]
        gt_row = gt_dict.get(mpn, {})
        scored.append(score_product(mpn, gt_row, our_row.to_dict()))

    all_frs = [fr for ps in scored for fr in ps.field_results]

    def _field_score(names):
        frs = [fr for fr in all_frs if fr.field in names]
        if not frs:
            return 0.0, 0, 0
        hit = sum(1 for fr in frs if fr.tier in ("EXACT", "CLOSE"))
        return hit / len(frs) * 100, hit, len(frs)

    cls_pct, cls_h, cls_t = _field_score(["Classpath"])
    mfr_pct, mfr_h, mfr_t = _field_score(["MANUFACTURER_NAME", "BRAND_NAME"])
    dsc_pct, dsc_h, dsc_t = _field_score(["INVOICE_DESC", "MOBILE_DESC", "SHORT_DESC", "RETAIL_DESC"])

    # ── Summary metric cards ──────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    c1.markdown(metric_card("Classpath Accuracy", cls_pct, cls_h, cls_t), unsafe_allow_html=True)
    c2.markdown(metric_card("Manufacturer + Brand", mfr_pct, mfr_h, mfr_t), unsafe_allow_html=True)
    c3.markdown(metric_card("Description Match", dsc_pct, dsc_h, dsc_t), unsafe_allow_html=True)

    # ── Description rate bars ─────────────────────────────────────────────────
    st.markdown("#### Description Match Rates")
    dcols = st.columns(4)
    for i, fname in enumerate(["INVOICE_DESC", "MOBILE_DESC", "SHORT_DESC", "RETAIL_DESC"]):
        frs = [fr for fr in all_frs if fr.field == fname]
        avg_sim = sum(fr.similarity for fr in frs) / len(frs) * 100 if frs else 0
        best = min(frs, key=lambda x: ["EXACT","CLOSE","PARTIAL","MISS"].index(x.tier)).tier if frs else "MISS"
        with dcols[i]:
            st.markdown(f"""<div class="mcard">
  <div class="mc-lbl">{fname.replace('_',' ')}</div>
  <div class="mc-val">{avg_sim:.0f}%</div>
  <div style="margin-bottom:6px">{badge(best)}</div>
  {pbar(avg_sim)}
</div>""", unsafe_allow_html=True)

    # ── Per-row breakdown ─────────────────────────────────────────────────────
    st.markdown("#### Per-Row Field Breakdown")
    st.caption("Each row shows Expected (green) vs Got (colored by tier). Expand a row to inspect all fields.")

    for ps in scored:
        overall = ps.close_count / ps.total * 100 if ps.total else 0
        tier_counts = f"exact {ps.exact_count}  ·  close {ps.close_count}  ·  total {ps.total}"
        with st.expander(f"**{ps.mpn}** — {tier_counts}", expanded=True):
            # Column headers
            h = st.columns([2.2, 0.7, 1.0, 3.8, 3.8])
            for col, label in zip(h, ["Field", "Sim", "Tier", "Expected (GT)", "Got (pipeline)"]):
                col.markdown(f"<small style='color:#94A3B8;font-weight:700;text-transform:uppercase;letter-spacing:.06em'>{label}</small>",
                             unsafe_allow_html=True)
            st.markdown("<hr style='margin:4px 0 8px;border:none;border-top:1px solid #E2E8F0'>", unsafe_allow_html=True)

            for fr in ps.field_results:
                cols = st.columns([2.2, 0.7, 1.0, 3.8, 3.8])
                cols[0].markdown(f"<small style='color:#475569;font-family:monospace'>{fr.field}</small>",
                                 unsafe_allow_html=True)
                cols[1].markdown(f"<small style='color:#64748B'>{fr.similarity:.0%}</small>",
                                 unsafe_allow_html=True)
                cols[2].markdown(badge(fr.tier), unsafe_allow_html=True)

                exp_disp = (fr.expected[:75] + "…") if len(fr.expected) > 75 else fr.expected
                got_disp = (fr.got[:75] + "…") if len(fr.got) > 75 else fr.got

                exp_color = "#64748B"
                got_color_val = got_color(fr.tier)
                _empty_html = "<em style='color:#CBD5E1'>empty</em>"
                exp_content = exp_disp if exp_disp else _empty_html
                got_content = got_disp if got_disp else _empty_html

                cols[3].markdown(
                    f"<small style='color:{exp_color}'>{exp_content}</small>",
                    unsafe_allow_html=True
                )
                cols[4].markdown(
                    f"<small style='color:{got_color_val}'>{got_content}</small>",
                    unsafe_allow_html=True
                )

            # Char-limit checks
            if ps.char_limit_checks:
                st.markdown("<hr style='margin:10px 0 6px;border:none;border-top:1px solid #E2E8F0'>",
                            unsafe_allow_html=True)
                st.markdown("<small style='font-weight:700;color:#475569'>Format checks:</small>",
                            unsafe_allow_html=True)
                for fname, chk in ps.char_limit_checks.items():
                    ok = chk["pass"]
                    lo, hi, _ = CHAR_LIMIT_RULES[fname]
                    color = "#15803D" if ok else "#DC2626"
                    icon = "✓" if ok else "✗"
                    rule = f"want {lo}–{hi} chars"
                    val_preview = chk["value"][:60] + ("…" if len(chk["value"]) > 60 else "")
                    st.markdown(
                        f"<small style='color:{color}'><b>{icon} {fname}</b>: "
                        f"len={chk['length']} ({rule}) — <em>{val_preview or 'empty'}</em></small>",
                        unsafe_allow_html=True
                    )

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — FULL ENRICHED CATALOG
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("### 📦 Full Enriched Catalog")

if enriched_df.empty:
    st.info("No enriched data yet. Run: `python -m unihack.unihack_pipeline`")
    st.stop()

# ── Live stats bar ────────────────────────────────────────────────────────────
n = len(enriched_df)
misc_path = "Hardware>General Hardware>Miscellaneous"
n_classified   = (enriched_df["Classpath"].fillna("") != misc_path).sum()
n_brand        = (enriched_df["BRAND_NAME"].fillna("") != "").sum()
n_enriched     = (enriched_df["_enriched"].fillna("") == "True").sum()
n_invoice_ok   = (enriched_df["_invoice_desc_ok"].fillna("") == "True").sum()
n_mobile_ok    = (enriched_df["_mobile_desc_ok"].fillna("") == "True").sum()

def pct(a, b): return f"{a/b*100:.0f}%" if b else "—"

st.markdown(f"""
<div class="stats-bar">
  {stat_item(n, "Total Rows")}
  {stat_item(pct(n_classified, n), "Classified")}
  {stat_item(pct(n_brand, n), "Brand Found")}
  {stat_item(pct(n_enriched, n), "Web-Enriched")}
  {stat_item(pct(n_invoice_ok, n), "Invoice OK")}
  {stat_item(pct(n_mobile_ok, n), "Mobile OK")}
  {stat_item(n_classified, "of {n} Classified")}
  {stat_item(n_enriched, "of {n} Enriched")}
</div>
""".replace("{n}", str(n)), unsafe_allow_html=True)

# ── Filters ───────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns([3, 2, 2])
with fc1:
    search_q = st.text_input("🔍 Search", placeholder="MPN, brand, keyword…", label_visibility="collapsed")
with fc2:
    dept_opts = ["All depts"] + sorted(enriched_df["Dept"].replace("", pd.NA).dropna().unique().tolist())
    dept_sel = st.selectbox("Department", dept_opts, label_visibility="collapsed")
with fc3:
    enr_opts = ["All enrichment", "Enriched only", "Not enriched"]
    enr_sel = st.selectbox("Enrichment", enr_opts, label_visibility="collapsed")

filt = enriched_df.copy()
if search_q:
    q = search_q.lower()
    mask = (
        filt["Mfg_Part_Num"].str.lower().str.contains(q, na=False) |
        filt["BRAND_NAME"].str.lower().str.contains(q, na=False) |
        filt["MANUFACTURER_NAME"].str.lower().str.contains(q, na=False) |
        filt["INVOICE_DESC"].str.lower().str.contains(q, na=False) |
        filt["MOBILE_DESC"].str.lower().str.contains(q, na=False) |
        filt["Part_Desc"].str.lower().str.contains(q, na=False)
    )
    filt = filt[mask]
if dept_sel != "All depts":
    filt = filt[filt["Dept"] == dept_sel]
if enr_sel == "Enriched only":
    filt = filt[filt["_enriched"] == "True"]
elif enr_sel == "Not enriched":
    filt = filt[filt["_enriched"] != "True"]

# ── Build display dataframe ───────────────────────────────────────────────────
def n_attrs(row):
    return sum(1 for i in range(1, 11) if row.get(f"ATTRIBUTE_LABEL_{i}", "").strip())

display_rows = []
for _, r in filt.iterrows():
    display_rows.append({
        "MPN":          r.get("Mfg_Part_Num", ""),
        "Brand":        r.get("BRAND_NAME", ""),
        "Manufacturer": r.get("MANUFACTURER_NAME", ""),
        "Classpath":    r.get("Classpath", ""),
        "Product Type": r.get("Product Name", ""),
        "INVOICE_DESC": r.get("INVOICE_DESC", ""),
        "MOBILE_DESC":  r.get("MOBILE_DESC", ""),
        "SHORT_DESC":   r.get("SHORT_DESC", ""),
        "Enriched":     "✓" if r.get("_enriched") == "True" else "✗",
        "Attrs":        n_attrs(r.to_dict()),
        "Inv OK":       "✓" if r.get("_invoice_desc_ok") == "True" else "✗",
        "Mob OK":       "✓" if r.get("_mobile_desc_ok") == "True" else "✗",
        "Method":       r.get("_brand_resolution_method", ""),
    })
display_df = pd.DataFrame(display_rows)
st.caption(f"Showing {len(display_df)} of {n} rows")
st.dataframe(display_df, use_container_width=True, height=380)

# ── Row detail panel ──────────────────────────────────────────────────────────
st.markdown("#### Row Detail")
mpn_list = filt["Mfg_Part_Num"].tolist()
chosen = st.selectbox(
    "Inspect row:",
    ["(select a row)"] + mpn_list,
    label_visibility="collapsed"
)

if chosen and chosen != "(select a row)":
    rows = enriched_df[enriched_df["Mfg_Part_Num"] == chosen]
    if rows.empty:
        st.warning("Row not found.")
    else:
        r = rows.iloc[0].to_dict()
        enriched_ok = r.get("_enriched") == "True"
        source_url = r.get("_enrichment_source", "")

        d1, d2 = st.columns(2)

        # Left: identity + enrichment status
        with d1:
            st.markdown("**Identity**")
            st.markdown(f"""
<div style="background:white;border:1px solid #E2E8F0;border-radius:10px;padding:16px;font-size:13px;line-height:2.1">
<b>MPN:</b> {r.get('Mfg_Part_Num','')}<br>
<b>Manufacturer:</b> {r.get('MANUFACTURER_NAME','') or '—'}<br>
<b>Brand:</b> {r.get('BRAND_NAME','') or '—'}<br>
<b>Classpath:</b> {r.get('Classpath','') or '—'}<br>
<b>Dept · Class · Fine:</b> {r.get('Dept','')} · {r.get('Class','')} · {r.get('Fine','')}<br>
<b>Brand resolution:</b> <code>{r.get('_brand_resolution_method','')}</code><br>
<b>Classification method:</b> <code>{r.get('_classification_method','')}</code> &nbsp;
<em style="color:#94A3B8">confidence: {r.get('_classification_confidence','')}</em>
</div>""", unsafe_allow_html=True)

            st.markdown("<div style='margin-top:10px'><b>Web Enrichment</b></div>", unsafe_allow_html=True)
            if enriched_ok and source_url:
                st.markdown(f"""<div class="enrich-ok">
✓ Enriched from manufacturer page<br>
<a href="{source_url}" target="_blank" style="font-size:12px">{source_url[:90]}</a>
</div>""", unsafe_allow_html=True)
            else:
                st.markdown("""<div class="enrich-fail">
✗ Not enriched — no manufacturer page found<br>
<small>DuckDuckGo search returned 0 manufacturer-domain results. Product may be a
display-only floor model, or the MPN is not indexed on the manufacturer website.</small>
</div>""", unsafe_allow_html=True)

        # Right: extracted attributes
        with d2:
            st.markdown("**Extracted Attributes**")
            attrs = [
                (r.get(f"ATTRIBUTE_LABEL_{i}",""), r.get(f"ATTRIBUTE_VALUE_{i}",""), r.get(f"ATTRIBUTE_UOM_{i}",""))
                for i in range(1, 11)
                if r.get(f"ATTRIBUTE_LABEL_{i}", "").strip()
            ]
            if attrs:
                rows_html = "".join(
                    f'<div class="atr"><span class="atr-n">{nm}</span>'
                    f'<span class="atr-v">{vl}</span><span class="atr-u">{um}</span></div>'
                    for nm, vl, um in attrs
                )
                st.markdown(f'<div class="atr-wrap">{rows_html}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div class="atr-wrap" style="color:#94A3B8;font-size:13px">'
                    'No attributes extracted — enrichment did not produce spec data.</div>',
                    unsafe_allow_html=True
                )

        # Generated descriptions
        st.markdown("**Generated Descriptions**")
        desc_specs = [
            ("INVOICE_DESC", "_invoice_desc_ok", "≤40 chars, ALL CAPS"),
            ("MOBILE_DESC",  "_mobile_desc_ok",  "60–80 chars, sentence case"),
            ("SHORT_DESC",   None,               "Title case"),
            ("LONG_DESC1",   None,               "Full spec dump"),
            ("RETAIL_DESC",  None,               "No brand/MPN"),
        ]
        for fname, ok_key, rule in desc_specs:
            val = r.get(fname, "")
            ok = r.get(ok_key, "True") == "True" if ok_key else True
            color = "#15803D" if ok else "#DC2626"
            icon = "✓" if ok else "✗"
            preview = (val[:110] + "…") if len(val) > 110 else val
            _empty_span = "<em style='color:#CBD5E1'>empty</em>"
            preview_content = preview if preview else _empty_span
            st.markdown(
                f"<div style='margin-bottom:8px'>"
                f"<small style='color:{color};font-weight:700'>{icon} {fname}</small>"
                f"&nbsp;<small style='color:#94A3B8'>{rule} · {len(val)} chars</small><br>"
                f"<small style='color:#334155;padding-left:14px'>{preview_content}</small>"
                f"</div>",
                unsafe_allow_html=True
            )
