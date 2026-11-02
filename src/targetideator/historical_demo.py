"""Historical release-membership explorer for P1.2."""

from __future__ import annotations

import html
import json
from datetime import date
from functools import lru_cache
from typing import Any

from targetideator.evidence.historical_store import (
    HistoricalEvidenceStore,
    load_default_historical_store,
)

DEFAULT_DISEASE = "MONDO:0005011"
DEFAULT_TARGET = "ENSG00000167207"
DEFAULT_AS_OF = date(2025, 9, 17)
DEFAULT_COMPARE = date(2025, 3, 19)


@lru_cache(maxsize=1)
def historical_store() -> HistoricalEvidenceStore:
    return load_default_historical_store()


def historical_payload(
    disease_id: str,
    target_id: str,
    as_of_date: date,
    compare_to: date | None = None,
) -> dict[str, Any]:
    store = historical_store()
    result = store.query(disease_id, target_id, as_of_date)
    payload: dict[str, Any] = {
        "query": result.model_dump(mode="json"),
        "releases": store.release_summary(),
    }
    if compare_to is not None:
        payload["diff"] = store.diff(
            disease_id, target_id, compare_to, as_of_date
        ).model_dump(mode="json")
    return payload


def _target_options(selected: str) -> str:
    targets = {
        record.target.identifier: record.target.label
        for record in historical_store().snapshot.records
    }
    return "".join(
        f'<option value="{html.escape(identifier)}" '
        f'{"selected" if identifier == selected else ""}>'
        f"{html.escape(label)} · {html.escape(identifier)}</option>"
        for identifier, label in sorted(targets.items(), key=lambda item: item[1])
    )


def _association_rows(records: list, store: HistoricalEvidenceStore) -> str:
    output = []
    for record in sorted(records, key=lambda item: item.datasource_id):
        raw = store.raw_record(record.id) or {}
        output.append(
            "<tr>"
            f"<td><b>{html.escape(record.datasource_id)}</b><small>{html.escape(record.datatype_id)}</small></td>"
            f"<td>{record.score:.4f}</td><td>{record.evidence_count:,}</td>"
            f"<td>{record.first_observed_release}"
            f"<small>{'≤ earliest observed release' if record.first_observation_left_censored else 'first appeared in observed releases'}</small></td>"
            f"<td><a href='{html.escape(str(record.source_parquet_url))}'>Parquet</a> "
            f"<a href='{html.escape(str(record.association_url))}'>association</a>"
            "<details><summary>raw ↔ normalized</summary>"
            f"<h4>Normalized membership</h4><pre>{html.escape(json.dumps(record.model_dump(mode='json'), ensure_ascii=False, indent=2))}</pre>"
            f"<h4>Raw Parquet row</h4><pre>{html.escape(json.dumps(raw, ensure_ascii=False, indent=2))}</pre>"
            "</details></td></tr>"
        )
    return "".join(output)


def historical_page(
    disease_id: str = DEFAULT_DISEASE,
    target_id: str = DEFAULT_TARGET,
    as_of_date: date = DEFAULT_AS_OF,
    compare_to: date = DEFAULT_COMPARE,
) -> str:
    store = historical_store()
    result = store.query(disease_id, target_id, as_of_date)
    earlier = store.query(disease_id, target_id, compare_to)
    diff = store.diff(disease_id, target_id, compare_to, as_of_date)
    quality = store.quality_report()
    release_rows = "".join(
        f"<tr><td>{item['version']}</td><td>{item['release_date']}</td>"
        f"<td>{item['archive_file_count']}</td><td>{item['dataset_row_count']:,}</td>"
        f"<td>{item['subset_row_count']}</td><td>{item['evidence_count_sum']:,}</td>"
        f"<td class='pass'>{'complete' if item['complete_for_query'] else 'incomplete'}</td></tr>"
        for item in store.release_summary()
    )
    earlier_by_key = {record.membership_key: record for record in earlier.records}
    later_by_key = {record.membership_key: record for record in result.records}
    changed_rows = "".join(
        f"<tr><td>{html.escape((later_by_key.get(change.membership_key) or earlier_by_key[change.membership_key]).datasource_id)}</td>"
        f"<td>{change.earlier_score:.4f} → {change.later_score:.4f}</td>"
        f"<td>{change.earlier_evidence_count:,} → {change.later_evidence_count:,}</td></tr>"
        for change in diff.changed
    ) or "<tr><td colspan='3' class='muted'>No score or evidence-count changes.</td></tr>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator Historical Replay</title><style>
:root{{--ink:#17202a;--muted:#637079;--paper:#f4f1eb;--panel:#fff;--accent:#006c67;--ok:#176b50;--line:#ddd6ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}} header,main{{max-width:1220px;margin:auto;padding:24px}} h1,h2{{font-family:Georgia,serif}} h1{{font-size:40px;margin:8px 0}} .panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #3a2d1a0d}} .valid{{background:#e8f4ef;border-left:5px solid var(--ok);padding:13px 17px}} .muted,small{{color:var(--muted)}} small{{display:block}} nav a{{margin-right:14px}} a,summary{{color:var(--accent);font-weight:700}} form{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:12px;align-items:end}} label{{font-weight:700}} select,input,button{{width:100%;padding:10px;border:1px solid #aaa39a;border-radius:7px;background:white}} button{{background:var(--accent);color:white;border:0;font-weight:800}} .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}} .metric{{background:#f5f7f5;padding:12px;border-radius:8px}} .metric b{{display:block;font-size:20px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #eee4d8;text-align:left;vertical-align:top}} .pass{{color:var(--ok);font-weight:800}} .split{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} pre{{max-height:330px;overflow:auto;background:#17202a;color:#edf4f3;padding:11px;border-radius:6px;font-size:11px}} details{{margin-top:7px}} @media(max-width:760px){{form,.split{{grid-template-columns:1fr}} header,main{{padding:16px}}}}
</style></head><body><header><nav><a href="/">P0.2 dossier</a><a href="/evidence">P1.1 current snapshot</a><a href="/api/p1/history/quality">Quality API</a></nav>
<p class="muted">TARGETIDEATOR · P1.2 ARCHIVED RELEASE REPLAY</p><h1>Historical Association Explorer</h1>
<p class="valid"><b>RETROSPECTIVE RELEASE BOUNDARY VALID.</b><br>{html.escape(result.warning)}</p>
<p class="muted">Snapshot <code>{html.escape(store.snapshot.id)}</code> · exact Open Targets archived Parquet membership · datasource-level direct associations</p></header>
<main><section class="panel"><form method="get" action="/evidence/history">
<label>Target<select name="target_id">{_target_options(result.target_id)}</select></label>
<label>As of<input type="date" name="as_of_date" value="{as_of_date.isoformat()}"></label>
<label>Compare to<input type="date" name="compare_to" value="{compare_to.isoformat()}"></label>
<input type="hidden" name="disease_id" value="{html.escape(result.disease_id)}"><button type="submit">Replay</button></form></section>
<section class="panel"><h2>Release-selected state</h2><div class="metrics">
<div class="metric"><small>Selected release</small><b>{result.selected_release or 'none'}</b></div>
<div class="metric"><small>Association memberships</small><b>{len(result.records)}</b></div>
<div class="metric"><small>Added / removed</small><b>+{len(diff.added_membership_keys)} / −{len(diff.removed_membership_keys)}</b></div>
<div class="metric"><small>Changed score/count</small><b>{len(diff.changed)}</b></div>
<div class="metric"><small>Post-cutoff leakage</small><b>{result.post_cutoff_leakage_count}</b></div>
<div class="metric"><small>Replay valid</small><b>{str(result.retrospective_valid).lower()}</b></div></div></section>
<section class="split"><div class="panel"><h2>Release-to-release changes</h2><p class="muted">{diff.earlier_release or 'none'} → {diff.later_release or 'none'}</p><table><thead><tr><th>Datasource</th><th>Score</th><th>Evidence count</th></tr></thead><tbody>{changed_rows}</tbody></table></div>
<div class="panel"><h2>Frozen release coverage</h2><table><thead><tr><th>Release</th><th>Date</th><th>Files</th><th>Dataset rows</th><th>Subset</th><th>Evidence count</th><th>Status</th></tr></thead><tbody>{release_rows}</tbody></table><p class="muted">Archive file checksum coverage {quality['archive_file_manifest_coverage']:.0%} · deterministic rebuild {str(quality['deterministic_rebuild_matches']).lower()}</p></div></section>
<section class="panel"><h2>Membership rows at {result.selected_release or 'no release'}</h2><table><thead><tr><th>Datasource/family</th><th>Score</th><th>Evidence count</th><th>First observed</th><th>Lineage</th></tr></thead><tbody>{_association_rows(result.records, store)}</tbody></table></section>
</main></body></html>"""
