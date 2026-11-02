"""P6.4 counterevidence-role masking ablation dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.counterevidence_ablation_store import (
    CounterevidenceAblationStore,
    load_default_counterevidence_ablation_store,
)


@lru_cache(maxsize=1)
def counterevidence_ablation_store() -> CounterevidenceAblationStore:
    return load_default_counterevidence_ablation_store()


def counterevidence_ablation_payload() -> dict:
    store = counterevidence_ablation_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "hypotheses": store.hypotheses(),
        "changed_cells": store.cells(changed_only=True),
    }


def counterevidence_ablation_page() -> str:
    store = counterevidence_ablation_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td><b>{html.escape(row['target_label'])}</b></td>"
        f"<td>{row['masked_binding_count']}</td>"
        f"<td>{html.escape(row['full_combined_verdict'])} → {html.escape(row['masked_combined_verdict'])}</td>"
        f"<td>{row['full_non_survive_critic_count']} → {row['masked_non_survive_critic_count']}</td>"
        f"<td>{row['full_projected_revision_field_count']} → {row['masked_projected_revision_field_count']}</td>"
        f"<td>{str(row['block_decision_changed']).lower()}</td></tr>"
        for row in store.hypotheses()
    )
    changed = "".join(
        f"<li><b>{html.escape(row['critic_type'])}</b> · {html.escape(row['full_verdict'])} → {html.escape(row['masked_verdict'])} · <code>{html.escape(row['full_rule_id'])}</code> → <code>{html.escape(row['masked_rule_id'])}</code></li>"
        for row in store.cells(changed_only=True)
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.4 counterevidence ablation</title>
<style>:root{{--ink:#172126;--paper:#edf0eb;--panel:#fff;--accent:#225c68;--warn:#963623;--line:#c9d3cb;--neg:#8b3827}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1300px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.finding{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px}}code{{font-size:11px}}.neg{{color:var(--neg)}}@media(max-width:850px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/evaluation/paired-control">P6.3 paired control</a> · <a href="/api/p6/counterevidence-ablation/cells?changed_only=true">Changed cells</a></p><p>TARGETIDEATOR · P6.4 COUNTEREVIDENCE ABLATION</p><h1>Local sensitivity, no decision change</h1><p class="warning"><b>MODEL-ONLY ROLE MASKING.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Masked bindings</small><b>{q.mask_ledger_record_count}</b></div><div><small>Counter references removed</small><b>{q.removed_counterevidence_reference_count}</b></div><div><small>Cell verdict changes</small><b>{q.cell_verdict_changed_count}/20</b></div><div><small>Combined changes</small><b class="neg">{q.combined_verdict_changed_count}/5</b></div><div><small>Block changes</small><b class="neg">{q.block_decision_changed_count}/5</b></div></section></header>
<main><p class="finding"><b>Frozen negative result:</b> explicit counter roles affect local critic behavior, but this five-hypothesis slice shows no combined-verdict or block-decision sensitivity.</p>
<section class="panel"><h2>Hypothesis-level comparison</h2><table><thead><tr><th>Target</th><th>Masked bindings</th><th>Combined verdict</th><th>Non-survive cells</th><th>Projected revision fields</th><th>Block changed</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Cells with verdict or rule changes</h2><ul>{changed}</ul></section>
<section class="panel" style="margin-top:16px"><h2>Interpretation boundary</h2><p>Local sensitivity: <b>{str(q.counterevidence_local_sensitivity_detected).lower()}</b> · decision-level sensitivity: <b>{str(q.counterevidence_decision_level_sensitivity_detected).lower()}</b> · C3 decision-value supported: <b>{str(q.c3_counterevidence_decision_value_supported).lower()}</b>.</p><ul>{limitations}</ul></section></main></body></html>"""
