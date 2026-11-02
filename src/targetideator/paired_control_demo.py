"""P6.3 proposer-only versus falsify-revise paired-control dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.paired_control_store import (
    PairedControlStore,
    load_default_paired_control_store,
)


@lru_cache(maxsize=1)
def paired_control_store() -> PairedControlStore:
    return load_default_paired_control_store()


def paired_control_payload() -> dict:
    store = paired_control_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "pairs": store.pairs(),
        "false_rejection_queue": store.false_rejection_queue(),
    }


def paired_control_page() -> str:
    store = paired_control_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td><b>{html.escape(row['target_label'])}</b><br><small>{html.escape(row['hypothesis_id'])}</small></td>"
        f"<td>{row['proposer_only_unqualified_proxy_count']}</td>"
        f"<td>{row['full_path_unqualified_proxy_count']}</td>"
        f"<td>{row['revised_counterevidence_retained_count']}/{row['source_counterevidence_binding_count']}</td>"
        f"<td>{html.escape(row['combined_verdict'])} → {html.escape(row['revision_status'])}</td>"
        f"<td>{'REVIEW' if row['potential_false_rejection_review_required'] else '—'}</td></tr>"
        for row in store.pairs()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.3 paired control</title>
<style>:root{{--ink:#172126;--paper:#edf0eb;--panel:#fff;--accent:#225c68;--warn:#963623;--line:#c9d3cb;--ok:#176b50}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1350px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px;vertical-align:top}}small{{color:#5b686a;font-size:11px}}.pair{{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center}}.pair div{{padding:15px;border:1px solid var(--line);border-radius:8px;background:#f8faf7}}.ok{{color:var(--ok)}}@media(max-width:850px){{.panel{{overflow:auto}}.pair{{grid-template-columns:1fr}}}}</style></head>
<body><header><p><a href="/evaluation/dependency-stress">P6.2 dependency stress</a> · <a href="/api/p6/paired-control/critic-cells">Critic-cell audit</a></p><p>TARGETIDEATOR · P6.3 PAIRED PIPELINE CONTROL</p><h1>Same hypotheses, explicit qualification</h1><p class="warning"><b>MODEL-ONLY PAIRED CONTROL.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Hypothesis pairs</small><b>{q.paired_hypothesis_count}</b></div><div><small>Critic cells</small><b>{q.critic_cell_count}</b></div><div><small>Unqualified proxy</small><b>{q.proposer_only_unqualified_proxy_count} → {q.full_path_unqualified_proxy_count}</b></div><div><small>Counterevidence retained</small><b>{q.revised_counterevidence_retained_count}/{q.source_counterevidence_binding_count}</b></div><div><small>Potential false-rejection queue</small><b>{q.false_rejection_queue_count}</b></div></section></header>
<main><section class="panel"><h2>Frozen paired arms</h2><div class="pair"><div><b>Proposer-only</b><br>P3 hypothesis emitted without critic-derived qualifications.</div><b>versus</b><div><b>Generate → falsify → revise</b><br>Same P3 core, P4 fixed critics, P4.1 constraint-only revision.</div></div></section>
<section class="panel" style="margin-top:16px"><h2>Per-hypothesis propagation</h2><table><thead><tr><th>Hypothesis</th><th>Proposer proxy</th><th>Full-path residual</th><th>Counterevidence</th><th>Verdict path</th><th>False-rejection status</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Interpretation boundary</h2><p>Unsupported proxy reduction: <b>{q.unsupported_proxy_reduction_fraction:.0%}</b> · surviving-critic patch leaks: <b class="ok">{q.surviving_critic_patch_leak_count}</b> · false-rejection rate computed: <b>{str(q.false_rejection_rate_computed).lower()}</b>.</p><ul>{limitations}</ul></section></main></body></html>"""
