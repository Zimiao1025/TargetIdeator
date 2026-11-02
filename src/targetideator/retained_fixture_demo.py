"""R2.2 retained-fixture governance dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.retained_fixture_store import (
    RetainedFixtureStore,
    load_default_retained_fixture_store,
)


@lru_cache(maxsize=1)
def retained_fixture_store() -> RetainedFixtureStore:
    return load_default_retained_fixture_store()


def retained_fixture_payload() -> dict:
    store = retained_fixture_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "inventory": [row.model_dump(mode="json") for row in store.inventory()],
    }


def retained_fixture_page() -> str:
    store = retained_fixture_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td><code>{html.escape(row.relative_path)}</code></td>"
        f"<td>{html.escape(row.artifact_class)}</td>"
        f"<td>{html.escape(row.recommended_action)}</td>"
        f"<td>{html.escape(row.owner_role)}</td><td>unresolved</td></tr>"
        for row in store.inventory()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.2 retained fixtures</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1450px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px}}code{{font-size:11px}}.ok{{color:var(--ok)}}.blocked{{color:var(--warn)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/hydration">R2.1 hydration</a> · <a href="/api/release/retained-fixtures">JSON inventory</a></p><p>TARGETIDEATOR · R2.2 RETAINED-FIXTURE GOVERNANCE</p><h1>Payload classified; distribution remains blocked</h1><p class="warning"><b>NO LEGAL CONCLUSION OR PACKAGE MUTATION.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Retained files</small><b>{q.retained_file_count}</b></div><div><small>Source captures</small><b>{q.source_capture_count}</b></div><div><small>Curated fixtures</small><b>{q.curated_fixture_count}</b></div><div><small>Derived artifacts</small><b>{q.derived_artifact_count}</b></div><div><small>Unresolved decisions</small><b>{q.unresolved_redistribution_count}</b></div></section></header>
<main><p class="boundary">Inventory coverage: <b class="ok">100%</b>. Legal conclusions: <b>0</b>. Packaging changes applied: <b>0</b>. Recommended actions are owner queues, not executable instructions.</p>
<section class="panel"><h2>Owner decision queue</h2><table><thead><tr><th>Path</th><th>Class</th><th>Recommended action</th><th>Owner</th><th>Decision</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Governance inventory engineering gate: <b class="ok">true</b> · full code-only distribution ready: <b class="blocked">false</b> · public release authorized: <b class="blocked">false</b> · C1/C4 unblocked: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
