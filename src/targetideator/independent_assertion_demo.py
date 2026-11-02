"""P5.7 independent drug-target corroboration dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.independent_assertion_store import (
    IndependentAssertionStore,
    load_default_independent_assertion_store,
)


@lru_cache(maxsize=1)
def independent_assertion_store() -> IndependentAssertionStore:
    return load_default_independent_assertion_store()


def independent_assertion_payload() -> dict:
    store = independent_assertion_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "cross_source_sample": store.sample_corroborations(
            5, "cross_source_drug_target_supported"
        ),
        "single_source_sample": store.sample_corroborations(
            5, "opentargets_chembl_only"
        ),
    }


def independent_assertion_page() -> str:
    store = independent_assertion_store()
    q = store.snapshot.quality
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    cross_rate = q.cross_source_supported_assertion_count / q.current_source_assertion_count
    pair_rate = q.cross_source_supported_pair_count / q.current_source_pair_count
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.7 independent corroboration</title>
<style>:root{{--ink:#172328;--paper:#edf0ec;--panel:#fff;--accent:#075f66;--warn:#95402d;--line:#cad4cc;--cross:#17694f;--single:#9a5c22}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.flow{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:center}}.flow div{{background:#f8fbf7;border:1px solid var(--line);border-radius:9px;padding:15px}}.arrow{{font-size:26px;color:var(--accent)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}.bar{{height:18px;border-radius:10px;overflow:hidden;background:#eadfd4;display:flex}}.bar span:first-child{{background:var(--cross)}}.cross{{color:var(--cross);font-weight:750}}.single{{color:var(--single);font-weight:750}}code{{font:12px ui-monospace,monospace}}@media(max-width:800px){{.grid,.flow{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg);text-align:center}}}}</style></head>
<body><header><p><a href="/identity/assertions">P5.6 assertion history</a> · <a href="/api/p5/independent-assertions/quality">Quality API</a></p><p>TARGETIDEATOR · P5.7 INDEPENDENT CORROBORATION</p><h1>Corroborate the pair; preserve the trial boundary</h1><p class="warning"><b>DRUG–TARGET SUPPORT IS NOT A SECOND TRIAL ASSERTION.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>DrugCentral pairs</small><b>{q.independent_drug_target_pair_count:,}</b></div><div><small>cross-source assertions</small><b>{q.cross_source_supported_assertion_count:,}</b></div><div><small>OT/ChEMBL-only assertions</small><b>{q.single_source_assertion_count:,}</b></div><div><small>cross-source NCT</small><b>{q.cross_source_supported_nct_count:,}</b></div><div><small>new trial mappings</small><b>{q.newly_mapped_nct_count}</b></div><div><small>name matches used</small><b>{q.name_matching_used_count}</b></div></section></header>
<main><section class="panel"><h2>Admission chain</h2><div class="flow"><div><b>DrugCentral 2027 row</b><br>At least one non-ChEMBL, attributable assertion source.</div><span class="arrow">→</span><div><b>Exact identities only</b><br>Full InChIKey → unique ChEMBL ID<br>Swiss-Prot → unique Ensembl ID</div><span class="arrow">→</span><div><b>Drug–target corroboration</b><br>Never creates trial linkage; ambiguous crosswalks are rejected.</div></div></section>
<section class="grid"><div class="panel"><h2>Assertion-level support</h2><div class="bar"><span style="width:{cross_rate:.2%}"></span><span></span></div><p><span class="cross">{q.cross_source_supported_assertion_count:,} cross-source ({cross_rate:.1%})</span><br><span class="single">{q.single_source_assertion_count:,} Open Targets/ChEMBL-only</span></p><p><a href="/api/p5/independent-assertions/corroborations/sample?status=cross_source_drug_target_supported&limit=5">Inspect cross-source sample</a></p></div><div class="panel"><h2>Pair-level support</h2><div class="bar"><span style="width:{pair_rate:.2%}"></span><span></span></div><p><span class="cross">{q.cross_source_supported_pair_count:,} / {q.current_source_pair_count:,} pairs ({pair_rate:.1%})</span></p><p>Cross-source evidence supports the drug–target edge only. Every record keeps <code>trial_specific_source_assertion_count=1</code>.</p></div></section>
<section class="grid"><div class="panel"><h2>Trial-level composition</h2><p><b>{q.all_assertions_cross_source_nct_count:,}</b> NCT have all current assertions corroborated.</p><p><b>{q.mixed_support_nct_count:,}</b> contain both corroborated and single-source assertions.</p><p><b>{q.single_source_only_nct_count:,}</b> remain entirely Open Targets/ChEMBL-only.</p></div><div class="panel"><h2>Hard stop on coverage expansion</h2><p>P5.5 candidate promotions: <b>{q.p5_5_candidate_promoted_to_trial_target_count}</b>.</p><p>Newly mapped NCT: <b>{q.newly_mapped_nct_count}</b>. Remaining unresolved: <b>{q.remaining_unresolved_nct_count:,}</b>.</p><p>The independent source is used to stratify confidence in an existing edge, never to manufacture a missing trial edge.</p></div></section>
<section class="panel"><h2>Known limitations</h2><ul>{limitations}</ul></section></main></body></html>"""
