"""P6.1 fixed-perturbation claim-graph robustness dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.robustness_store import (
    RobustnessStore,
    load_default_robustness_store,
)


@lru_cache(maxsize=1)
def robustness_store() -> RobustnessStore:
    return load_default_robustness_store()


def robustness_payload() -> dict:
    store = robustness_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "scenarios": store.scenarios(),
    }


def robustness_page() -> str:
    store = robustness_store()
    q = store.snapshot.quality
    scenarios = store.scenarios()
    rows = "".join(
        f"<tr><td><code>{html.escape(row['perturbation_kind'])}</code></td>"
        f"<td>{row['requested_fraction']:.0%}</td>"
        f"<td>{row['perturbed_record_count']}</td>"
        f"<td>{row['graph_signature_similarity']:.3f}</td>"
        f"<td>{row['target_signature_changed_count']}/{row['target_count']}</td>"
        f"<td>{row['p3_bound_claim_impacted_count']}/{q.p3_bound_literature_claim_count}</td>"
        f"<td>{row['p3_hypothesis_signature_changed_count']}/5</td>"
        f"<td>{row['dependency_edge_retention']:.1%}</td></tr>"
        for row in scenarios
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.1 graph robustness</title>
<style>:root{{--ink:#182125;--paper:#edf0eb;--panel:#fff;--accent:#174f65;--warn:#963623;--line:#cad3cb;--muted:#5c696b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1400px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:9px;vertical-align:top}}code{{font:12px ui-monospace,monospace}}small{{color:var(--muted)}}.flow{{display:grid;grid-template-columns:repeat(7,auto);gap:9px;align-items:center}}.flow div{{background:#f5f8f4;border:1px solid var(--line);border-radius:8px;padding:13px}}.flow i{{color:var(--accent);font-size:22px}}@media(max-width:900px){{.panel{{overflow:auto}}.flow{{grid-template-columns:1fr}}.flow i{{transform:rotate(90deg);text-align:center}}}}</style></head>
<body><header><p><a href="/evaluation">P6.0 claim audit</a> · <a href="/api/p6/robustness/quality">Quality API</a></p><p>TARGETIDEATOR · P6.1 CLAIM-GRAPH ROBUSTNESS</p><h1>Corrupt the graph; measure propagation</h1><p class="warning"><b>MODEL-ONLY STRUCTURAL EXPERIMENT.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Scenarios</small><b>{q.scenario_count}</b></div><div><small>Severity levels</small><b>1/5/10/20%</b></div><div><small>Literature claims</small><b>{q.provisional_literature_claim_count}</b></div><div><small>Dependency edges</small><b>{q.structured_dependency_edge_count}</b></div><div><small>P3-bound claims</small><b>{q.p3_bound_literature_claim_count}</b></div><div><small>Clinical metrics</small><b>{q.clinical_metric_count}</b></div></section></header>
<main><section class="panel"><h2>Experiment boundary</h2><div class="flow"><div>Frozen graph</div><i>→</i><div>Stable-hash nested perturbation</div><i>→</i><div>Structure + binding signatures</div><i>→</i><div>No refit, no outcome</div></div></section>
<section class="panel" style="margin-top:16px"><h2>Robustness matrix</h2><table><thead><tr><th>Perturbation</th><th>Level</th><th>Changed records</th><th>Graph similarity</th><th>Target signatures</th><th>P3-bound claims</th><th>P3 hypotheses</th><th>Dependency retention</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>What this does not unlock</h2><p>C1 changed: <b>{str(q.c1_status_changed).lower()}</b> · C4 changed: <b>{str(q.c4_status_changed).lower()}</b> · C2 scientific claim unlocked: <b>{str(q.c2_scientific_claim_unlocked).lower()}</b>.</p><ul>{limitations}</ul><p><a href="/api/p6/robustness/ledger">Inspect exact perturbed IDs →</a></p></section></main></body></html>"""
