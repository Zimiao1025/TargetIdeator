"""R2.1 external-payload hydration dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.data import external_data_root
from targetideator.release.hydration_store import HydrationStore, load_default_hydration_store


@lru_cache(maxsize=1)
def hydration_store() -> HydrationStore:
    return load_default_hydration_store()


def hydration_status() -> dict:
    root = external_data_root()
    if root is None:
        return {
            "configured": False,
            "data_root": None,
            "artifact_count": 24,
            "ready_count": 0,
            "missing_count": 24,
            "checksum_mismatch_count": 0,
            "source_input_ready_count": 0,
            "derived_output_ready_count": 0,
            "hydration_complete": False,
            "redistribution_performed": False,
            "rows": [],
        }
    return {"configured": True, **hydration_store().root_report(root)}


def hydration_payload() -> dict:
    store = hydration_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "status": hydration_status(),
        "recipe": [row.model_dump(mode="json") for row in store.recipe()],
    }


def hydration_page() -> str:
    store = hydration_store()
    q = store.snapshot.quality
    status = hydration_status()
    rows = "".join(
        f"<tr><td>{row.command_stage}</td><td><code>{html.escape(row.filename)}</code></td>"
        f"<td>{html.escape(row.artifact_role)}</td>"
        f"<td>{'yes' if row.network_required else 'no'}</td>"
        f"<td><code>{html.escape(row.operator_command)}</code></td></tr>"
        for row in sorted(store.recipe(), key=lambda item: (item.command_stage, item.filename))
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    configured = (
        html.escape(status["data_root"])
        if status["configured"]
        else "TARGETIDEATOR_DATA_ROOT is not configured"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.1 hydration</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1450px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px}}code{{font-size:11px}}.ok{{color:var(--ok)}}.blocked{{color:var(--warn)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/data-bundle">R2 bundle</a> · <a href="/api/release/hydration">JSON contract</a></p><p>TARGETIDEATOR · R2.1 OPERATOR HYDRATION CONTRACT</p><h1>Plan frozen; no data transfer performed</h1><p class="warning"><b>NO AUTOMATIC DOWNLOAD OR REDISTRIBUTION.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>External artifacts</small><b>24</b></div><div><small>User-acquired inputs</small><b>10</b></div><div><small>Derived outputs</small><b>14</b></div><div><small>Ready in configured root</small><b>{status['ready_count']}/24</b></div><div><small>Checksum mismatches</small><b>{status['checksum_mismatch_count']}</b></div></section></header>
<main><p class="boundary"><b>Configured root:</b> {configured}. Planning calls made: network <b>0</b>, file copies <b>0</b>. Commands below are operator-reviewed recipes, not an executable auto-fetch script.</p>
<section class="panel"><h2>Hydration recipe</h2><table><thead><tr><th>Stage</th><th>Artifact</th><th>Role</th><th>Network</th><th>Operator command template</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Hydration contract engineering gate: <b class="ok">true</b> · full code-only distribution ready: <b class="blocked">false</b> · redistribution performed: <b class="blocked">false</b> · C1/C4 unblocked: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
