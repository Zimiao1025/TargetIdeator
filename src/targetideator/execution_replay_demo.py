"""R2.5 isolated command replay dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.replay_store import (
    ExecutionReplayStore,
    default_execution_replay_manifest_path,
    default_execution_replay_snapshot_path,
)


@lru_cache(maxsize=1)
def execution_replay_store() -> ExecutionReplayStore:
    return ExecutionReplayStore.load(
        default_execution_replay_snapshot_path(),
        default_execution_replay_manifest_path(),
    )


def execution_replay_payload() -> dict:
    store = execution_replay_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "groups": [row.model_dump(mode="json") for row in store.groups()],
        "artifacts": [row.model_dump(mode="json") for row in store.artifacts()],
    }


def execution_replay_page() -> str:
    store = execution_replay_store()
    q = store.snapshot.quality
    group_rows = "".join(
        f"<tr><td>{index}</td><td>{row.command_stage}</td>"
        f"<td class='{html.escape(row.status)}'>{html.escape(row.status)}</td>"
        f"<td>{row.exit_code}</td><td>{row.exact_match_count}</td>"
        f"<td>{row.checksum_mismatch_count}</td><td>{row.missing_count}</td>"
        f"<td>{row.duration_seconds:.1f}s</td>"
        f"<td><code>{html.escape(row.command_template)}</code></td></tr>"
        for index, row in enumerate(store.groups(), start=1)
    )
    non_exact = [row for row in store.artifacts() if row.status != "exact_match"]
    artifact_rows = "".join(
        f"<tr><td><code>{html.escape(row.relative_path)}</code></td>"
        f"<td>{html.escape(row.disposition)}</td>"
        f"<td class='{html.escape(row.status)}'>{html.escape(row.status)}</td>"
        f"<td><code>{html.escape(row.expected_sha256[:12])}</code></td>"
        f"<td><code>{html.escape((row.observed_sha256 or '—')[:12])}</code></td></tr>"
        for row in non_exact
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.5 execution replay</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1500px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}}code{{font-size:11px}}.completed,.exact_match{{color:var(--ok);font-weight:750}}.failed,.missing,.checksum_mismatch,.blocked{{color:var(--warn);font-weight:750}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/execution-plan">R2.4 plan</a> · <a href="/api/release/execution-replay">JSON replay</a></p><p>TARGETIDEATOR · R2.5 ISOLATED EXECUTION REPLAY</p><h1>Execution complete; checksum gate closed</h1><p class="warning"><b>OBSERVED REPLAY RESULT — NOT A CHECKSUM WAIVER.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Groups executed</small><b>{q.executed_command_group_count}/31</b></div><div><small>Successful</small><b>{q.successful_command_group_count}</b></div><div><small>Failed</small><b>{q.failed_command_group_count}</b></div><div><small>Exact</small><b>{q.exact_match_count}/113</b></div><div><small>Drift</small><b>{q.checksum_mismatch_count}</b></div><div><small>Missing</small><b>{q.missing_count}</b></div></section></header>
<main><p class="boundary">Bulk symlinks <b>{q.bulk_symlink_count}</b> · data copies <b>{q.data_file_copy_count}</b> · source deletions <b>{q.source_file_delete_count}</b> · config writes <b>{q.configuration_write_count}</b>. Replay complete: <b>{str(q.replay_execution_complete).lower()}</b>; checksum gate: <b class="blocked">{str(q.checksum_replay_gate_passed).lower()}</b>.</p>
<section class="panel"><h2>31 command groups</h2><table><thead><tr><th>#</th><th>Stage</th><th>Status</th><th>Exit</th><th>Exact</th><th>Drift</th><th>Missing</th><th>Time</th><th>Command</th></tr></thead><tbody>{group_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Non-exact artifacts ({len(non_exact)})</h2><table><thead><tr><th>Path</th><th>Disposition</th><th>Status</th><th>Expected</th><th>Observed</th></tr></thead><tbody>{artifact_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Runtime smoke: <b class="blocked">false</b> · package convergence: <b class="blocked">false</b> · public release: <b class="blocked">false</b> · C1/C4: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
