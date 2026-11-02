"""P5.5 versioned drug-identity resolution dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.drug_identity_store import (
    DrugIdentityStore,
    load_default_drug_identity_store,
)


@lru_cache(maxsize=1)
def drug_identity_store() -> DrugIdentityStore:
    return load_default_drug_identity_store()


def drug_identity_payload() -> dict:
    store = drug_identity_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "sample_complete": store.sample(5, "complete_exact_family_resolution"),
        "sample_multi_drug": [
            row
            for row in store.sample(100, "complete_exact_family_resolution")
            if row["multi_drug_trial_possible"]
        ][:5],
        "sample_ambiguous": store.sample(
            5, "ambiguous_exact_name_to_multiple_families"
        ),
    }


def drug_identity_page() -> str:
    store = drug_identity_store()
    q = store.snapshot.quality
    statuses = "".join(
        f"<tr><td><code>{html.escape(status)}</code></td><td>{count:,}</td>"
        f"<td><a href='/api/p5/drug-identity/sample?status={html.escape(status)}&limit=5'>sample</a></td></tr>"
        for status, count in q.resolution_status_counts.items()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.5 drug identity resolution</title>
<style>:root{{--ink:#172328;--paper:#ecefe9;--panel:#fff;--accent:#075f66;--warn:#95402d;--line:#ccd5cc;--ok:#17694f;--violet:#62508f}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}a{{color:var(--accent);font-weight:750}}code{{font:12px ui-monospace,monospace}}.flow{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:center;margin:14px 0}}.flow div{{padding:14px;background:#f7faf6;border:1px solid var(--line);border-radius:8px}}.arrow{{font-size:25px;color:var(--accent)}}.safe{{color:var(--ok);font-weight:750}}.blocked{{color:var(--warn);font-weight:750}}.distinct{{border-top:4px solid var(--violet)}}@media(max-width:800px){{.grid,.flow{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg);text-align:center}}}}</style></head>
<body><header><p><a href="/identity/audit">P5.4 mapping audit</a> · <a href="/identity/assertions">P5.6 source assertions →</a> · <a href="/api/p5/drug-identity/quality">Quality API</a></p><p>TARGETIDEATOR · P5.5 VERSIONED DRUG IDENTITY</p><h1>Resolve the drug; preserve the target gap</h1><p class="warning"><b>IDENTITY CANDIDATES ARE NOT TARGET EVIDENCE.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>25.09 molecule rows</small><b>{q.full_dictionary_row_count:,}</b></div><div><small>normalized names</small><b>{q.normalized_dictionary_name_count:,}</b></div><div><small>exact-name matched NCT</small><b>{q.exact_name_matched_trial_count:,}</b></div><div><small>therapeutic coverage</small><b>{q.exact_name_match_coverage_of_therapeutic_unresolved:.1%}</b></div><div><small>true name ambiguity</small><b>{q.ambiguous_name_trial_count:,}</b></div><div><small>target assertion gaps</small><b>{q.target_assertion_gap_count:,}</b></div></section></header>
<main><section class="flow"><div><b>AACT versioned names</b><br>Historical names and aliases from the matching baseline.</div><span class="arrow">→</span><div><b>Open Targets 25.09 families</b><br>Exact normalized names plus source parent hierarchy.</div><span class="arrow">→</span><div><b>Candidate identity only</b><br><span class="blocked">No automatic trial→drug→target assertion.</span></div></section>
<section class="grid"><div class="panel"><h2>Resolution ledger</h2><table><thead><tr><th>status</th><th>NCT</th><th>audit</th></tr></thead><tbody>{statuses}</tbody></table></div><div class="panel distinct"><h2>Two concepts that must stay separate</h2><p><b>{q.multi_family_nonambiguous_trial_count:,} multi-family, nonambiguous trials</b><br>Different intervention names each resolve cleanly; this can be a legitimate combination regimen.</p><p><b>{q.ambiguous_name_trial_count:,} ambiguous-name trials</b><br>At least one individual normalized name resolves to more than one molecule family.</p><p class="safe">Only the second category is identity ambiguity.</p></div></section>
<section class="grid"><div class="panel"><h2>Family hierarchy integrity</h2><p><b>{q.molecule_family_count:,}</b> canonical families from <b>{q.parent_link_count:,}</b> source parent links.</p><p>Cycles: <b>{q.hierarchy_cycle_count}</b> · dangling parent links: <b>{q.dangling_parent_link_count}</b>. Dangling roots remain explicit; they are not silently repaired.</p></div><div class="panel"><h2>Hard boundary</h2><p>Every one of the <b>{q.exact_name_matched_trial_count:,}</b> matched trials retains <code>target_assertion_status=missing_source_asserted_trial_target</code>.</p><p>Automatic drug mappings: <b>{q.automatic_trial_drug_mapping_count}</b> · automatic target mappings: <b>{q.automatic_trial_target_mapping_count}</b> · temporal feature uses: <b>{q.current_identity_used_as_temporal_model_feature_count}</b>.</p></div></section>
<section class="panel"><h2>Known limitations</h2><ul>{limitations}</ul></section></main></body></html>"""
