"""P5.4 mapping missingness and unresolved-triage dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.mapping_audit_store import (
    MappingAuditStore,
    load_default_mapping_audit_store,
)

DIMENSIONS = (
    "split",
    "phase",
    "source_class",
    "baseline_status",
    "fda_regulated_drug",
    "outcome_category",
    "intervention_profile",
    "name_stability",
)


@lru_cache(maxsize=1)
def mapping_audit_store() -> MappingAuditStore:
    return load_default_mapping_audit_store()


def mapping_audit_payload() -> dict:
    store = mapping_audit_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "sample_unique_candidate": store.sample_triage(
            5, "exact_mapped_drug_candidate_no_trial_target_assertion"
        ),
        "sample_ambiguous_candidate": store.sample_triage(
            5, "ambiguous_exact_mapped_drug_candidates_no_trial_target_assertion"
        ),
    }


def mapping_audit_page(
    dimension: str = "intervention_profile", min_count: int = 100
) -> str:
    if dimension not in DIMENSIONS:
        dimension = "intervention_profile"
    min_count = max(0, min(min_count, 10000))
    store = mapping_audit_store()
    q = store.snapshot.quality
    rows = store.strata(dimension, min_count)
    table_rows = "".join(
        f"<tr><td><code>{html.escape(row['value'])}</code></td>"
        f"<td>{row['mapped_record_count']:,}/{row['total_record_count']:,}</td>"
        f"<td>{row['coverage']:.1%}</td>"
        f"<td class={'low' if row['coverage_difference_from_overall'] < -0.1 else 'high' if row['coverage_difference_from_overall'] > 0.1 else ''}>"
        f"{row['coverage_difference_from_overall']:+.1%}</td></tr>"
        for row in rows
    )
    options = "".join(
        f"<option value='{item}' {'selected' if item == dimension else ''}>{item}</option>"
        for item in DIMENSIONS
    )
    taxonomy = "".join(
        f"<tr><td><code>{html.escape(reason)}</code></td><td>{count:,}</td>"
        f"<td><a href='/api/p5/mapping-audit/triage/sample?reason={html.escape(reason)}&limit=5'>sample</a></td></tr>"
        for reason, count in q.unresolved_reason_counts.items()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.4 mapping audit</title>
<style>:root{{--ink:#172328;--paper:#f0eee7;--panel:#fff;--accent:#075f66;--warn:#95402d;--line:#d5cec2;--low:#a33a2c;--high:#17694f}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}a{{color:var(--accent);font-weight:750}}code{{font:12px ui-monospace,monospace}}.low{{color:var(--low);font-weight:750}}.high{{color:var(--high);font-weight:750}}form{{display:flex;gap:10px;align-items:end;flex-wrap:wrap}}label{{display:grid;gap:3px}}select,input,button{{font:inherit;padding:7px}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style></head>
<body><header><p><a href="/identity">P5.3 identity ledger</a> · <a href="/identity/resolution">P5.5 drug identity →</a> · <a href="/api/p5/mapping-audit/quality">Quality API</a></p><p>TARGETIDEATOR · P5.4 MAPPING MISSINGNESS AUDIT</p><h1>Coverage gaps become a triage queue</h1><p class="warning"><b>DESCRIPTIVE AUDIT — NO INFERRED MAPPING.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>historical captures</small><b>{q.intervention_capture_complete_count}/{q.intervention_capture_count}</b></div><div><small>unresolved NCT</small><b>{q.unresolved_unique_nct_count:,}</b></div><div><small>unique exact candidates</small><b>{q.unresolved_reason_counts['exact_mapped_drug_candidate_no_trial_target_assertion']:,}</b></div><div><small>ambiguous candidates</small><b>{q.unresolved_reason_counts['ambiguous_exact_mapped_drug_candidates_no_trial_target_assertion']:,}</b></div><div><small>changed names</small><b>{q.repeated_nct_changed_name_count:,}</b></div><div><small>material disparities</small><b>{q.material_coverage_disparity_stratum_count}</b></div></section></header>
<main><section class="grid"><div class="panel"><h2>Fixed unresolved taxonomy</h2><table><thead><tr><th>reason</th><th>NCT</th><th>audit</th></tr></thead><tbody>{taxonomy}</tbody></table></div><div class="panel"><h2>Mapped-name crosscheck</h2><p><b>{q.mapped_nct_exact_name_agreement_count:,}</b> mapped NCT have an exact normalized AACT↔mapped-drug agreement across the three snapshots.</p><p><b>{q.mapped_nct_no_exact_name_agreement_count:,}</b> have therapeutic names but no exact mapped-drug agreement; <b>{q.mapped_nct_without_therapeutic_name_count}</b> have no therapeutic name. These are audit flags, not automatic rejection.</p></div></section>
<section class="panel"><h2>Descriptive coverage strata</h2><form method="get"><label>dimension<select name="dimension">{options}</select></label><label>minimum records<input type="number" name="min_count" min="0" max="10000" value="{min_count}"></label><button type="submit">Apply</button></form><table><thead><tr><th>{html.escape(dimension)}</th><th>mapped / total</th><th>coverage</th><th>delta vs overall</th></tr></thead><tbody>{table_rows}</tbody></table></section>
<section class="panel"><h2>Interpretation boundary</h2><ul>{limitations}</ul><p>Exact candidates only prioritize data repair. They never populate `mapping_ids`, and all candidate records retain `automatic_mapping_permitted=false`.</p></section></main></body></html>"""
