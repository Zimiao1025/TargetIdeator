"""P6.0 reproducible paper-claim and decision replay dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.store import EvaluationStore, load_default_evaluation_store


@lru_cache(maxsize=1)
def evaluation_store() -> EvaluationStore:
    return load_default_evaluation_store()


def evaluation_payload() -> dict:
    store = evaluation_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "claims": store.claims(),
        "replay": store.replay(),
    }


def evaluation_page() -> str:
    store = evaluation_store()
    q = store.snapshot.quality
    claim_rows = "".join(
        f"<tr><td><b>{row['claim_code']}</b><br><small>{html.escape(row['title'])}</small></td>"
        f"<td><span class='status {html.escape(row['current_status'])}'>{html.escape(row['current_status'])}</span></td>"
        f"<td>{html.escape(row['falsification_condition'])}</td>"
        f"<td>{html.escape(row['blockers'][0])}</td></tr>"
        for row in store.claims()
    )
    replay_cards = "".join(
        f"<article><h3>{html.escape(row['target_label'])} · {html.escape(row['proposed_direction'])} · {html.escape(row['proposed_modality'])}</h3>"
        f"<p><code>{html.escape(row['hypothesis_id'])}</code></p>"
        f"<div class='steps'><span>P3<br><b>{html.escape(row['p3_verification_status'])}</b></span>"
        f"<i>→</i><span>P4<br><b>{html.escape(row['p4_combined_verdict'])}</b></span>"
        f"<i>→</i><span>P4.1<br><b>{html.escape(row['p4_1_revision_status'])}</b></span>"
        f"<i>→</i><span>P5<br><b>{html.escape(row['p5_decision_status'])}</b></span></div>"
        f"<p>Support/counterevidence: {row['supporting_claim_count']}/{row['counterevidence_claim_count']} · patches: {row['p4_1_patch_count']} · future outcome: <b>WITHHELD</b></p>"
        f"<p><a href='/api/p6/evaluation/replay/{html.escape(row['hypothesis_id'])}'>Inspect replay JSON →</a></p></article>"
        for row in store.replay()
    )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.0 evaluation audit</title>
<style>:root{{--ink:#182125;--paper:#ecefe9;--panel:#fff;--accent:#174f65;--warn:#98311f;--line:#cad3cb;--muted:#5c696b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1380px;margin:auto;padding:25px}}h1,h2,h3{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#ffe8df;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel,article{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-bottom:1px solid var(--line);padding:10px;vertical-align:top}}small{{color:var(--muted)}}code{{font:12px ui-monospace,monospace}}.status{{display:inline-block;padding:4px 8px;border-radius:12px;background:#ece8df;font:12px ui-monospace,monospace}}.blocked_by_identification,.blocked_by_missing_gold{{color:#8e2e20;background:#fbe1db}}.engineering_evidence_only{{color:#70520a;background:#fff0c9}}.deferred_out_of_scope{{color:#59656b;background:#e8ecee}}.replays{{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:14px}}article h3{{margin:0}}.steps{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr auto 1fr;gap:8px;align-items:center}}.steps span{{background:#f4f7f3;padding:9px;border-radius:7px;min-height:76px}}.steps b{{font-size:11px;word-break:break-word}}.steps i{{color:var(--accent);font-size:20px}}@media(max-width:800px){{.panel{{overflow:auto}}.replays{{grid-template-columns:1fr}}.steps{{grid-template-columns:1fr}}.steps i{{transform:rotate(90deg);text-align:center}}}}</style></head>
<body><header><p><a href="/identity/selection-audit">P5.9 selection audit</a> · <a href="/api/p6/evaluation/quality">Quality API</a></p><p>TARGETIDEATOR · P6.0 CLAIM-TO-ARTIFACT REPLAY</p><h1>Audit the paper before claiming the result</h1><p class="warning"><b>0 SCIENTIFICALLY SUPPORTED HEADLINE CLAIMS.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Paper claims</small><b>{q.paper_claim_count}</b></div><div><small>Headline claims</small><b>{q.headline_claim_count}</b></div><div><small>Scientifically supported</small><b>{q.scientifically_supported_claim_count}</b></div><div><small>Frozen manifests</small><b>{q.artifact_inventory_count}</b></div><div><small>Replayed hypotheses</small><b>{q.replay_hypothesis_count}</b></div><div><small>Future outcomes revealed</small><b>{q.future_outcome_reveal_count}</b></div></section></header>
<main><section class="panel"><h2>Claim registry</h2><table><thead><tr><th>Claim</th><th>Current status</th><th>Predeclared falsification</th><th>Current blocker</th></tr></thead><tbody>{claim_rows}</tbody></table></section>
<section style="margin-top:18px"><h2>Decision replay</h2><p>The replay shows what the frozen system did at each stage. It deliberately ends before a non-identifiable future target outcome.</p><div class="replays">{replay_cards}</div></section>
<section class="panel" style="margin-top:18px"><h2>Publication boundary</h2><ul>{limitations}</ul><p><a href="/api/p6/evaluation/artifacts">Inspect all frozen manifests →</a></p></section></main></body></html>"""
