"""P5.1 temporal outcome cohort and validation-calibrated baseline dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.models import ModelStatus
from targetideator.outcomes.store import OutcomeStore, load_default_outcome_store


@lru_cache(maxsize=1)
def outcome_store() -> OutcomeStore:
    return load_default_outcome_store()


def outcome_payload() -> dict:
    store = outcome_store()
    return {
        "dataset": store.dataset.model_dump(mode="json"),
        "models": store.models.model_dump(mode="json"),
        "quality": store.quality_report(),
    }


def outcome_page() -> str:
    store = outcome_store()
    dataset = store.dataset
    models = store.models
    split_rows = "".join(
        f"<tr><td>{split.value}</td><td>{count}</td>"
        + "".join(
            f"<td>{dataset.quality.cause_positive_counts_by_split[split][cause]}</td>"
            for cause in dataset.quality.cause_positive_counts_by_split[split]
        )
        + "</tr>"
        for split, count in dataset.quality.split_counts.items()
    )
    cards = []
    for report in models.model_reports:
        trained = report.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED
        cards.append(
            f"""<article class="card {'trained' if trained else 'blocked'}">
            <p class="eyebrow">{report.cause.value.upper()}</p>
            <h2>{report.status.value.replace('_', ' ')}</h2>
            <p>train positives <b>{report.train_metrics.positive_count}</b> / {report.train_metrics.sample_count}<br>
            validation positives <b>{report.validation_metrics_uncalibrated.positive_count}</b> / {report.validation_metrics_uncalibrated.sample_count}<br>
            test positives <b>{report.test_metrics_calibrated.positive_count}</b> / {report.test_metrics_calibrated.sample_count}</p>
            <p>test Brier, raw → calibrated<br><b>{report.test_metrics_uncalibrated.brier_score}</b> → <b>{report.test_metrics_calibrated.brier_score}</b></p>
            <p><code>fit=train · calibrate={report.calibration_fit_split} · evaluate=test</code></p>
            </article>"""
        )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in models.quality.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator P5.1 outcomes</title><style>
:root{{--ink:#192126;--paper:#f3f0e9;--panel:#fff;--accent:#006b67;--warn:#983b2f;--line:#d7d0c4}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1250px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:8px 0}}h2{{font-size:21px;margin:2px 0 10px}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics,.grid{{display:grid;gap:14px}}.metrics{{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin:18px 0}}.metrics div,.card,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{font-size:24px;display:block}}.grid{{grid-template-columns:repeat(4,1fr)}}.card.blocked{{border-color:#cb8378;background:#fff8f6}}.eyebrow{{color:var(--accent);font-weight:800;letter-spacing:.08em}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}code{{font:12px ui-monospace,monospace;color:#59656b}}a{{color:var(--accent);font-weight:700}}@media(max-width:850px){{.grid{{grid-template-columns:1fr 1fr}}}}@media(max-width:550px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><header><p><a href="/decision">P5 decision board</a> · <a href="/api/p5/outcomes/quality">Quality API</a></p><p>TARGETIDEATOR · P5.1 TEMPORAL OUTCOMES</p><h1>Registry outcome calibration sandbox</h1>
<p class="warning"><b>DEVELOPMENT ONLY — NOT TARGET SUCCESS PROBABILITY.</b><br>{html.escape(models.warning)}</p>
<section class="metrics"><div><small>landmark records</small><b>{dataset.quality.record_count}</b></div><div><small>unique trials</small><b>{dataset.quality.unique_nct_count}</b></div><div><small>right-censored</small><b>{dataset.quality.right_censored_count}</b></div><div><small>trained heads</small><b>{models.quality.trained_head_count}/4</b></div><div><small>test fit leakage</small><b>{models.quality.test_fit_leakage_count}</b></div></section></header>
<main><section class="panel"><h2>Forward calendar landmarks</h2><table><thead><tr><th>split</th><th>n</th><th>efficacy</th><th>safety</th><th>PK</th><th>strategy</th></tr></thead><tbody>{split_rows}</tbody></table><p>Ongoing at horizon is event-free through the window and administratively right-censored beyond it. Completed is a competing registry event, never efficacy success.</p></section>
<h2>Cause-specific models</h2><section class="grid">{''.join(cards)}</section><section class="panel"><h2>Blocking limitations</h2><ul>{limitations}</ul><p><a href="/api/p5/outcomes/models">Inspect frozen parameters and test predictions →</a></p></section></main></body></html>"""
