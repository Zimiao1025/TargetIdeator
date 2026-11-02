"""R2.7 canonical acceptance and R2.8 package-convergence dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.data import MissingDataArtifactError, fixture_path
from targetideator.release.canonical_store import CanonicalAcceptanceStore
from targetideator.release.convergence_store import PackageConvergenceStore


def _canonical_root():
    return fixture_path("r2_7_canonical/r2_7_canonical_acceptance_snapshot.json").parent


def _convergence_root():
    return fixture_path("r2_8_convergence/r2_8_package_convergence_snapshot.json").parent


@lru_cache(maxsize=1)
def canonical_acceptance_store() -> CanonicalAcceptanceStore:
    root = _canonical_root()
    return CanonicalAcceptanceStore.load(
        root / "r2_7_canonical_acceptance_snapshot.json",
        root / "r2_7_canonical_acceptance_manifest.json",
    )


@lru_cache(maxsize=1)
def package_convergence_store() -> PackageConvergenceStore:
    root = _convergence_root()
    return PackageConvergenceStore.load(
        root / "r2_8_package_convergence_snapshot.json",
        root / "r2_8_package_convergence_manifest.json",
    )


def package_convergence_snapshot_id_or_status() -> str:
    """Keep installed-wheel health usable when external self-attestation is absent."""

    try:
        return package_convergence_store().snapshot.id
    except MissingDataArtifactError:
        return "external-self-attestation-not-configured"


def package_convergence_payload() -> dict:
    canonical = canonical_acceptance_store()
    convergence = package_convergence_store()
    return {
        "canonical_snapshot": canonical.snapshot.model_dump(mode="json"),
        "canonical_quality": canonical.quality_report(),
        "canonical_acceptance": [
            row.model_dump(mode="json") for row in canonical.acceptance()
        ],
        "convergence_snapshot": convergence.snapshot.model_dump(mode="json"),
        "convergence_quality": convergence.quality_report(),
        "file_audit": [row.model_dump(mode="json") for row in convergence.file_audit()],
        "runtime_smoke": [
            row.model_dump(mode="json") for row in convergence.runtime_smoke()
        ],
    }


def package_convergence_page() -> str:
    canonical = canonical_acceptance_store()
    convergence = package_convergence_store()
    cq = canonical.snapshot.quality
    pq = convergence.snapshot.quality
    smoke_rows = "".join(
        f"<tr><td>{html.escape(row.check_name)}</td>"
        f"<td class='{html.escape(row.status)}'>{html.escape(row.status)}</td>"
        f"<td>{row.exit_code}</td><td>{row.duration_seconds:.2f}s</td>"
        f"<td><code>{html.escape(' '.join(row.command[:5]))}</code></td></tr>"
        for row in convergence.runtime_smoke()
    )
    rule_rows = "".join(
        f"<tr><td><code>{html.escape(rule.id)}</code></td>"
        f"<td>{html.escape(rule.selector)}</td><td>{html.escape(rule.semantic_guard)}</td></tr>"
        for rule in canonical.snapshot.rules
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in pq.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2.8 package convergence</title>
<style>:root{{--ink:#172126;--paper:#eef0ea;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1400px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:8px}}code{{font-size:11px}}.passed,.ok{{color:var(--ok);font-weight:750}}.blocked{{color:var(--warn);font-weight:750}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release/replay-hardening">R2.6 replay diagnosis</a> · <a href="/api/release/package-convergence">JSON audit</a></p><p>TARGETIDEATOR · R2.7–R2.8</p><h1>Canonical gate and package convergence passed</h1><p class="warning"><b>ENGINEERING CONVERGENCE — PUBLICATION STILL CLOSED.</b><br>{html.escape(convergence.snapshot.warning)}</p>
<section class="metrics"><div><small>Byte identity</small><b>{cq.byte_identity_acceptance_count}</b></div><div><small>Canonical v1</small><b>{cq.canonical_content_acceptance_count}</b></div><div><small>Rejected</small><b>{cq.rejected_count}</b></div><div><small>Explicit exclusions</small><b>{pq.combined_exclusion_count}</b></div><div><small>Runtime smoke</small><b>{pq.runtime_smoke_passed_count}/{pq.runtime_smoke_check_count}</b></div><div><small>External resolution</small><b>{pq.external_resolution_smoke_count}/137</b></div></section></header>
<main><section class="panel"><h2>Canonical-content v1 rules</h2><p>Frozen changed-path fingerprint: <code>{cq.approved_changed_path_map_sha256}</code>. Any new field path requires a new contract version.</p><table><thead><tr><th>Rule</th><th>Selector</th><th>Guard</th></tr></thead><tbody>{rule_rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Installed-wheel smoke</h2><table><thead><tr><th>Check</th><th>Status</th><th>Exit</th><th>Duration</th><th>Command</th></tr></thead><tbody>{smoke_rows}</tbody></table><p>Runtime gate: <b class="ok">{str(pq.projected_runtime_smoke_gate_passed).lower()}</b> · package convergence: <b class="ok">{str(pq.package_convergence_gate_passed).lower()}</b>.</p></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Public release: <b class="blocked">false</b> · data publication: <b class="blocked">false</b> · C1/C4: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
