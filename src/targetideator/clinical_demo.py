"""P1.3 evidence-string and trial-level replay demo."""

from __future__ import annotations

import html
import json
from datetime import date
from functools import lru_cache

from targetideator.evidence.clinical_store import (
    ClinicalHistoryStore,
    load_default_clinical_store,
)

DEFAULT_DISEASE = "MONDO:0005011"
DEFAULT_TARGET = "ENSG00000110944"
DEFAULT_AS_OF = date(2025, 9, 17)
DEFAULT_COMPARE = date(2025, 3, 19)
TARGETS = {
    "ENSG00000110944": "IL23A",
    "ENSG00000162434": "JAK1",
    "ENSG00000181634": "TNFSF15",
    "ENSG00000167207": "NOD2",
}


@lru_cache(maxsize=1)
def clinical_store() -> ClinicalHistoryStore:
    return load_default_clinical_store()


def clinical_payload(
    disease_id: str,
    target_id: str,
    as_of_date: date,
    compare_to: date | None = None,
) -> dict:
    store = clinical_store()
    payload = {
        "query": store.query(disease_id, target_id, as_of_date).model_dump(mode="json"),
        "quality": store.quality_report(),
    }
    if compare_to is not None:
        payload["diff"] = store.diff(
            disease_id, target_id, compare_to, as_of_date
        ).model_dump(mode="json")
    return payload


def _target_options(selected: str) -> str:
    return "".join(
        f"<option value='{identifier}'{' selected' if identifier == selected else ''}>"
        f"{label}</option>"
        for identifier, label in TARGETS.items()
    )


def _evidence_rows(records, store: ClinicalHistoryStore) -> str:
    if not records:
        return "<tr><td colspan='6' class='muted'>No ChEMBL evidence strings for this target.</td></tr>"
    rows = []
    current_names = {
        item.drug.identifier: item.drug.label for item in store.snapshot.drug_metadata
    }
    for record in records:
        raw = store.raw_evidence(record.id) or {}
        display_name = current_names.get(record.drug.identifier, record.drug.identifier)
        rows.append(
            "<tr>"
            f"<td><b>{html.escape(display_name)}</b><small>{record.drug.identifier} · current ChEMBL label</small></td>"
            f"<td><a href='{html.escape(str(record.source_urls[0]))}'>{record.trial.identifier}</a></td>"
            f"<td>{record.clinical_phase if record.clinical_phase is not None else '—'}</td>"
            f"<td>{html.escape(record.clinical_status or '—')}</td><td>{record.score:.2f}</td>"
            "<td><details><summary>raw ↔ normalized</summary>"
            f"<pre>{html.escape(json.dumps(record.model_dump(mode='json'), ensure_ascii=False, indent=2))}</pre>"
            f"<pre>{html.escape(json.dumps(raw, ensure_ascii=False, indent=2))}</pre>"
            "</details></td></tr>"
        )
    return "".join(rows)


def _trial_rows(records, store: ClinicalHistoryStore) -> str:
    if not records:
        return "<tr><td colspan='7' class='muted'>No linked AACT trial rows.</td></tr>"
    rows = []
    for record in records:
        raw = store.raw_trial(record.id) or {}
        rows.append(
            "<tr>"
            f"<td><a href='{html.escape(str(record.source_url))}'>{record.trial.identifier}</a>"
            f"<small>{html.escape(record.brief_title)}</small></td>"
            f"<td>{html.escape(record.overall_status)}</td>"
            f"<td>{html.escape(record.phase or '—')}</td>"
            f"<td>{record.enrollment if record.enrollment is not None else '—'}</td>"
            f"<td>{record.study_first_posted_date}</td>"
            f"<td>{record.last_update_posted_date or '—'}</td>"
            "<td><details><summary>AACT row</summary>"
            f"<pre>{html.escape(json.dumps(raw, ensure_ascii=False, indent=2))}</pre>"
            "</details></td></tr>"
        )
    return "".join(rows)


def clinical_page(
    disease_id: str = DEFAULT_DISEASE,
    target_id: str = DEFAULT_TARGET,
    as_of_date: date = DEFAULT_AS_OF,
    compare_to: date = DEFAULT_COMPARE,
) -> str:
    store = clinical_store()
    result = store.query(disease_id, target_id, as_of_date)
    diff = store.diff(disease_id, target_id, compare_to, as_of_date)
    quality = store.quality_report()
    changes = "".join(
        "<tr>"
        f"<td>{item.nct_id}</td><td>{html.escape(item.earlier_status)} → "
        f"{html.escape(item.later_status)}</td>"
        f"<td>{item.earlier_last_update_posted_date or '—'} → "
        f"{item.later_last_update_posted_date or '—'}</td></tr>"
        for item in diff.changed_trials
    ) or "<tr><td colspan='3' class='muted'>No linked trial status/update changes.</td></tr>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator Clinical History</title><style>
:root{{--ink:#17202a;--muted:#637079;--paper:#f4f1eb;--panel:#fff;--accent:#006c67;--ok:#176b50;--line:#ddd6ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}} header,main{{max-width:1280px;margin:auto;padding:24px}} h1,h2{{font-family:Georgia,serif}} h1{{font-size:40px;margin:8px 0}} .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #3a2d1a0d}} .valid{{background:#e8f4ef;border-left:5px solid var(--ok);padding:13px 17px}} .muted,small{{color:var(--muted)}} small{{display:block}} nav a{{margin-right:14px}} a,summary{{color:var(--accent);font-weight:700}} form{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:12px;align-items:end}} label{{font-weight:700}} select,input,button{{width:100%;padding:10px;border:1px solid #aaa39a;border-radius:7px;background:white}} button{{background:var(--accent);color:white;border:0;font-weight:800}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}} .metric{{background:#f5f7f5;padding:12px;border-radius:8px}} .metric b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #eee4d8;text-align:left;vertical-align:top}} pre{{max-height:330px;overflow:auto;background:#17202a;color:#edf4f3;padding:11px;border-radius:6px;font-size:11px}} details{{margin-top:7px}} @media(max-width:760px){{form{{grid-template-columns:1fr}} header,main{{padding:16px}}}}
</style></head><body><header><nav><a href="/">P0.2 dossier</a><a href="/evidence/history">P1.2 associations</a><a href="/api/p1/clinical/quality">Quality API</a></nav>
<p class="muted">TARGETIDEATOR · P1.3 EVIDENCE-STRING / TRIAL REPLAY</p><h1>Clinical Evidence Timeline</h1>
<p class="valid"><b>HISTORICAL SOURCE BOUNDARIES ENFORCED.</b><br>{html.escape(result.warning)}</p>
<p class="muted">ChEMBL-derived evidence and AACT trial rows are selected independently by cutoff. Current ChEMBL/ClinicalTrials.gov API records are validation-only.</p></header>
<main><section class="panel"><form method="get" action="/evidence/clinical">
<label>Target<select name="target_id">{_target_options(result.target_id)}</select></label>
<label>As of<input type="date" name="as_of_date" value="{as_of_date.isoformat()}"></label>
<label>Compare to<input type="date" name="compare_to" value="{compare_to.isoformat()}"></label>
<input type="hidden" name="disease_id" value="{html.escape(result.disease_id)}"><button type="submit">Replay</button></form></section>
<section class="panel"><h2>Cutoff-selected state</h2><div class="metrics">
<div class="metric"><small>ChEMBL release</small><b>{result.selected_chembl_release or 'none'}</b></div>
<div class="metric"><small>AACT snapshot</small><b>{result.selected_aact_snapshot or 'none'}</b></div>
<div class="metric"><small>Evidence strings</small><b>{len(result.evidence_records)}</b></div>
<div class="metric"><small>Linked trials</small><b>{len(result.trial_records)}</b></div>
<div class="metric"><small>Trial changes</small><b>{len(diff.changed_trials)}</b></div>
<div class="metric"><small>Post-cutoff leakage</small><b>{result.post_cutoff_leakage_count}</b></div>
</div></section>
<section class="panel"><h2>Evidence membership diff</h2><p>{diff.earlier_chembl_release or 'none'} → {diff.later_chembl_release or 'none'} · added {len(diff.added_evidence_keys)} · removed {len(diff.removed_evidence_keys)} · changed {len(diff.changed_evidence)}</p>
<h2>Linked AACT trial changes</h2><table><thead><tr><th>NCT</th><th>Status</th><th>Last update posted</th></tr></thead><tbody>{changes}</tbody></table></section>
<section class="panel"><h2>Individual ChEMBL evidence strings</h2><table><thead><tr><th>Drug</th><th>Trial</th><th>Phase</th><th>ChEMBL status</th><th>Score</th><th>Lineage</th></tr></thead><tbody>{_evidence_rows(result.evidence_records, store)}</tbody></table></section>
<section class="panel"><h2>Historical AACT trial rows</h2><table><thead><tr><th>Trial</th><th>Status</th><th>Phase</th><th>Enrollment</th><th>First posted</th><th>Last update</th><th>Lineage</th></tr></thead><tbody>{_trial_rows(result.trial_records, store)}</tbody></table></section>
<section class="panel"><h2>Acceptance</h2><p class="muted">Evidence→trial coverage {quality['evidence_to_historical_trial_coverage']:.0%} · CT.gov ID validation {quality['ctgov_identifier_validation_coverage']:.0%} · first-posted mismatches {quality['first_posted_mismatch_count']} · deterministic rebuild {str(quality.get('deterministic_rebuild_matches', False)).lower()}</p></section>
</main></body></html>"""
