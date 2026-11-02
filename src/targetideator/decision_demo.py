"""P5 uncalibrated multi-head decision board."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.ideation.store import load_default_ideation_store
from targetideator.scoring.models import DecisionHeadName
from targetideator.scoring.store import DecisionStore, load_default_decision_store


@lru_cache(maxsize=1)
def decision_store() -> DecisionStore:
    return load_default_decision_store()


def decision_payload() -> dict:
    store = decision_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
    }


def _weights(
    causal: float,
    direction: float,
    translation: float,
    feasibility: float,
    safety: float,
) -> dict[DecisionHeadName, float]:
    return {
        DecisionHeadName.CAUSAL_RELEVANCE: causal,
        DecisionHeadName.CORRECT_DIRECTION: direction,
        DecisionHeadName.TRANSLATABLE_EFFICACY: translation,
        DecisionHeadName.MODALITY_FEASIBILITY: feasibility,
        DecisionHeadName.SAFETY_WINDOW: safety,
    }


def decision_page(
    causal_weight: float = 0.2,
    direction_weight: float = 0.2,
    translation_weight: float = 0.2,
    feasibility_weight: float = 0.2,
    safety_weight: float = 0.2,
) -> str:
    store = decision_store()
    snapshot = store.snapshot
    scenario = store.utility_scenario(
        _weights(
            causal_weight,
            direction_weight,
            translation_weight,
            feasibility_weight,
            safety_weight,
        )
    )
    scenario_by_hypothesis = {
        item["hypothesis_id"]: item for item in scenario["results"]
    }
    portfolio = load_default_ideation_store().portfolio
    hypotheses = {item.id: item for item in portfolio.hypotheses}
    cards: list[str] = []
    for decision in snapshot.decisions:
        hypothesis = hypotheses[decision.hypothesis_id]
        heads = []
        for head in decision.heads:
            if head.score is None:
                score_html = "<strong class='missing'>ABSTAIN</strong>"
                bar = ""
            else:
                score_html = f"<strong>{head.score:.2f}</strong>"
                bar = f"<div class='track'><i style='width:{head.score * 100:.0f}%'></i></div>"
            missing = "".join(
                f"<li>{html.escape(item)}</li>" for item in head.missing_requirements
            )
            features = "".join(
                f"<li><code>{html.escape(item.feature_id)}</code> = {html.escape(str(item.value))}"
                f"<small>{item.effect.value}: {html.escape(item.rationale)}</small></li>"
                for item in head.feature_contributions
            )
            heads.append(
                f"""<section class="head {'abstained' if head.abstained else ''}"><div class="head-title"><h3>{head.head_name.value.replace('_', ' ')}</h3>{score_html}</div>{bar}
                <small>ordinal readiness · not probability · {head.uncertainty.value}</small>
                <details><summary>Features, evidence gaps and rule</summary><ul>{features}</ul><ul>{missing}</ul><code>{html.escape(head.rule_id)}</code></details></section>"""
            )
        scenario_row = scenario_by_hypothesis[decision.hypothesis_id]
        utility = (
            f"{scenario_row['utility']:.3f}"
            if scenario_row["utility"] is not None
            else "WITHHELD"
        )
        reasons = "".join(
            f"<li>{html.escape(item)}</li>" for item in decision.abstention_reasons
        )
        cards.append(
            f"""<article class="card"><header class="row"><div><p class="eyebrow">{html.escape(hypothesis.target.label)}</p><h2>{hypothesis.proposed_direction.value} · {hypothesis.proposed_modality.value}</h2><p class="mono">{html.escape(hypothesis.id)}</p></div>
            <div class="status"><strong>{decision.decision_status.value}</strong><span>utility: {utility}</span><span>Pareto: {decision.pareto_status.value}</span></div></header>
            <section class="heads">{''.join(heads)}</section><details><summary>Abstention reasons</summary><ul>{reasons}</ul></details>
            <p><a href="/api/p5/decision-engine/hypotheses/{html.escape(hypothesis.id)}">Inspect decision JSON →</a></p></article>"""
        )
    quality = snapshot.quality
    normalized = scenario["weights"]
    calibration = snapshot.calibration
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5</title>
<style>:root{{--ink:#17202a;--paper:#f1f0ec;--panel:#fff;--accent:#2e5687;--warn:#8a3f16;--line:#d9d3c8;--missing:#a54437}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}body>header,main{{max-width:1450px;margin:auto;padding:24px}}h1,h2,h3{{font-family:Georgia,serif}}h1{{font-size:42px;margin:8px 0}}h2,h3{{margin:0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}
.metrics,.heads{{display:grid;gap:12px}}.metrics{{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:18px 0}}.metrics div,.card,.head,.weights,.calibration{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.weights{{margin:16px 0}}.weights form{{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr)) auto;gap:10px;align-items:end}}input{{width:100%;padding:8px}}button{{padding:9px 14px;background:var(--accent);color:white;border:0;border-radius:7px;font-weight:700}}
.card{{margin-bottom:22px}}.row,.head-title{{display:flex;justify-content:space-between;gap:14px;align-items:center}}.eyebrow{{color:var(--accent);font-weight:800;letter-spacing:.08em;margin:0}}.status{{display:grid;gap:5px;text-align:right}}.status strong,.status span{{background:#eceff4;border-radius:14px;padding:4px 9px;font-size:12px}}.heads{{grid-template-columns:repeat(5,1fr);margin:16px 0}}.head.abstained{{border-color:#d99187;background:#fff7f5}}.head-title strong{{font-size:22px}}.missing{{color:var(--missing);font-size:13px!important}}.track{{height:8px;background:#e4e7ea;border-radius:8px;margin:9px 0;overflow:hidden}}.track i{{display:block;height:100%;background:var(--accent)}}.mono,code,small{{color:#626c76}}.mono,code{{font:12px ui-monospace,monospace}}small{{display:block}}details{{border-top:1px solid var(--line);padding-top:9px;margin-top:9px}}summary{{cursor:pointer;font-weight:750}}a{{color:var(--accent);font-weight:750}}.calibration{{margin:16px 0;border-color:#d99187}}@media(max-width:1100px){{.heads{{grid-template-columns:repeat(2,1fr)}}.weights form{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:650px){{.heads,.weights form{{grid-template-columns:1fr}}.row{{display:block}}.status{{text-align:left}}}}</style></head>
<body><header><p><a href="/revision">P4.1 revisions</a> · <a href="/falsification">P4 falsification</a> · <a href="/api/p5/decision-engine/quality">Quality API</a></p><p>TARGETIDEATOR · P5 DEVELOPMENT SLICE</p><h1>Multi-head decision board</h1>
<p class="warning"><b>UNCALIBRATED — SCORES ARE NOT PROBABILITIES.</b><br>{html.escape(snapshot.warning)}</p>
<section class="metrics"><div><small>Candidates / heads</small><b>{quality.candidate_count}/{quality.head_count}</b></div><div><small>Observed head coverage</small><b>{quality.head_score_coverage:.0%}</b></div><div><small>Upstream blocked</small><b>{quality.upstream_blocked_candidate_count}</b></div><div><small>P5 abstained</small><b>{quality.missing_head_abstention_candidate_count}</b></div><div><small>Pareto frontier</small><b>{quality.pareto_frontier_candidate_count}</b></div></section>
<section class="calibration"><b>Calibration unavailable</b><br>method={calibration.method}; outcome labels={calibration.outcome_label_count}; Brier/ECE/PR-AUC=null. Risk–coverage is withheld because true risk cannot be measured without outcomes.</section>
<section class="weights"><h2>Utility-weight scenario</h2><p>Weights are normalized, but missing heads are never renormalized away and no ranking is performed.</p><form method="get">
<label>Causal<input name="causal_weight" type="number" min="0" step="0.05" value="{normalized['causal_relevance']:.3f}"></label><label>Direction<input name="direction_weight" type="number" min="0" step="0.05" value="{normalized['correct_direction']:.3f}"></label><label>Translation<input name="translation_weight" type="number" min="0" step="0.05" value="{normalized['translatable_efficacy']:.3f}"></label><label>Feasibility<input name="feasibility_weight" type="number" min="0" step="0.05" value="{normalized['modality_feasibility']:.3f}"></label><label>Safety<input name="safety_weight" type="number" min="0" step="0.05" value="{normalized['safety_window']:.3f}"></label><button type="submit">Apply</button></form></section></header>
<main>{''.join(cards)}</main></body></html>"""
