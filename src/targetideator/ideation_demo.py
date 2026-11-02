"""P3 model-silver candidate and hypothesis portfolio demo."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.ideation.store import IdeationStore, load_default_ideation_store


@lru_cache(maxsize=1)
def ideation_store() -> IdeationStore:
    return load_default_ideation_store()


def ideation_payload() -> dict:
    store = ideation_store()
    return {
        "portfolio": store.portfolio.model_dump(mode="json"),
        "quality": store.quality_report(),
    }


def ideation_page() -> str:
    store = ideation_store()
    portfolio = store.portfolio
    candidate_by_target = {item.target.identifier: item for item in portfolio.candidates}
    cards = []
    for hypothesis in portfolio.hypotheses:
        candidate = candidate_by_target[hypothesis.target.identifier]
        routes = "".join(
            f"<li><b>{html.escape(signal.route.value)}</b> · rank {signal.route_rank} · "
            f"score {signal.route_score:.3f}<small>{html.escape('; '.join(signal.limitations))}</small></li>"
            for signal in candidate.route_signals
        )
        claims = "".join(
            f"<li><code>{html.escape(claim_id)}</code></li>"
            for claim_id in hypothesis.mechanism_claim_ids
        )
        gaps = "".join(f"<li>{html.escape(item)}</li>" for item in hypothesis.information_gaps)
        cards.append(
            f"""<article class="card">
            <div class="row"><h2>{html.escape(hypothesis.target.label)}</h2><span>UNRANKED</span></div>
            <p class="mono">{html.escape(hypothesis.id)}</p>
            <p><b>Direction / modality</b><br>{hypothesis.proposed_direction.value} · {hypothesis.proposed_modality.value}</p>
            <p><b>Cell state</b><br>{html.escape(hypothesis.cell_state)}</p>
            <p><b>Evidence routes ({candidate.route_count}/4)</b></p><ul>{routes}</ul>
            <details open><summary>Bound mechanism claims ({len(hypothesis.mechanism_claim_ids)})</summary><ul>{claims}</ul></details>
            <details><summary>Information gaps</summary><ul>{gaps}</ul></details>
            <a href="/api/p3/ideation/hypotheses/{html.escape(hypothesis.id)}">Inspect JSON →</a>
            </article>"""
        )
    quality = portfolio.quality
    route_metrics = "".join(
        f"<div><small>{route.value}</small><b>{count}</b></div>"
        for route, count in sorted(quality.route_candidate_counts.items(), key=lambda item: item[0].value)
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P3</title>
<style>:root{{--ink:#17202a;--paper:#f2f0eb;--panel:#fff;--accent:#315c9c;--warn:#8a3f16}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
header,main{{max-width:1200px;margin:auto;padding:24px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:8px 0}}
.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics,.grid{{display:grid;gap:16px}}
.metrics{{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:20px 0}}.metrics div,.card{{background:var(--panel);padding:18px;border:1px solid #ddd6ca;border-radius:10px}}
.metrics b{{display:block;font-size:24px}}.grid{{grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}}.row{{display:flex;justify-content:space-between;align-items:center}}.row span{{background:#e8edf5;color:var(--accent);padding:4px 8px;border-radius:12px;font-weight:700}}
.mono,small{{color:#626c76}}.mono,code{{font:12px ui-monospace,monospace}}small{{display:block}}a{{color:var(--accent);font-weight:700}}details{{border-top:1px solid #eee4d8;padding:10px 0}}summary{{cursor:pointer;font-weight:700}}@media(max-width:600px){{.grid{{grid-template-columns:1fr}}}}</style></head>
<body><header><p><a href="/">P0 dossier</a> · <a href="/literature">P2 literature</a> · <a href="/api/p3/ideation/quality">Quality API</a></p>
<p>TARGETIDEATOR · P3 DEVELOPMENT SLICE</p><h1>Unranked hypothesis portfolio</h1>
<p class="warning"><b>SCIENTIFIC VALIDATION GATE NOT PASSED.</b><br>{html.escape(portfolio.warning)}</p>
<section class="metrics"><div><small>Seed candidates recalled</small><b>{quality.recalled_seed_target_count}/{quality.fixed_seed_target_count}</b></div>
<div><small>Hypotheses</small><b>{quality.hypothesis_count}</b></div><div><small>Model-silver claims</small><b>{quality.model_silver_claim_count}</b></div>
<div><small>Engineering gate</small><b>{str(quality.engineering_gate_passed).lower()}</b></div>{route_metrics}</section></header>
<main><section class="grid">{''.join(cards)}</section></main></body></html>"""
