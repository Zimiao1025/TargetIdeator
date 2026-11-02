"""R1 artifact release-candidate audit dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.store import ReleaseAuditStore, load_default_release_audit_store


@lru_cache(maxsize=1)
def release_audit_store() -> ReleaseAuditStore:
    return load_default_release_audit_store()


def release_audit_payload() -> dict:
    store = release_audit_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "gates": store.gates(),
        "largest_payload_files": store.largest_payload_files(),
    }


def release_audit_page() -> str:
    store = release_audit_store()
    q = store.snapshot.quality
    gates = "".join(
        f"<tr><td><code>{html.escape(row['gate_id'])}</code></td>"
        f"<td class='{html.escape(row['status'])}'>{html.escape(row['status'])}</td>"
        f"<td>{html.escape(row['owner'])}</td><td>{html.escape(row['evidence'])}"
        f"{'<br><b>Remediation:</b> ' + html.escape(row['remediation']) if row['remediation'] else ''}</td></tr>"
        for row in store.gates()
    )
    payload = "".join(
        f"<tr><td><code>{html.escape(row['relative_path'])}</code></td>"
        f"<td>{row['byte_count'] / 1024 / 1024:.2f} MiB</td>"
        f"<td>{html.escape(row['payload_class'])}</td>"
        f"<td>{str(row['redistribution_review_required']).lower()}</td></tr>"
        for row in store.largest_payload_files(12)
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R1 release audit</title>
<style>:root{{--ink:#172126;--paper:#ecefe9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1380px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px}}code{{font-size:11px}}.passed{{color:var(--ok);font-weight:800}}.blocked{{color:var(--warn);font-weight:800}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/evaluation/paper-bundle">P6.6 paper bundle</a> · <a href="/api/release/audit">JSON audit</a></p><p>TARGETIDEATOR · R1 RELEASE-CANDIDATE AUDIT</p><h1>Automation complete; release blocked</h1><p class="warning"><b>NO UPLOAD AUTHORIZED.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>Release gates</small><b>{q.release_gate_count}</b></div><div><small>Passed</small><b class="passed">{q.passed_gate_count}</b></div><div><small>Blocked</small><b class="blocked">{q.blocked_gate_count}</b></div><div><small>Payload</small><b>{q.package_payload_byte_count / 1024 / 1024:.1f} MiB</b></div><div><small>Budget</small><b>{q.package_payload_budget_bytes / 1024 / 1024:.0f} MiB</b></div></section></header>
<main><p class="boundary"><b>Owner decisions required:</b> choose a license, approve citation metadata, complete the source redistribution ledger, establish an isolated repository, and split the bulk data payload.</p>
<section class="panel"><h2>Release gates</h2><table><thead><tr><th>Gate</th><th>Status</th><th>Owner</th><th>Evidence and remediation</th></tr></thead><tbody>{gates}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Largest packaged payload files</h2><table><thead><tr><th>Path</th><th>Size</th><th>Class</th><th>Redistribution review</th></tr></thead><tbody>{payload}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Release boundary</h2><ul>{limitations}</ul><p>Safe automated hardening complete: <b>{str(q.safe_automated_hardening_complete).lower()}</b> · release candidate ready: <b class="blocked">{str(q.release_candidate_ready).lower()}</b> · upload authorized: <b class="blocked">{str(q.publication_or_upload_authorized).lower()}</b>.</p></section></main></body></html>"""
