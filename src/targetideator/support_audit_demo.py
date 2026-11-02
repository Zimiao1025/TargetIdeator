"""P5.8 corroboration-aware outcome provenance dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.support_audit_store import (
    SupportAuditStore,
    load_default_support_audit_store,
)


@lru_cache(maxsize=1)
def support_audit_store() -> SupportAuditStore:
    return load_default_support_audit_store()


def support_audit_payload() -> dict:
    store = support_audit_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "explicit_event_sample": store.sample_explicit_events(8),
    }


def support_audit_page() -> str:
    store = support_audit_store()
    q = store.snapshot.quality
    labels = {
        "unmapped_no_source_assertion": "Unmapped / no assertion",
        "mapped_all_cross_source_pairs": "Mapped / all pairs cross-source",
        "mapped_mixed_pair_support": "Mapped / mixed pair support",
        "mapped_opentargets_chembl_only": "Mapped / OT–ChEMBL only",
    }
    rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(name)}</code><br><small>{labels[name]}</small></td>"
        f"<td>{q.nct_counts_by_support_stratum[name]:,}</td>"
        f"<td>{q.outcome_record_counts_by_support_stratum[name]:,}</td>"
        f"<td>{q.explicit_event_counts_by_support_stratum[name]:,}</td>"
        "</tr>"
        for name in q.nct_counts_by_support_stratum
    )
    category_rows = "".join(
        f"<tr><td>{html.escape(category)}</td>"
        + "".join(f"<td>{counts[name]:,}</td>" for name in q.nct_counts_by_support_stratum)
        + "</tr>"
        for category, counts in q.explicit_event_counts_by_category_and_support_stratum.items()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.8 support audit</title>
<style>:root{{--ink:#172328;--paper:#eef1ec;--panel:#fff;--accent:#075f66;--warn:#95402d;--line:#cad4cc}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.flow{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:center}}.flow div{{background:#f8fbf7;border:1px solid var(--line);border-radius:9px;padding:15px}}.arrow{{font-size:26px;color:var(--accent)}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px;vertical-align:top}}code{{font:12px ui-monospace,monospace}}small{{color:#526168}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}@media(max-width:850px){{.grid,.flow{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg);text-align:center}}.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/identity/corroboration">P5.7 corroboration</a> · <a href="/api/p5/support-audit/quality">Quality API</a></p><p>TARGETIDEATOR · P5.8 OUTCOME PROVENANCE AUDIT</p><h1>Join support to provenance, not to conclusions</h1><p class="warning"><b>NO OUTCOME-RATE COMPARISON.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Outcome provenance</small><b>{q.outcome_provenance_record_count:,}</b></div><div><small>Unique NCT</small><b>{q.unique_nct_count:,}</b></div><div><small>Mapped NCT</small><b>{q.mapped_nct_count:,}</b></div><div><small>Unmapped NCT</small><b>{q.unmapped_nct_count:,}</b></div><div><small>Explicit events</small><b>{q.explicit_event_record_count:,}</b></div><div><small>Model feature use</small><b>{q.support_stratum_used_as_model_feature_count}</b></div></section></header>
<main><section class="panel"><h2>Frozen lineage</h2><div class="flow"><div><b>P5.3 outcome provenance</b><br>Registry state, stop reason, raw hashes and classifier trace.</div><span class="arrow">→</span><div><b>P5.7 source support</b><br>Existing assertions only; no new mapping.</div><span class="arrow">→</span><div><b>P5.8 audit stratum</b><br>Counts and record inspection only; no rates or target attribution.</div></div></section>
<section class="panel" style="margin-top:16px"><h2>Coverage ledger</h2><table><thead><tr><th>Support stratum</th><th>Unique NCT</th><th>Outcome records</th><th>Explicit events</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="grid"><div class="panel"><h2>Explicit event counts</h2><table><thead><tr><th>Category</th><th>Unmapped</th><th>All cross</th><th>Mixed</th><th>Single source</th></tr></thead><tbody>{category_rows}</tbody></table><p><a href="/api/p5/support-audit/explicit-events/sample?limit=10">Inspect verbatim provenance records</a></p></div><div class="panel"><h2>Hard boundaries</h2><p>Mapping changes: <b>{q.mapping_status_change_count}</b><br>Outcome reinterpretations: <b>{q.outcome_interpretation_change_count}</b><br>Causal comparisons: <b>{q.causal_comparison_count}</b><br>Target outcome attributions: <b>{q.target_outcome_attribution_count}</b></p><ul>{limitations}</ul></div></section></main></body></html>"""
