"""Temporal Evidence Explorer HTML and API helpers."""

from __future__ import annotations

import html
import json
from datetime import date
from functools import lru_cache
from typing import Any

from targetideator.evidence.store import EvidenceStore, load_default_store

DEFAULT_DISEASE = "MONDO:0005011"
DEFAULT_TARGET = "ENSG00000110944"
DEFAULT_AS_OF = date(2026, 11, 1)
DEFAULT_COMPARE = date(2026, 9, 23)


@lru_cache(maxsize=1)
def evidence_store() -> EvidenceStore:
    return load_default_store()


def evidence_payload(
    disease_id: str,
    target_id: str,
    as_of_date: date,
    compare_to: date | None = None,
) -> dict[str, Any]:
    store = evidence_store()
    result = store.query(disease_id, target_id, as_of_date)
    payload: dict[str, Any] = {
        "query": result.model_dump(mode="json"),
        "family_counts": store.family_counts(result.records),
        "timeline": store.timeline(result.records),
    }
    if compare_to is not None:
        payload["diff"] = store.diff(disease_id, target_id, compare_to, as_of_date).model_dump(
            mode="json"
        )
    return payload


def _target_options(selected: str) -> str:
    store = evidence_store()
    targets = {
        record.target.identifier: record.target.label for record in store.snapshot.records
    }
    return "".join(
        f'<option value="{html.escape(identifier)}" '
        f'{"selected" if identifier == selected else ""}>'
        f"{html.escape(label)} · {html.escape(identifier)}</option>"
        for identifier, label in sorted(targets.items(), key=lambda item: item[1])
    )


def _timeline_rows(timeline: list[dict[str, Any]]) -> str:
    if not timeline:
        return "<p class='muted'>No event dates are present at this cutoff.</p>"
    maximum = max(item["count"] for item in timeline)
    return "".join(
        f"<tr><td>{item['year'] or 'unknown'}</td><td>{html.escape(item['datatype_id'])}</td>"
        f"<td><span class='bar' style='width:{max(3, item['count'] / maximum * 100):.1f}%'></span>"
        f"<b>{item['count']}</b></td></tr>"
        for item in timeline
    )


def _record_rows(records: list, store: EvidenceStore, limit: int = 50) -> str:
    output: list[str] = []
    for record in sorted(
        records,
        key=lambda item: (item.event_date or date.min, item.id),
        reverse=True,
    )[:limit]:
        raw = store.raw_record(record.id) or {}
        normalized = {
            "id": record.id,
            "target": record.target.model_dump(mode="json"),
            "disease": record.disease.model_dump(mode="json"),
            "datatype_id": record.datatype_id,
            "datasource_id": record.datasource_id,
            "event_date": record.event_date.isoformat() if record.event_date else None,
            "event_date_precision": record.event_date_precision.value,
            "available_on": record.available_on.isoformat(),
            "availability_basis": record.availability_basis.value,
            "score": record.score,
            "lineage": record.lineage.model_dump(mode="json"),
        }
        source_links = " ".join(
            f'<a href="{html.escape(str(url))}" rel="noreferrer">source</a>'
            for url in record.source_urls[:3]
        )
        output.append(
            "<tr>"
            f"<td>{html.escape(record.datatype_id)}<small>{html.escape(record.datasource_id)}</small></td>"
            f"<td>{record.event_date.isoformat() if record.event_date else 'unknown'}"
            f"<small>precision: {record.event_date_precision.value}</small></td>"
            f"<td>{record.score if record.score is not None else '—'}</td>"
            f"<td>{source_links}<details><summary>raw ↔ normalized</summary>"
            f"<h4>Normalized</h4><pre>{html.escape(json.dumps(normalized, ensure_ascii=False, indent=2))}</pre>"
            f"<h4>Raw Open Targets row</h4><pre>{html.escape(json.dumps(raw, ensure_ascii=False, indent=2))}</pre>"
            "</details></td></tr>"
        )
    return "".join(output)


def evidence_page(
    disease_id: str = DEFAULT_DISEASE,
    target_id: str = DEFAULT_TARGET,
    as_of_date: date = DEFAULT_AS_OF,
    compare_to: date = DEFAULT_COMPARE,
) -> str:
    store = evidence_store()
    result = store.query(disease_id, target_id, as_of_date)
    diff = store.diff(disease_id, target_id, compare_to, as_of_date)
    timeline = store.timeline(result.records)
    families = store.family_counts(result.records)
    quality = store.quality_report()
    family_html = "".join(
        f"<span class='pill'>{html.escape(name)} <b>{count}</b></span>"
        for name, count in families.items()
    ) or "<span class='muted'>No evidence at this cutoff</span>"
    unresolved = store.snapshot.unresolved_entities
    unresolved_html = (
        "<p class='pass'>Queue empty — no entity was force-mapped.</p>"
        if not unresolved
        else "<ul>" + "".join(
            f"<li>{html.escape(item.input_value)}: {html.escape(item.reason)}</li>"
            for item in unresolved
        ) + "</ul>"
    )
    quality_items = {
        "Records": quality["record_count"],
        "Seed mapping precision": f"{quality['seed_panel_mapping_precision']:.0%} (n={quality['seed_panel_mapping_total']})",
        "Lineage coverage": f"{quality['lineage_coverage']:.0%}",
        "Source URL coverage": f"{quality['source_url_coverage']:.0%}",
        "Post-cutoff leakage": quality["post_cutoff_leakage_count"],
        "Deterministic rebuild": "pass" if quality["deterministic_rebuild_matches"] else "fail",
    }
    quality_html = "".join(
        f"<div class='metric'><small>{html.escape(str(name))}</small><b>{html.escape(str(value))}</b></div>"
        for name, value in quality_items.items()
    )
    rows = _record_rows(result.records, store)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator Temporal Evidence Explorer</title>
<style>
:root{{--ink:#17202a;--muted:#637079;--paper:#f4f1eb;--panel:#fff;--accent:#006c67;--warn:#8a3f16;--line:#ddd6ca}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}}
header,main{{max-width:1220px;margin:auto;padding:24px}} h1{{font:700 40px/1.1 Georgia,serif;margin:8px 0}} h2{{font:700 25px Georgia,serif}}
.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:13px 17px;color:#622b0f}} .muted,small{{color:var(--muted)}} small{{display:block}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0;box-shadow:0 4px 18px #3a2d1a0d}}
form{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:12px;align-items:end}} label{{font-weight:700}} select,input,button{{width:100%;padding:10px;border:1px solid #aaa39a;border-radius:7px;background:white}} button{{background:var(--accent);color:white;border:0;font-weight:800;cursor:pointer}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}} .metric{{background:#f5f7f5;padding:12px;border-radius:8px}} .metric b{{display:block;font-size:19px}}
.pill{{display:inline-block;background:#e5efed;color:#075e59;padding:5px 9px;border-radius:18px;margin:3px}} .pass{{color:#176b50;font-weight:700}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:9px;border-bottom:1px solid #eee4d8;text-align:left;vertical-align:top}} .bar{{display:inline-block;height:8px;background:#6cb5ae;margin-right:8px;min-width:3px}}
details{{margin-top:7px}} summary,a{{color:var(--accent);font-weight:700;cursor:pointer}} pre{{max-height:330px;overflow:auto;background:#17202a;color:#edf4f3;padding:11px;border-radius:6px;font-size:11px}}
.split{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} code{{font-size:12px}} nav a{{margin-right:14px}}
@media(max-width:760px){{form,.split{{grid-template-columns:1fr}} header,main{{padding:16px}}}}
</style></head>
<body><header><nav><a href="/">P0.2 hypothesis dossier</a><a href="/evidence/history">P1.2 historical replay</a><a href="/api/p1/quality">Quality API</a></nav>
<p class="muted">TARGETIDEATOR · P1 TEMPORAL EVIDENCE SUBSTRATE</p><h1>Temporal Evidence Explorer</h1>
<p class="warning"><b>ENGINEERING DEMO — NOT A HISTORICAL BACKTEST.</b><br>{html.escape(result.warning)}</p>
<p class="muted">Snapshot <code>{html.escape(store.snapshot.source.id)}</code> · Open Targets {store.snapshot.source.release_version} · released {store.snapshot.source.release_date.isoformat()} · {store.snapshot.source.mode.value}</p></header>
<main><section class="panel"><form method="get" action="/evidence">
<label>Target<select name="target_id">{_target_options(result.target_id)}</select></label>
<label>As of<input type="date" name="as_of_date" value="{as_of_date.isoformat()}"></label>
<label>Compare to<input type="date" name="compare_to" value="{compare_to.isoformat()}"></label>
<input type="hidden" name="disease_id" value="{html.escape(result.disease_id)}"><button type="submit">Apply cutoff</button></form></section>
<section class="panel"><h2>Cutoff result</h2><div class="metrics">
<div class="metric"><small>Visible records</small><b>{len(result.records)}</b></div>
<div class="metric"><small>Excluded after cutoff</small><b>{result.excluded_post_cutoff_count}</b></div>
<div class="metric"><small>Leakage</small><b>{result.post_cutoff_leakage_count}</b></div>
<div class="metric"><small>Diff {compare_to.isoformat()} → {as_of_date.isoformat()}</small><b>+{len(diff.added_ids)} / −{len(diff.removed_ids)}</b></div></div>
<h3>Evidence families</h3>{family_html}</section>
<section class="split"><div class="panel"><h2>Event-date timeline</h2><p class="muted">This is a source event/publication timeline, not proof of historical availability.</p><table><thead><tr><th>Year</th><th>Family</th><th>Count</th></tr></thead><tbody>{_timeline_rows(timeline)}</tbody></table></div>
<div class="panel"><h2>Data quality</h2><div class="metrics">{quality_html}</div><h3>Unresolved entity queue</h3>{unresolved_html}</div></section>
<section class="panel"><h2>Raw ↔ normalized evidence</h2><p class="muted">Showing up to 50 of {len(result.records)} records. Every normalized field carries a raw-record checksum, JSON path map, adapter version, and source link.</p>
<table><thead><tr><th>Family/source</th><th>Event date</th><th>Score</th><th>Lineage</th></tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""
