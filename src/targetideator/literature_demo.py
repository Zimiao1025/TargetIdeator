"""P2.2 versioned literature and span-grounded claim inspector."""

from __future__ import annotations

import html
from datetime import date
from functools import lru_cache

from targetideator.literature.store import LiteratureStore, load_default_literature_store
from targetideator.literature.review import load_default_review_batch, review_quality_report
from targetideator.literature.comment_resolution import (
    comment_resolution_quality_report,
    load_default_comment_resolution,
)
from targetideator.literature.human_review import (
    assess_human_review_readiness,
    build_human_review_draft,
)

DEFAULT_TARGET = "ENSG00000110944"
DEFAULT_AS_OF = date(2026, 11, 1)
TARGETS = {
    "ENSG00000110944": "IL23A",
    "ENSG00000162434": "JAK1",
    "ENSG00000181634": "TNFSF15",
    "ENSG00000167207": "NOD2",
}


@lru_cache(maxsize=1)
def literature_store() -> LiteratureStore:
    return load_default_literature_store()


def literature_payload(target_id: str, as_of_date: date) -> dict:
    store = literature_store()
    readiness = assess_human_review_readiness(
        build_human_review_draft("A"), build_human_review_draft("B"), store
    )
    return {
        "query": store.query(target_id, as_of_date),
        "quality": store.quality_report(),
        "review": review_quality_report(load_default_review_batch(), store),
        "comment_resolution": comment_resolution_quality_report(
            load_default_comment_resolution(), store
        ),
        "human_review_readiness": readiness.model_dump(mode="json"),
    }


def _target_options(selected: str) -> str:
    return "".join(
        f"<option value='{identifier}'{' selected' if identifier == selected else ''}>"
        f"{label}</option>"
        for identifier, label in TARGETS.items()
    )


def _claim_rows(claims: list[dict], documents: dict[str, dict]) -> str:
    if not claims:
        return "<tr><td colspan='7' class='muted'>No claim spans available at this cutoff.</td></tr>"
    rows = []
    for claim in claims:
        document = documents[claim["document_version_id"]]
        source_id = document["pmid"] or document["pmcid"] or document["source_id"]
        source_url = f"https://europepmc.org/article/MED/{source_id}"
        rows.append(
            "<tr>"
            f"<td><b>{html.escape(claim['target']['label'])}</b><small>{html.escape(claim['theme'])}</small></td>"
            f"<td>{html.escape(claim['polarity'])}</td><td>{html.escape(claim['direction'])}</td>"
            f"<td><q>{html.escape(claim['verbatim_span'])}</q>"
            f"<small>chars {claim['span_start']}:{claim['span_end']} · exact paragraph hash</small></td>"
            f"<td>{html.escape(claim['review_status'])}</td>"
            f"<td><a href='{html.escape(source_url)}'>{html.escape(str(source_id))}</a>"
            f"<small>{html.escape(document['title'])}</small></td>"
            f"<td><a href='/api/p2/literature/claims/{html.escape(claim['id'])}'>lineage</a></td>"
            "</tr>"
        )
    return "".join(rows)


def _relation_rows(relations: list[dict], claims: dict[str, dict]) -> str:
    if not relations:
        return "<tr><td colspan='4' class='muted'>No reviewed relation candidates at this cutoff.</td></tr>"
    return "".join(
        "<tr>"
        f"<td><span class='pill'>{html.escape(item['relation_type'])}</span></td>"
        f"<td>{html.escape(claims[item['source_claim_id']]['target']['label'])}: "
        f"{html.escape(claims[item['source_claim_id']]['theme'])}</td>"
        f"<td>{html.escape(claims[item['target_claim_id']]['target']['label'])}: "
        f"{html.escape(claims[item['target_claim_id']]['theme'])}</td>"
        f"<td>{html.escape(item['rationale'])}</td></tr>"
        for item in relations
    )


def literature_page(
    target_id: str = DEFAULT_TARGET,
    as_of_date: date = DEFAULT_AS_OF,
    layer: str = "provisional_gold",
) -> str:
    store = literature_store()
    result = store.query(target_id, as_of_date)
    quality = store.quality_report()
    documents = {item["id"]: item for item in result["documents"]}
    gold = result["provisional_gold_claims"]
    extracted = result["extracted_claims"]
    claims = gold if layer == "provisional_gold" else extracted
    claim_index = {item["id"]: item for item in gold}
    metrics = quality["extraction_metrics"]
    review = review_quality_report(load_default_review_batch(), store)
    comment_resolution = comment_resolution_quality_report(
        load_default_comment_resolution(), store
    )
    readiness = assess_human_review_readiness(
        build_human_review_draft("A"), build_human_review_draft("B"), store
    )
    layer_options = (
        "<option value='provisional_gold' selected>provisional gold</option>"
        "<option value='extracted'>rule extractor</option>"
        if layer == "provisional_gold"
        else "<option value='provisional_gold'>provisional gold</option>"
        "<option value='extracted' selected>rule extractor</option>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator Literature Claims</title><style>
:root{{--ink:#17202a;--muted:#637079;--paper:#f2f0eb;--panel:#fff;--accent:#8a3d5d;--warn:#9a4b00;--line:#ddd6ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}} header,main{{max-width:1380px;margin:auto;padding:24px}} h1,h2{{font-family:Georgia,serif}} h1{{font-size:40px;margin:8px 0}} .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #3a2d1a0d}} .blocked{{background:#fff0dc;border-left:5px solid var(--warn);padding:13px 17px}} .muted,small{{color:var(--muted)}} small{{display:block}} nav a{{margin-right:14px}} a{{color:var(--accent);font-weight:700}} form{{display:grid;grid-template-columns:2fr 1fr 1.5fr auto;gap:12px;align-items:end}} label{{font-weight:700}} select,input,button{{width:100%;padding:10px;border:1px solid #aaa39a;border-radius:7px;background:white}} button{{background:var(--accent);color:white;border:0;font-weight:800}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}} .metric{{background:#f9f3f5;padding:12px;border-radius:8px}} .metric b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #eee4d8;text-align:left;vertical-align:top}} q{{display:block;max-width:650px}} .pill{{font-size:11px;background:#f4e6ec;padding:3px 7px;border-radius:9px}} @media(max-width:800px){{form{{grid-template-columns:1fr}} header,main{{padding:16px}}}}
</style></head><body><header><nav><a href="/">P0.2 dossier</a><a href="/claims">P2.1 graph</a><a href="/api/p2/literature/quality">Quality API</a></nav>
<p class="muted">TARGETIDEATOR · P2.2 VERSIONED LITERATURE CLAIMS</p><h1>Literature Claim Inspector</h1>
<p class="blocked"><b>P3 GATE BLOCKED.</b><br>{html.escape(metrics['p3_gate_reason'])}</p>
<p class="muted">Current text versions use max(first-index, source-revision) availability. Later revisions are never backfilled into earlier cutoffs.</p></header><main>
<section class="panel"><form method="get" action="/literature"><label>Target<select name="target_id">{_target_options(result.get('target_id', target_id))}</select></label><label>As of<input type="date" name="as_of_date" value="{as_of_date.isoformat()}"></label><label>Layer<select name="layer">{layer_options}</select></label><button type="submit">Inspect</button></form></section>
<section class="panel"><h2>Corpus and gate</h2><div class="metrics">
<div class="metric"><small>Documents visible</small><b>{len(documents)}</b></div>
<div class="metric"><small>Gold candidates</small><b>{len(gold)}</b></div>
<div class="metric"><small>Extracted claims</small><b>{len(extracted)}</b></div>
<div class="metric"><small>Double-review queue</small><b>{quality['double_review_task_count']}</b></div>
<div class="metric"><small>Model pre-review</small><b>{review['model_pass_count']}/60</b></div>
<div class="metric"><small>Human signed</small><b>{review['human_signed_review_count']}/60</b></div>
<div class="metric"><small>Pre-review conflicts</small><b>{review['disagreement_count']}</b></div>
<div class="metric"><small>Comment proposals</small><b>{comment_resolution['proposed_accept_count']}/{comment_resolution['proposed_reject_count']}/{comment_resolution['proposed_revise_count']}</b></div>
<div class="metric"><small>Human confirmed</small><b>{readiness.reviewer_a_confirmed_count + readiness.reviewer_b_confirmed_count}/60</b></div>
<div class="metric"><small>Exact-span F1</small><b>{metrics['exact_span_f1']:.2f}</b></div>
<div class="metric"><small>Relation F1</small><b>{metrics['relation_f1']:.2f}</b></div>
<div class="metric"><small>P3 eligible</small><b>{quality['p3_eligible_claim_count']}</b></div></div></section>
<section class="panel"><h2>{html.escape(layer.replace('_', ' ').title())} claims</h2><table><thead><tr><th>Target/theme</th><th>Polarity</th><th>Direction</th><th>Verbatim span</th><th>Review</th><th>Document version</th><th>Audit</th></tr></thead><tbody>{_claim_rows(claims, documents)}</tbody></table></section>
<section class="panel"><h2>Provisional semantic relations</h2><p class="muted">Supports does not imply replication. Replicates is emitted only for a different document with explicit confirmation language; every edge remains provisional.</p><table><thead><tr><th>Type</th><th>Source</th><th>Target</th><th>Rationale</th></tr></thead><tbody>{_relation_rows(result['relations'], claim_index)}</tbody></table></section>
</main></body></html>"""
