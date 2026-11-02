"""P4 fixed-taxonomy falsification demo."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.falsification.store import (
    FalsificationStore,
    load_default_falsification_store,
)
from targetideator.ideation.store import load_default_ideation_store
from targetideator.literature.store import load_default_literature_store


@lru_cache(maxsize=1)
def falsification_store() -> FalsificationStore:
    return load_default_falsification_store()


def falsification_payload() -> dict:
    store = falsification_store()
    portfolio = load_default_ideation_store().portfolio
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "source_hypotheses": [
            item.model_dump(mode="json") for item in portfolio.hypotheses
        ],
        "quality": store.quality_report(),
    }


def falsification_page() -> str:
    store = falsification_store()
    snapshot = store.snapshot
    portfolio = load_default_ideation_store().portfolio
    hypotheses = {item.id: item for item in portfolio.hypotheses}
    literature = load_default_literature_store().snapshot
    claims = {item.id: item for item in literature.provisional_gold_claims}
    cards: list[str] = []
    for result in snapshot.results:
        hypothesis = hypotheses[result.hypothesis_id]
        critic_cards = []
        for item in result.assessments:
            claim_items = "".join(
                f"<li><code>{html.escape(claim_id)}</code><small>{html.escape(claims[claim_id].verbatim_span)}</small></li>"
                for claim_id in item.evidence_claim_ids
            ) or "<li><em>No bound claim; evidence gap is explicit.</em></li>"
            gaps = "".join(f"<li>{html.escape(gap)}</li>" for gap in item.evidence_gaps)
            critic_cards.append(
                f"""<section class="critic {item.verdict.value}">
                <div class="row"><h3>{html.escape(item.critic_type.value)}</h3><span>{item.verdict.value}</span></div>
                <p><b>Strongest counter-hypothesis</b><br>{html.escape(item.strongest_counter_hypothesis)}</p>
                <p><b>Fatal assumption</b><br>{html.escape(item.fatal_assumption)}</p>
                <p><b>Falsifiable prediction</b><br>{html.escape(item.falsifiable_prediction.statement)}<small><b>Refute if:</b> {html.escape(item.falsifiable_prediction.refutation_condition)}</small></p>
                <details><summary>Evidence and gaps</summary><ul>{claim_items}</ul><ul>{gaps}</ul></details>
                <small>Frozen rule: <code>{html.escape(item.rule_id)}</code> · proposer trace used: false</small>
                </section>"""
            )
        source_claims = "".join(
            f"<li><code>{html.escape(claim_id)}</code></li>"
            for claim_id in hypothesis.mechanism_claim_ids
        )
        revisions = ", ".join(result.revision_fields) or "none"
        cards.append(
            f"""<article class="result">
            <header class="result-head"><div><p class="eyebrow">{html.escape(hypothesis.target.label)}</p>
            <h2>{hypothesis.proposed_direction.value} · {hypothesis.proposed_modality.value}</h2>
            <p class="mono">{html.escape(hypothesis.id)}</p></div><strong class="combined {result.combined_verdict.value}">{result.combined_verdict.value}</strong></header>
            <div class="split"><aside><h3>Source P3 hypothesis</h3>
            <p><b>Population</b><br>{html.escape(hypothesis.population)}</p>
            <p><b>Cell state</b><br>{html.escape(hypothesis.cell_state)}</p>
            <p><b>Evidence layer</b><br>{hypothesis.evidence_layer}</p>
            <details><summary>{len(hypothesis.mechanism_claim_ids)} bound claims</summary><ul>{source_claims}</ul></details>
            <p><b>Combined rationale</b><br>{html.escape(result.combined_rationale)}</p>
            <p><b>Fields to revise</b><br>{html.escape(revisions)}</p>
            <a href="/api/p4/falsification/hypotheses/{html.escape(hypothesis.id)}">Inspect paired JSON →</a></aside>
            <div class="critics">{''.join(critic_cards)}</div></div></article>"""
        )
    quality = snapshot.quality
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P4</title>
<style>:root{{--ink:#17202a;--paper:#f1f0ec;--panel:#fff;--accent:#563b8f;--warn:#8a3f16;--line:#d9d3c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}body>header,main{{max-width:1400px;margin:auto;padding:24px}}
h1,h2,h3{{font-family:Georgia,serif}}h1{{font-size:42px;margin:8px 0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}}.metrics div,.result,aside,.critic{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{font-size:24px;display:block}}
.result{{margin:0 0 22px}}.result-head,.row{{display:flex;justify-content:space-between;align-items:center;gap:16px}}.result-head h2,.row h3{{margin:0}}.eyebrow{{font-weight:800;color:var(--accent);text-transform:uppercase;letter-spacing:.08em;margin:0}}
.combined,.row span{{border-radius:18px;padding:6px 11px;text-transform:uppercase;font:700 12px system-ui}}.abstain{{background:#fff7e4;border-color:#ddbd72!important}}.revise{{background:#f3edff;border-color:#aa91d8!important}}.survive{{background:#e9f6ef;border-color:#79b897!important}}.reject{{background:#fdebea;border-color:#d88982!important}}
.split{{display:grid;grid-template-columns:minmax(260px,.75fr) minmax(600px,2.25fr);gap:16px}}.critics{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.critic h3{{text-transform:capitalize}}.mono,code,small{{color:#626c76}}.mono,code{{font:12px ui-monospace,monospace}}small{{display:block;margin-top:5px}}details{{border-top:1px solid var(--line);padding-top:9px}}summary{{cursor:pointer;font-weight:700}}a{{color:var(--accent);font-weight:700}}ul{{padding-left:20px}}
@media(max-width:900px){{.split,.critics{{grid-template-columns:1fr}}}}</style></head>
<body><header><p><a href="/">P0 dossier</a> · <a href="/ideation">P3 portfolio</a> · <a href="/api/p4/falsification/quality">Quality API</a></p>
<p>TARGETIDEATOR · P4 DEVELOPMENT SLICE</p><h1>Fixed-taxonomy falsification</h1>
<p class="warning"><b>SCIENTIFIC VALIDATION GATE NOT PASSED.</b><br>{html.escape(snapshot.warning)}</p>
<section class="metrics"><div><small>Hypotheses</small><b>{quality.hypothesis_count}</b></div><div><small>Fixed critics</small><b>{quality.critic_assessment_count}</b></div><div><small>Taxonomy coverage</small><b>{quality.taxonomy_coverage:.0%}</b></div><div><small>Claim integrity</small><b>{quality.claim_reference_integrity:.0%}</b></div><div><small>Engineering gate</small><b>{str(quality.engineering_gate_passed).lower()}</b></div></section></header>
<main>{''.join(cards)}</main></body></html>"""
