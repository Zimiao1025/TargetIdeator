"""P5.9 target-validation selection audit dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.selection_audit_store import (
    SelectionAuditStore,
    load_default_selection_audit_store,
)


@lru_cache(maxsize=1)
def selection_audit_store() -> SelectionAuditStore:
    return load_default_selection_audit_store()


def selection_audit_payload() -> dict:
    store = selection_audit_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "top_imbalances": store.sample_balance(10, "mapped_vs_unmapped", True),
    }


def selection_audit_page() -> str:
    store = selection_audit_store()
    q = store.snapshot.quality
    top = store.sample_balance(8, "mapped_vs_unmapped", True)
    imbalance_rows = "".join(
        f"<tr><td><code>{html.escape(row['feature_name'])}</code></td>"
        f"<td>{row['group_mean']:.3f}</td><td>{row['rest_mean']:.3f}</td>"
        f"<td>{row['standardized_mean_difference']:+.3f}</td></tr>"
        for row in top
    )
    stratum_rows = "".join(
        f"<tr><td><code>{html.escape(stratum)}</code></td>"
        f"<td>{q.support_stratum_counts[stratum]:,}</td>"
        f"<td>{q.stratum_one_vs_rest_roc_auc[stratum]:.3f}</td>"
        f"<td>{q.stratum_one_vs_rest_common_support_fraction[stratum]:.1%}</td>"
        f"<td>{q.max_abs_smd_by_contrast[stratum + '_vs_rest']:.3f}</td></tr>"
        for stratum in q.support_stratum_counts
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.9 selection audit</title>
<style>:root{{--ink:#172328;--paper:#eef1ec;--panel:#fff;--accent:#075f66;--warn:#9e2f20;--line:#cad4cc}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#ffe7df;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:9px;vertical-align:top}}code{{font:12px ui-monospace,monospace}}.gate{{font-size:28px;color:var(--warn);font-weight:850}}.flow{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:center}}.flow div{{background:#f8fbf7;border:1px solid var(--line);border-radius:9px;padding:15px}}.arrow{{font-size:26px;color:var(--accent)}}@media(max-width:850px){{.grid,.flow{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg);text-align:center}}.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/identity/outcome-audit">P5.8 outcome audit</a> · <a href="/api/p5/selection-audit/quality">Quality API</a></p><p>TARGETIDEATOR · P5.9 VALIDATION-READINESS AUDIT</p><h1>Measure selection before measuring targets</h1><p class="warning"><span class="gate">TARGET VALIDATION: NO-GO</span><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Unique NCT</small><b>{q.unique_nct_count:,}</b></div><div><small>Baseline features</small><b>{q.baseline_feature_count}</b></div><div><small>Cross-fit ROC-AUC</small><b>{q.mapping_selection_roc_auc:.3f}</b></div><div><small>Maximum |SMD|</small><b>{q.mapped_vs_unmapped_max_abs_smd:.3f}</b></div><div><small>Material imbalances</small><b>{q.mapped_vs_unmapped_material_imbalance_count}</b></div><div><small>Outcome models fit</small><b>{q.fitted_outcome_model_count}</b></div></section></header>
<main><section class="panel"><h2>Frozen diagnostic chain</h2><div class="flow"><div><b>Earliest pre-outcome landmark</b><br>One record per NCT; repeated landmarks collapsed.</div><span class="arrow">→</span><div><b>Five-fold cross-fitting</b><br>Can baseline attributes predict mapping/support availability?</div><span class="arrow">→</span><div><b>No-go gate</b><br>No outcome labels, reweighting, or target estimates.</div></div></section>
<section class="grid" style="margin-top:16px"><div class="panel"><h2>Largest mapped/unmapped imbalances</h2><table><thead><tr><th>Feature</th><th>Mapped</th><th>Unmapped</th><th>SMD</th></tr></thead><tbody>{imbalance_rows}</tbody></table></div><div class="panel"><h2>Overlap is not exchangeability</h2><p>1–99% common propensity interval: <b>{q.mapping_common_support_lower:.3f}–{q.mapping_common_support_upper:.3f}</b>.</p><p>Overall in common support: <b>{q.mapping_common_support_fraction:.1%}</b><br>Mapped: <b>{q.mapped_group_common_support_fraction:.1%}</b><br>Unmapped: <b>{q.unmapped_group_common_support_fraction:.1%}</b></p><p>Substantial overlap cannot erase observed imbalance or unmeasured selection. It does not authorize IPW/transport estimates.</p></div></section>
<section class="panel" style="margin-top:16px"><h2>Four-stratum diagnostics</h2><table><thead><tr><th>Stratum</th><th>NCT</th><th>one-v-rest AUC</th><th>common support</th><th>max |SMD|</th></tr></thead><tbody>{stratum_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Blocking limitations</h2><ul>{limitations}</ul><p>Outcome-field feature use: <b>{q.outcome_field_used_as_selection_feature_count}</b> · causal adjustments: <b>{q.causal_adjustment_count}</b> · target estimates: <b>{q.target_outcome_estimate_count}</b>.</p></section></main></body></html>"""
