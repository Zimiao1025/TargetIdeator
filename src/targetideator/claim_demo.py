"""P2.1 deterministic claim graph inspector."""

from __future__ import annotations

import html
import json
from datetime import date
from functools import lru_cache

from targetideator.claims.models import ClaimObject
from targetideator.claims.store import ClaimGraphStore, load_default_claim_graph_store

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
def claim_graph_store() -> ClaimGraphStore:
    return load_default_claim_graph_store()


def claim_graph_payload(
    disease_id: str,
    target_id: str,
    as_of_date: date,
    compare_to: date | None = None,
) -> dict:
    store = claim_graph_store()
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


def _object_label(value: ClaimObject) -> str:
    return value.entity.label if value.entity else value.literal or "—"


def _claim_rows(records, store: ClaimGraphStore) -> str:
    if not records:
        return "<tr><td colspan='7' class='muted'>No structured claims at this cutoff.</td></tr>"
    rows = []
    for claim in records:
        lineage = store.claim_lineage(claim.id) or {}
        rows.append(
            "<tr>"
            f"<td><span class='pill'>{html.escape(claim.kind.value)}</span></td>"
            f"<td><b>{html.escape(claim.subject.label)}</b></td>"
            f"<td>{html.escape(claim.predicate)}</td>"
            f"<td>{html.escape(_object_label(claim.object))}</td>"
            f"<td>{html.escape(claim.polarity.value)}</td>"
            f"<td>{html.escape(claim.observed_in)}<small>{claim.available_on}</small></td>"
            "<td><details><summary>claim ↔ source</summary>"
            f"<pre>{html.escape(json.dumps(lineage, ensure_ascii=False, indent=2, default=str))}</pre>"
            "</details></td></tr>"
        )
    return "".join(rows)


def _family_rows(result, store: ClaimGraphStore) -> str:
    if not result.evidence_families:
        return "<tr><td colspan='4' class='muted'>No evidence families.</td></tr>"
    claims = {item.id: item for item in result.claims}
    rows = []
    for family in result.evidence_families:
        members = [claims[item] for item in family.member_claim_ids if item in claims]
        kinds = ", ".join(sorted(item.kind.value for item in members))
        edges = sum(item.evidence_family_id == family.id for item in result.relations)
        rows.append(
            "<tr>"
            f"<td><b>{family.dependency_key}</b></td><td>{len(members)} naive claims</td>"
            f"<td>1 independent unit</td><td>{edges} edges<small>{html.escape(kinds)}</small></td>"
            "</tr>"
        )
    return "".join(rows)


def claim_graph_page(
    disease_id: str = DEFAULT_DISEASE,
    target_id: str = DEFAULT_TARGET,
    as_of_date: date = DEFAULT_AS_OF,
    compare_to: date = DEFAULT_COMPARE,
    dependency_correction: bool = True,
) -> str:
    store = claim_graph_store()
    result = store.query(disease_id, target_id, as_of_date)
    diff = store.diff(disease_id, target_id, compare_to, as_of_date)
    displayed_count = (
        result.independent_evidence_count if dependency_correction else result.naive_claim_count
    )
    correction_options = (
        "<option value='true' selected>on</option><option value='false'>off</option>"
        if dependency_correction
        else "<option value='true'>on</option><option value='false' selected>off</option>"
    )
    changed = "".join(
        f"<li><code>{html.escape(item.assertion_key)}</code><small>changed: "
        f"{html.escape(', '.join(item.changed_fields))}</small></li>"
        for item in diff.changed_claims
    ) or "<li class='muted'>No assertion changes.</li>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator Claim Graph</title><style>
:root{{--ink:#17202a;--muted:#637079;--paper:#f2f0eb;--panel:#fff;--accent:#6553a3;--ok:#176b50;--line:#ddd6ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}} header,main{{max-width:1320px;margin:auto;padding:24px}} h1,h2{{font-family:Georgia,serif}} h1{{font-size:40px;margin:8px 0}} .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #3a2d1a0d}} .boundary{{background:#eeeaf8;border-left:5px solid var(--accent);padding:13px 17px}} .muted,small{{color:var(--muted)}} small{{display:block}} nav a{{margin-right:14px}} a,summary{{color:var(--accent);font-weight:700}} form{{display:grid;grid-template-columns:2fr 1fr 1fr 1.2fr auto;gap:12px;align-items:end}} label{{font-weight:700}} select,input,button{{width:100%;padding:10px;border:1px solid #aaa39a;border-radius:7px;background:white}} input[type=checkbox]{{width:auto}} button{{background:var(--accent);color:white;border:0;font-weight:800}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}} .metric{{background:#f5f4fa;padding:12px;border-radius:8px}} .metric b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #eee4d8;text-align:left;vertical-align:top}} .pill{{font-size:11px;background:#ece8f8;padding:3px 6px;border-radius:9px}} pre{{max-height:360px;overflow:auto;background:#17202a;color:#edf4f3;padding:11px;border-radius:6px;font-size:11px}} code{{font-size:11px}} @media(max-width:800px){{form{{grid-template-columns:1fr}} header,main{{padding:16px}}}}
</style></head><body><header><nav><a href="/">P0.2 dossier</a><a href="/evidence/clinical">P1.3 evidence</a><a href="/api/p2/claims/quality">Quality API</a></nav>
<p class="muted">TARGETIDEATOR · P2.1 DETERMINISTIC CLAIM GRAPH</p><h1>Claim Graph Inspector</h1>
<p class="boundary"><b>INTERPRETATION BOUNDARY.</b><br>{html.escape(result.warning)}</p></header><main>
<section class="panel"><form method="get" action="/claims">
<label>Target<select name="target_id">{_target_options(result.target_id)}</select></label>
<label>As of<input type="date" name="as_of_date" value="{as_of_date.isoformat()}"></label>
<label>Compare to<input type="date" name="compare_to" value="{compare_to.isoformat()}"></label>
<label>Dependency correction<select name="dependency_correction">{correction_options}</select></label>
<input type="hidden" name="disease_id" value="{html.escape(result.disease_id)}"><button type="submit">Inspect</button></form></section>
<section class="panel"><h2>Cutoff-selected graph</h2><div class="metrics">
<div class="metric"><small>ChEMBL release</small><b>{result.selected_chembl_release or 'none'}</b></div>
<div class="metric"><small>AACT snapshot</small><b>{result.selected_aact_snapshot or 'none'}</b></div>
<div class="metric"><small>Naive claims</small><b>{result.naive_claim_count}</b></div>
<div class="metric"><small>Independent families</small><b>{result.independent_evidence_count}</b></div>
<div class="metric"><small>Displayed count</small><b>{displayed_count}</b></div>
<div class="metric"><small>Dependency ratio</small><b>{result.dependency_correction_ratio:.0%}</b></div>
<div class="metric"><small>Post-cutoff leakage</small><b>{result.post_cutoff_leakage_count}</b></div></div></section>
<section class="panel"><h2>Evidence families</h2><p class="muted">Each NCT is one independence unit. Source facts, deterministic assertions, registry rows, and repeated releases remain visible but do not multiply support.</p>
<table><thead><tr><th>Trial family</th><th>Raw representation</th><th>Corrected</th><th>Graph</th></tr></thead><tbody>{_family_rows(result, store)}</tbody></table></section>
<section class="panel"><h2>Temporal assertion diff</h2><p>{compare_to} → {as_of_date} · added {len(diff.added_assertion_keys)} · removed {len(diff.removed_assertion_keys)} · changed {len(diff.changed_claims)}</p><ul>{changed}</ul></section>
<section class="panel"><h2>Atomic claims and provenance</h2><table><thead><tr><th>Kind</th><th>Subject</th><th>Predicate</th><th>Object</th><th>Polarity</th><th>Version</th><th>Lineage</th></tr></thead><tbody>{_claim_rows(result.claims, store)}</tbody></table></section>
</main></body></html>"""
