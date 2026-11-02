"""P5.2 broad outcome benchmark dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.broad_store import (
    BroadOutcomeStore,
    load_default_broad_outcome_store,
)


@lru_cache(maxsize=1)
def broad_outcome_store() -> BroadOutcomeStore:
    return load_default_broad_outcome_store()


def broad_outcome_payload() -> dict:
    store = broad_outcome_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "sample_records": store.sample_records(10),
    }


def broad_outcome_page() -> str:
    snapshot = broad_outcome_store().snapshot
    quality = snapshot.quality
    rows = []
    for report in snapshot.model_reports:
        if report.evaluations:
            full = next(
                item
                for item in report.evaluations
                if item.name == "full_structured_logistic"
            )
            prevalence = next(
                item
                for item in report.evaluations
                if item.name == "train_prevalence"
            )
            values = (
                f"{full.test_metrics.pr_auc:.6f}",
                "n/a"
                if full.novel_nct_test_metrics.pr_auc is None
                else f"{full.novel_nct_test_metrics.pr_auc:.6f}",
                f"{prevalence.test_metrics.brier_score:.7f}",
                f"{full.test_metrics.brier_score:.7f}",
            )
        else:
            values = ("WITHHELD", "WITHHELD", "WITHHELD", "WITHHELD")
        rows.append(
            f"<tr><td><b>{report.cause.value}</b></td><td>{report.status.value}</td>"
            f"<td>{report.train_positive_count}/{report.validation_positive_count}/"
            f"{report.test_positive_count}/{report.novel_nct_test_positive_count}</td>"
            f"<td>{values[0]}</td><td>{values[1]}</td><td>{values[2]} → {values[3]}</td></tr>"
        )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in quality.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.2</title>
<style>:root{{--ink:#172126;--paper:#f1efe9;--panel:#fff;--accent:#005d62;--warn:#983b2f;--line:#d6d0c6}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1300px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:12px;color:#536068}}a{{color:var(--accent);font-weight:750}}code{{font:12px ui-monospace,monospace}}</style></head>
<body><header><p><a href="/outcomes">P5.1 immune cohort</a> · <a href="/api/p5/outcomes/broad/quality">Quality API</a></p><p>TARGETIDEATOR · P5.2 BROAD OUTCOME BENCHMARK</p><h1>Broad cohort, honest negative result</h1><p class="warning"><b>NOT TARGET OR DRUG SUCCESS PROBABILITY.</b><br>{html.escape(snapshot.warning)}</p>
<section class="metrics"><div><small>landmark records</small><b>{quality.record_count}</b></div><div><small>unique NCT</small><b>{quality.unique_nct_count}</b></div><div><small>novel-NCT test</small><b>{quality.novel_nct_test_count}</b></div><div><small>right-censored</small><b>{quality.right_censored_count}</b></div><div><small>trained heads</small><b>{quality.trained_head_count}/4</b></div></section></header>
<main><section class="panel"><h2>Held-out results</h2><p>Positive counts are train / validation / test / novel-NCT test. Calibration fits validation only. Tiny PR-AUC values are shown rather than hidden behind low Brier scores.</p><table><thead><tr><th>cause</th><th>status</th><th>positives</th><th>test PR-AUC</th><th>novel-NCT PR-AUC</th><th>Brier prevalence → full</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section class="panel"><h2>Why the gate remains closed</h2><ul>{limitations}</ul><p>In particular, novel-NCT test has zero efficacy positives, so efficacy discrimination there is undefined. PK has no positive class in any split and produces no estimator.</p><p><a href="/api/p5/outcomes/broad">Inspect snapshot and sample records →</a></p></section></main></body></html>"""
