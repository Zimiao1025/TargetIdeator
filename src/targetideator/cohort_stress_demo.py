"""P6.2 duplicate-cohort dependency stress dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.cohort_stress_store import (
    CohortStressStore,
    load_default_cohort_stress_store,
)


@lru_cache(maxsize=1)
def cohort_stress_store() -> CohortStressStore:
    return load_default_cohort_stress_store()


def cohort_stress_payload() -> dict:
    store = cohort_stress_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "scenarios": store.scenarios(),
        "targets": store.targets(),
    }


def cohort_stress_page() -> str:
    store = cohort_stress_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td>{row['requested_fraction']:.0%}</td>"
        f"<td>{row['selected_family_count']}</td>"
        f"<td>{row['baseline_claim_record_count']} → {row['naive_claim_record_count']}</td>"
        f"<td>{row['baseline_independent_family_count']} → {row['family_blind_independent_count']}</td>"
        f"<td>{row['baseline_independent_family_count']} → {row['dependency_corrected_independent_count']}</td>"
        f"<td>{row['false_independent_units_prevented']}</td></tr>"
        for row in store.scenarios()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.2 cohort stress</title>
<style>:root{{--ink:#172126;--paper:#eef1ec;--panel:#fff;--accent:#225c68;--warn:#973822;--line:#cbd4cc;--ok:#176b50}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1250px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px}}.ok{{color:var(--ok)}}small{{color:#59676a}}@media(max-width:800px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/evaluation/robustness">P6.1 perturbations</a> · <a href="/api/p6/cohort-stress/ledger">Injection ledger</a></p><p>TARGETIDEATOR · P6.2 DUPLICATE-COHORT CONTROL</p><h1>Duplicate records, not independent evidence</h1><p class="warning"><b>MODEL-ONLY COUNT INVARIANCE CONTROL.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Active claims</small><b>{q.baseline_claim_record_count}</b></div><div><small>NCT families</small><b>{q.baseline_independent_family_count}</b></div><div><small>Targets with data</small><b>{q.baseline_target_count}</b></div><div><small>Max naive inflation</small><b>{q.maximum_naive_claim_inflation_fraction:.1%}</b></div><div><small>Max corrected inflation</small><b class="ok">{q.maximum_dependency_corrected_inflation_fraction:.1%}</b></div></section></header>
<main><section class="panel"><h2>Frozen counterfactual</h2><p>Each selected NCT family receives one synthetic three-record copy with new claim and assertion identities, while its evidence-family lineage is retained. The family-blind negative control treats each copy as independent; the dependency-aware path must not.</p></section>
<section class="panel" style="margin-top:16px"><h2>Count propagation</h2><table><thead><tr><th>Injected families</th><th>Families selected</th><th>Naive claims</th><th>Family-blind units</th><th>Corrected units</th><th>False units prevented</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><p>Correction invariant: <b class="ok">{str(q.dependency_correction_invariant_passed).lower()}</b> · stripped-lineage negative control: <b>{str(q.lineage_stripped_negative_control_passed).lower()}</b> · C1/C4 changed: <b>false</b>.</p><ul>{limitations}</ul></section></main></body></html>"""
