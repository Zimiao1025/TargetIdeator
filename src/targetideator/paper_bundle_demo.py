"""P6.6 reproducible paper artifact readiness dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.evaluation.paper_bundle_store import (
    PaperBundleStore,
    load_default_paper_bundle_store,
)


@lru_cache(maxsize=1)
def paper_bundle_store() -> PaperBundleStore:
    return load_default_paper_bundle_store()


def paper_bundle_payload() -> dict:
    store = paper_bundle_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "gates": store.gates(),
        "paper_files": store.paper_files(),
    }


def paper_bundle_page() -> str:
    store = paper_bundle_store()
    q = store.snapshot.quality
    gate_rows = "".join(
        f"<tr><td><code>{html.escape(row['gate_id'])}</code></td>"
        f"<td>{html.escape(row['gate_scope'])}</td>"
        f"<td class='{html.escape(row['status'])}'>{html.escape(row['status'])}</td>"
        f"<td>{html.escape(row['evidence'])}"
        f"{'<br><b>Blocker:</b> ' + html.escape(row['blocking_reason']) if row['blocking_reason'] else ''}</td></tr>"
        for row in store.gates()
    )
    file_rows = "".join(
        f"<tr><td><a href='/api/p6/paper-bundle/file?path={html.escape(row['relative_path'])}'>{html.escape(row['relative_path'])}</a></td>"
        f"<td>{html.escape(row['role'])}</td><td>{row['byte_count']}</td>"
        f"<td><code>{html.escape(row['sha256'][:16])}…</code></td></tr>"
        for row in store.paper_files()
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator P6.6 paper bundle</title>
<style>:root{{--ink:#172126;--paper:#ecefe9;--panel:#fff;--accent:#235c67;--warn:#933a27;--ok:#17684d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1360px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.position{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px}}code{{font-size:11px}}.passed{{color:var(--ok);font-weight:800}}.blocked{{color:var(--warn);font-weight:800}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/evaluation/claim-synthesis">P6.5 claim synthesis</a> · <a href="/api/p6/paper-bundle">JSON bundle</a> · <a href="/api/p6/paper-bundle/file?path=paper/README.md">bundle README</a></p><p>TARGETIDEATOR · P6.6 REPRODUCIBLE PAPER ARTIFACT</p><h1>Artifact ready; scientific claims blocked</h1><p class="warning"><b>SEPARATE READINESS GATES.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Source manifests</small><b>{q.source_manifest_count}</b></div><div><small>Paper files</small><b>{q.paper_file_count}</b></div><div><small>Artifact gates passed</small><b class="passed">{q.passed_artifact_gate_count}/3</b></div><div><small>Scientific gates blocked</small><b class="blocked">{q.blocked_scientific_gate_count}/3</b></div><div><small>Supported claims</small><b class="blocked">{q.scientifically_supported_claim_count}</b></div></section></header>
<main><p class="position"><b>Allowed positioning:</b> reproducible methods/artifact and negative-results package. <b>Not allowed:</b> validated target discovery, calibrated clinical prediction, or demonstrated decision utility.</p>
<section class="panel"><h2>Readiness matrix</h2><table><thead><tr><th>Gate</th><th>Scope</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{gate_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Checksum-bound paper files</h2><table><thead><tr><th>File</th><th>Role</th><th>Bytes</th><th>SHA-256</th></tr></thead><tbody>{file_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Interpretation boundary</h2><ul>{limitations}</ul><p>Artifact release ready: <b class="passed">{str(q.artifact_release_ready).lower()}</b> · scientific submission ready: <b class="blocked">{str(q.scientific_submission_ready).lower()}</b> · negative result preserved: <b>{str(q.negative_result_preserved).lower()}</b>.</p></section></main></body></html>"""
