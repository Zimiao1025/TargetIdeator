"""R2.3 owner/data-steward fixture-disposition dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.disposition_store import (
    FixtureDispositionStore,
    load_default_fixture_disposition_store,
)


@lru_cache(maxsize=1)
def fixture_disposition_store() -> FixtureDispositionStore:
    return load_default_fixture_disposition_store()


def fixture_disposition_payload() -> dict:
    store = fixture_disposition_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "ledger": [row.model_dump(mode="json") for row in store.ledger()],
    }


def fixture_disposition_page() -> str:
    store = fixture_disposition_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td><code>{html.escape(row.relative_path)}</code></td>"
        f"<td>{html.escape(row.artifact_class)}</td>"
        f"<td><b>{html.escape(row.decision)}</b></td>"
        f"<td>{html.escape(row.decision_authority)}</td>"
        f"<td>{html.escape(row.execution_status)}</td></tr>"
        for row in store.ledger()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.3 dispositions</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1450px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px}}code{{font-size:11px}}.ok{{color:var(--ok)}}.blocked{{color:var(--warn)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/retained-fixtures">R2.2 inventory</a> · <a href="/api/release/fixture-dispositions">JSON ledger</a></p><p>TARGETIDEATOR · R2.3 OWNER/DATA-STEWARD DISPOSITIONS</p><h1>Decisions complete; execution remains blocked</h1><p class="warning"><b>DECISIONS RECORDED, NOT EXECUTED.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Decisions</small><b>{q.decision_record_count}/129</b></div><div><small>Retain</small><b>{q.retain_count}</b></div><div><small>Externalize</small><b>{q.externalize_count}</b></div><div><small>Regenerate</small><b>{q.regenerate_count}</b></div><div><small>Applied</small><b>{q.execution_applied_count}</b></div></section></header>
<main><p class="boundary">Decision coverage: <b class="ok">100%</b>. Unresolved packaging dispositions: <b>0</b>. Redistribution authorizations: <b>0</b>. Externalize/regenerate recipes must pass a separate replay gate before payload changes.</p>
<section class="panel"><h2>Frozen decision ledger</h2><table><thead><tr><th>Path</th><th>Class</th><th>Decision</th><th>Authority</th><th>Execution status</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Decision-ledger engineering gate: <b class="ok">true</b> · package convergence gate: <b class="blocked">false</b> · public release authorized: <b class="blocked">false</b> · C1/C4 unblocked: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
