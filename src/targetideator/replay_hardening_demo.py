"""R2.6 bounded-retry and replay-drift diagnosis dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.data import fixture_path
from targetideator.release.replay_hardening_store import ReplayHardeningStore
from targetideator.release.replay_store import ExecutionReplayStore


def _root():
    return fixture_path("r2_6_replay/r2_6_replay_hardening_snapshot.json").parent


@lru_cache(maxsize=1)
def replay_hardening_store() -> ReplayHardeningStore:
    root = _root()
    return ReplayHardeningStore.load(
        root / "r2_6_replay_hardening_snapshot.json",
        root / "r2_6_replay_hardening_manifest.json",
    )


@lru_cache(maxsize=1)
def hardened_execution_store() -> ExecutionReplayStore:
    root = _root()
    return ExecutionReplayStore.load(
        root / "r2_5_execution_replay_snapshot.json",
        root / "r2_5_execution_replay_manifest.json",
    )


def replay_hardening_payload() -> dict:
    hardening = replay_hardening_store()
    execution = hardened_execution_store()
    return {
        "snapshot": hardening.snapshot.model_dump(mode="json"),
        "quality": hardening.quality_report(),
        "execution_quality": execution.quality_report(),
        "groups": [row.model_dump(mode="json") for row in execution.groups()],
        "diagnosis": [row.model_dump(mode="json") for row in hardening.diagnosis()],
    }


def replay_hardening_page() -> str:
    hardening = replay_hardening_store()
    execution = hardened_execution_store()
    q = hardening.snapshot.quality
    eq = execution.snapshot.quality
    group_rows = "".join(
        f"<tr><td>{index}</td><td>{row.command_stage}</td>"
        f"<td class='{html.escape(row.status)}'>{html.escape(row.status)}</td>"
        f"<td>{row.exit_code}</td><td>{row.exact_match_count}</td>"
        f"<td>{row.checksum_mismatch_count}</td><td>{row.missing_count}</td>"
        f"<td><code>{html.escape(row.command_template)}</code></td></tr>"
        for index, row in enumerate(execution.groups(), start=1)
    )
    non_exact = [
        row for row in hardening.diagnosis() if row.diagnosis != "exact_byte_match"
    ]
    diagnosis_rows = "".join(
        f"<tr><td><code>{html.escape(row.relative_path)}</code></td>"
        f"<td>{html.escape(row.byte_status)}</td>"
        f"<td class='{html.escape(row.diagnosis)}'>{html.escape(row.diagnosis)}</td>"
        f"<td><code>{html.escape(row.expected_sha256[:12])}</code></td>"
        f"<td><code>{html.escape((row.observed_sha256 or '—')[:12])}</code></td></tr>"
        for row in non_exact
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.6 replay hardening</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1500px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}}code{{font-size:11px}}.completed,.declared_metadata_only_drift{{color:var(--ok);font-weight:750}}.failed,.substantive_content_drift,.blocked{{color:var(--warn);font-weight:750}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/execution-replay">R2.5 baseline</a> · <a href="/api/release/replay-hardening">JSON audit</a></p><p>TARGETIDEATOR · R2.6 REPLAY HARDENING</p><h1>Missing resolved; byte gate still closed</h1><p class="warning"><b>NON-GATING DIAGNOSIS — NO CHECKSUM WAIVER.</b><br>{html.escape(hardening.snapshot.warning)}</p>
<section class="metrics"><div><small>Groups executed</small><b>{eq.executed_command_group_count}/31</b></div><div><small>Successful</small><b>{eq.successful_command_group_count}</b></div><div><small>Failed</small><b>{eq.failed_command_group_count}</b></div><div><small>Byte exact</small><b>{q.exact_byte_match_count}/113</b></div><div><small>Metadata-only</small><b>{q.declared_metadata_only_drift_count}</b></div><div><small>Substantive / missing</small><b>{q.substantive_content_drift_count} / 0</b></div></section></header>
<main><p class="boundary">All 113 expected artifacts are available. Metadata-normalized diagnostic: <b class="completed">{str(q.metadata_normalized_diagnostic_passed).lower()}</b>; byte checksum gate: <b class="blocked">{str(q.byte_checksum_gate_passed).lower()}</b>. The single failed capture command produced all six expected raw files; its later snapshot build rejected new retry fields, while the separately staged clinical and claim-graph rebuild groups succeeded after the contract fix.</p>
<section class="panel"><h2>31 command groups</h2><table><thead><tr><th>#</th><th>Stage</th><th>Status</th><th>Exit</th><th>Exact</th><th>Drift</th><th>Missing</th><th>Command</th></tr></thead><tbody>{group_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Non-byte-exact artifacts ({len(non_exact)})</h2><table><thead><tr><th>Path</th><th>Byte status</th><th>Diagnosis</th><th>Expected</th><th>Observed</th></tr></thead><tbody>{diagnosis_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Runtime smoke: <b class="blocked">false</b> · package convergence: <b class="blocked">false</b> · public release: <b class="blocked">false</b> · C1/C4: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
