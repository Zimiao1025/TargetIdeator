"""R2.4 execution-plan and package-mutation preview dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.execution_plan_store import (
    ExecutionPlanStore,
    load_default_execution_plan_store,
)


@lru_cache(maxsize=1)
def execution_plan_store() -> ExecutionPlanStore:
    return load_default_execution_plan_store()


def execution_plan_payload() -> dict:
    store = execution_plan_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "recipe": [row.model_dump(mode="json") for row in store.recipe()],
        "preview": [row.model_dump(mode="json") for row in store.preview()],
    }


def execution_plan_page() -> str:
    store = execution_plan_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td>{row.command_stage}</td><td><code>{html.escape(row.relative_path)}</code></td>"
        f"<td>{html.escape(row.disposition)}</td><td>{'yes' if row.network_required else 'no'}</td>"
        f"<td><code>{html.escape(row.operator_command)}</code></td></tr>"
        for row in sorted(store.recipe(), key=lambda item: (item.command_stage, item.relative_path))
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.4 execution preview</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1500px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px}}code{{font-size:11px}}.ok{{color:var(--ok)}}.blocked{{color:var(--warn)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/fixture-dispositions">R2.3 decisions</a> · <a href="/api/release/execution-plan">JSON plan</a></p><p>TARGETIDEATOR · R2.4 EXECUTION PLAN + MUTATION PREVIEW</p><h1>Commands bound; package unchanged</h1><p class="warning"><b>PREVIEW ONLY — NO DELETE OR CONFIG WRITE.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Recipes</small><b>{q.execution_recipe_count}/113</b></div><div><small>Externalize</small><b>{q.externalize_recipe_count}</b></div><div><small>Regenerate</small><b>{q.regenerate_recipe_count}</b></div><div><small>Projected retain</small><b>{q.projected_retain_count}</b></div><div><small>Projected exclusions</small><b>{q.projected_exclude_count}</b></div><div><small>Checksum replays</small><b>{q.checksum_replay_count}</b></div></section></header>
<main><p class="boundary">Planning calls: network <b>0</b>, commands <b>0</b>, config writes <b>0</b>, source deletions <b>0</b>. The 113 exclusions exist only as preview records; `pyproject.toml` is unchanged.</p>
<section class="panel"><h2>Staged operator recipe</h2><table><thead><tr><th>Stage</th><th>Path</th><th>Disposition</th><th>Network</th><th>Command template</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Plan/preview engineering gates: <b class="ok">true/true</b> · checksum replay: <b class="blocked">false</b> · runtime smoke: <b class="blocked">false</b> · package convergence: <b class="blocked">false</b>.</p></section></main></body></html>"""
