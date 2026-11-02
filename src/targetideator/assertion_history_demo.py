"""P5.6 release-aware source-assertion history dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.outcomes.assertion_history_store import (
    AssertionHistoryStore,
    load_default_assertion_history_store,
)


@lru_cache(maxsize=1)
def assertion_history_store() -> AssertionHistoryStore:
    return load_default_assertion_history_store()


def assertion_history_payload() -> dict:
    store = assertion_history_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "removed_evidence": store.sample_evidence(5, "removed_after_25_03"),
        "removed_assertions": store.sample_assertions(5, "removed_after_25_03"),
    }


def assertion_history_page() -> str:
    store = assertion_history_store()
    q = store.snapshot.quality
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P5.6 assertion history</title>
<style>:root{{--ink:#172328;--paper:#eef0eb;--panel:#fff;--accent:#075f66;--warn:#95402d;--line:#ccd5cc;--muted:#637177}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:40px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:23px}}.timeline{{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center}}.release{{background:#f8fbf7;border:1px solid var(--line);border-radius:10px;padding:18px}}.arrow{{font-size:30px;color:var(--accent)}}.delta{{color:var(--warn);font-weight:750}}.zero{{font-size:44px;color:var(--warn);font-family:Georgia,serif}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left}}code{{font:12px ui-monospace,monospace}}small{{color:var(--muted)}}@media(max-width:800px){{.grid,.timeline{{grid-template-columns:1fr}}.arrow{{transform:rotate(90deg);text-align:center}}}}</style></head>
<body><header><p><a href="/identity/resolution">P5.5 drug identity</a> · <a href="/identity/corroboration">P5.7 independent corroboration →</a> · <a href="/api/p5/assertion-history/quality">Quality API</a></p><p>TARGETIDEATOR · P5.6 VERSIONED SOURCE ASSERTIONS</p><h1>Version the assertion; do not invent the link</h1><p class="warning"><b>SOURCE MEMBERSHIP IS NOT TARGET CAUSALITY.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>union evidence rows</small><b>{q.union_evidence_row_count:,}</b></div><div><small>union assertions</small><b>{q.union_assertion_count:,}</b></div><div><small>persistent assertions</small><b>{q.persistent_assertion_count:,}</b></div><div><small>removed assertions</small><b>{q.removed_assertion_count}</b></div><div><small>newly recovered NCT</small><b>{q.newly_recovered_nct_count}</b></div><div><small>name-inferred assertions</small><b>{q.name_inferred_assertion_count}</b></div></section></header>
<main><section class="panel"><h2>Release membership</h2><div class="timeline"><div class="release"><b>25.03 · 2025-03-19</b><p>{q.release_evidence_row_counts['25.03']:,} evidence rows<br>{q.release_assertion_counts['25.03']:,} trial–drug–target assertions<br>{q.release_mapped_nct_counts['25.03']:,} mapped NCT</p></div><div class="arrow">→</div><div class="release"><b>25.09 · 2025-09-17</b><p>{q.release_evidence_row_counts['25.09']:,} evidence rows <span class="delta">(−{q.removed_evidence_row_count})</span><br>{q.release_assertion_counts['25.09']:,} assertions <span class="delta">(−{q.removed_assertion_count})</span><br>{q.release_mapped_nct_counts['25.09']:,} mapped NCT <b>(±0)</b></p></div></div></section>
<section class="grid"><div class="panel"><h2>P5.5 recovery audit</h2><div class="zero">0 / {q.p5_5_exact_identity_candidate_nct_count:,}</div><p>identity-resolved unresolved NCT gained a target assertion from the older release.</p><p>This zero is the valid result. Exact drug names remain triage information and were not converted into target mappings.</p></div><div class="panel"><h2>Removed is not refuted</h2><p><b>{q.removed_evidence_row_count}</b> evidence rows representing <b>{q.removed_assertion_count}</b> triples occur in 25.03 but not 25.09.</p><p><a href="/api/p5/assertion-history/assertions/sample?lifecycle=removed_after_25_03&limit=5">Inspect removed assertions</a></p><p>Release removal records provenance drift; it does not prove that a drug–target mechanism is false.</p></div></section>
<section class="panel"><h2>Assertion admission contract</h2><table><thead><tr><th>identity</th><th>required source field</th><th>allowed inference</th></tr></thead><tbody><tr><td>trial</td><td><code>$.studyId</code></td><td>none</td></tr><tr><td>drug</td><td><code>$.drugId</code></td><td>none</td></tr><tr><td>target</td><td><code>$.targetId</code></td><td>none</td></tr><tr><td>evidence</td><td><code>$.id</code></td><td>none</td></tr></tbody></table><p>Field-provenance coverage: <b>{q.source_field_provenance_coverage:.0%}</b>. Fuzzy assertions: <b>{q.fuzzy_assertion_count}</b>. Temporal feature uses: <b>{q.source_assertion_used_as_temporal_model_feature_count}</b>.</p></section>
<section class="panel"><h2>Known limitations</h2><ul>{limitations}</ul></section></main></body></html>"""
