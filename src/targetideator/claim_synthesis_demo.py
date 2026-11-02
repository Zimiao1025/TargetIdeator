"""P6.5 frozen claim-disposition synthesis dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.synthesis_store import (
    ClaimSynthesisStore,
    load_default_claim_synthesis_store,
)


@lru_cache(maxsize=1)
def claim_synthesis_store() -> ClaimSynthesisStore:
    return load_default_claim_synthesis_store()


def claim_synthesis_payload() -> dict:
    store = claim_synthesis_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "claims": store.claims(),
        "experiments": store.experiments(),
    }


def claim_synthesis_page() -> str:
    store = claim_synthesis_store()
    q = store.snapshot.quality
    claim_rows = "".join(
        f"<tr><td><b>{html.escape(row['claim_code'])}</b><br><small>{html.escape(row['title'])}</small></td>"
        f"<td><code>{html.escape(row['synthesized_status'])}</code></td>"
        f"<td>{row['completed_engineering_control_count']}</td>"
        f"<td>{html.escape(row['synthesized_finding'])}</td>"
        f"<td class='blocked'>no</td></tr>"
        for row in store.claims()
    )
    experiment_rows = "".join(
        f"<tr><td><b>{html.escape(row['experiment_id'])}</b></td>"
        f"<td><code>{html.escape(row['result_class'])}</code></td>"
        f"<td>{html.escape(', '.join(row['primary_claim_codes']))}</td>"
        f"<td>{html.escape(row['observed_finding'])}</td>"
        f"<td class='blocked'>false</td></tr>"
        for row in store.experiments()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.5 claim synthesis</title>
<style>:root{{--ink:#172126;--paper:#ecefe9;--panel:#fff;--accent:#245d67;--warn:#923b27;--line:#cad3cc;--ok:#1c6a4f}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1360px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.finding{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px}}code{{font-size:11px}}small{{color:#59666a}}.blocked{{color:var(--warn);font-weight:800}}.ok{{color:var(--ok)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/evaluation/counterevidence-ablation">P6.4 ablation</a> · <a href="/api/p6/claim-synthesis">JSON synthesis</a> · <a href="/api/p6/claim-synthesis/paper-table">paper table</a></p><p>TARGETIDEATOR · P6.5 FROZEN CLAIM DISPOSITION</p><h1>Four controls closed, zero claims promoted</h1><p class="warning"><b>ENGINEERING SYNTHESIS ONLY.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Paper claims</small><b>{q.claim_count}</b></div><div><small>Engineering controls</small><b>{q.completed_engineering_control_count}</b></div><div><small>Status changes</small><b>{q.claim_status_changed_count}</b></div><div><small>Scientific claims</small><b class="blocked">{q.scientifically_supported_claim_count}</b></div><div><small>Decision-level negatives</small><b>{q.decision_level_negative_result_count}</b></div></section></header>
<main><p class="finding"><b>Frozen disposition:</b> P6.1–P6.4 make the engineering evidence more auditable, but none supplies the missing identification, gold labels, or decision metrics required to promote C1–C6.</p>
<section class="panel"><h2>Claim-by-experiment disposition</h2><table><thead><tr><th>Claim</th><th>Status</th><th>Controls</th><th>Current finding</th><th>Positive conclusion allowed</th></tr></thead><tbody>{claim_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Protocol-conformant experiment ledger</h2><table><thead><tr><th>Experiment</th><th>Result class</th><th>Claims</th><th>Frozen finding</th><th>Scientific gate</th></tr></thead><tbody>{experiment_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Remaining blockers</h2><ul>{limitations}</ul><p>C1 status changed: <b>{str(q.c1_status_changed).lower()}</b> · C4 status changed: <b>{str(q.c4_status_changed).lower()}</b> · formal P6 gate: <b>{str(q.formal_p6_gate_passed).lower()}</b>.</p></section></main></body></html>"""
