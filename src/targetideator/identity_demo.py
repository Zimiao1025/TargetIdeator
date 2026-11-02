"""P5.3 auditable trial→drug→target identity ledger dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.identity_store import (
    IdentityStore,
    load_default_identity_store,
)


@lru_cache(maxsize=1)
def identity_store() -> IdentityStore:
    return load_default_identity_store()


def identity_payload() -> dict:
    store = identity_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "sample_mappings": store.sample_mappings(8),
        "sample_provenance": store.sample_provenance(8),
        "sample_unresolved": store.sample_unresolved(8),
    }


def identity_page() -> str:
    snapshot = identity_store().snapshot
    quality = snapshot.quality
    coverage_rows = "".join(
        f"<tr><td><code>{html.escape(category)}</code></td>"
        f"<td>{coverage.mapped_count:,}/{coverage.total_count:,}</td>"
        f"<td>{coverage.coverage:.1%}</td></tr>"
        for category, coverage in quality.mapping_coverage_by_outcome_category.items()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in quality.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.3 identity ledger</title>
<style>:root{{--ink:#182328;--paper:#f1efe8;--panel:#fff;--accent:#075f66;--warn:#97412f;--line:#d7d1c5}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}a{{color:var(--accent);font-weight:750}}code{{font:12px ui-monospace,monospace}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style></head>
<body><header><p><a href="/outcomes/broad">P5.2 broad benchmark</a> · <a href="/identity/audit">P5.4 mapping audit</a> · <a href="/api/p5/identity/quality">Quality API</a></p><p>TARGETIDEATOR · P5.3 AUDITABLE IDENTITY LEDGER</p><h1>Trial → drug → target, with provenance</h1><p class="warning"><b>IDENTITY ENRICHMENT, NOT A NEW PREDICTIVE MODEL.</b><br>{html.escape(snapshot.warning)}</p>
<section class="metrics"><div><small>source evidence rows</small><b>{quality.source_evidence_row_count:,}</b></div><div><small>mapping triples</small><b>{quality.unique_trial_drug_target_mapping_count:,}</b></div><div><small>mapped unique NCT</small><b>{quality.mapped_unique_nct_count:,}</b><small>{quality.unique_nct_mapping_coverage:.1%}</small></div><div><small>outcome rows mapped</small><b>{quality.outcome_record_mapping_coverage.mapped_count:,}</b><small>{quality.outcome_record_mapping_coverage.coverage:.1%}</small></div><div><small>explicit events mapped</small><b>{quality.explicit_cause_event_mapping_coverage.mapped_count}/{quality.explicit_cause_event_mapping_coverage.total_count}</b></div><div><small>fuzzy auto-maps</small><b>{quality.fuzzy_auto_mapping_count}</b></div></section></header>
<main><section class="grid"><div class="panel"><h2>Non-collapsing identity policy</h2><p>{quality.multi_drug_trial_count:,} trials have multiple drugs; {quality.multi_target_trial_count:,} have multiple targets. Every source-asserted triple is retained with evidence IDs, source Parquet URLs and row checksums.</p><p>AACT train-snapshot exact-name audit: {quality.aact_name_exact_agreement_count:,}/{quality.aact_name_crosscheck_available_mapping_count:,}; disagreement is an audit flag, never an inferred replacement.</p><p><a href="/api/p5/identity/mappings/sample?limit=5">Inspect mapping records →</a></p></div><div class="panel"><h2>Outcome provenance</h2><p>All {quality.outcome_provenance_record_count:,} P5.2 rows retain baseline/outcome raw checksums, stop reason hash, rule ID, lexical cues and negation flags. Mapping release 25.09 is explicitly forbidden as a temporal model feature.</p><p><a href="/api/p5/identity/provenance/sample?limit=5">Inspect provenance rows →</a></p></div></section>
<section class="panel"><h2>Mapping coverage by outcome class</h2><table><thead><tr><th>category</th><th>mapped / total</th><th>coverage</th></tr></thead><tbody>{coverage_rows}</tbody></table></section>
<section class="panel"><h2>Gate remains closed</h2><ul>{limitations}</ul><p>{quality.unmapped_unique_nct_count:,} unique trials remain in an explicit unresolved queue; no automatic target inference is permitted. <a href="/api/p5/identity/unresolved/sample?limit=5">Inspect unresolved rows →</a></p></section></main></body></html>"""
