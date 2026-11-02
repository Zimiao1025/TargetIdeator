"""P4.1 conservative structured-revision demo."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.revision.store import RevisionStore, load_default_revision_store


@lru_cache(maxsize=1)
def revision_store() -> RevisionStore:
    return load_default_revision_store()


def revision_payload() -> dict:
    store = revision_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
    }


def _render_value(value: str | list[str]) -> str:
    if isinstance(value, list):
        return "<br>".join(html.escape(item) for item in value) or "<em>empty</em>"
    return html.escape(value)


def revision_page() -> str:
    snapshot = revision_store().snapshot
    cards: list[str] = []
    for candidate in snapshot.candidates:
        hypothesis = candidate.source_hypothesis
        rows = "".join(
            f"""<tr><td><code>{html.escape(patch.field_path.value)}</code><small>{patch.source_critic_type.value} · {patch.source_verdict.value}</small></td>
            <td>{_render_value(patch.before_value)}</td><td>{_render_value(patch.after_value)}</td>
            <td><b>{patch.operation.value}</b><small>{html.escape(patch.requirement)}</small></td></tr>"""
            for patch in candidate.patches
        )
        assumptions = "".join(
            f"<li>{html.escape(item)}</li>"
            for item in candidate.constraints.unresolved_assumptions
        )
        eligible = "eligible" if candidate.eligible_for_p5_development else "blocked"
        cards.append(
            f"""<article class="card {eligible}"><header class="row"><div><p class="eyebrow">{html.escape(hypothesis.target.label)}</p>
            <h2>{hypothesis.proposed_direction.value} · {hypothesis.proposed_modality.value}</h2>
            <p class="mono">{html.escape(hypothesis.id)}</p></div><div class="badges"><span>{candidate.source_combined_verdict.value}</span><strong>{candidate.revision_status.value}</strong></div></header>
            <section class="summary"><div><small>Core fingerprint changed</small><b>{str(candidate.source_core_sha256 != candidate.revised_core_sha256).lower()}</b></div>
            <div><small>Structured patches</small><b>{len(candidate.patches)}</b></div><div><small>P5 development route</small><b>{str(candidate.eligible_for_p5_development).lower()}</b></div></section>
            <details open><summary>Before / after structured diff</summary><div class="scroll"><table><thead><tr><th>Field</th><th>Before</th><th>After</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></div></details>
            <details><summary>Unresolved fatal assumptions</summary><ul>{assumptions}</ul></details>
            <p><a href="/api/p4/revisions/hypotheses/{html.escape(hypothesis.id)}">Inspect revision JSON →</a></p></article>"""
        )
    quality = snapshot.quality
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator P4.1</title><style>:root{{--ink:#17202a;--paper:#f1f0ec;--panel:#fff;--accent:#0c6d69;--warn:#8a3f16;--line:#d9d3c8}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}body>header,main{{max-width:1400px;margin:auto;padding:24px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:8px 0}}h2{{margin:0}}.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px}}
.metrics,.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}.metrics div,.summary div,.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b,.summary b{{display:block;font-size:23px}}.card{{margin-bottom:22px;border-left:5px solid #b88335}}.card.eligible{{border-left-color:var(--accent)}}
.row{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.eyebrow{{color:var(--accent);font-weight:800;letter-spacing:.08em;margin:0}}.badges{{display:grid;gap:6px;text-align:right}}.badges span,.badges strong{{border-radius:14px;background:#eee8dc;padding:4px 9px;font-size:12px}}.eligible .badges strong{{background:#dff1ea;color:#07564f}}
.mono,code,small{{color:#626c76}}.mono,code{{font:12px ui-monospace,monospace}}small{{display:block}}details{{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}}summary{{cursor:pointer;font-weight:800}}.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;margin-top:10px}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px;min-width:170px}}th{{background:#f5f3ee}}a{{color:var(--accent);font-weight:750}}@media(max-width:700px){{.row{{display:block}}.badges{{text-align:left}}}}</style></head>
<body><header><p><a href="/falsification">P4 falsification</a> · <a href="/ideation">P3 portfolio</a> · <a href="/api/p4/revisions/quality">Quality API</a></p><p>TARGETIDEATOR · P4.1 DEVELOPMENT SLICE</p>
<h1>Conservative structured revisions</h1><p class="warning"><b>CONSTRAINTS ARE NOT SCIENTIFIC CORRECTIONS.</b><br>{html.escape(snapshot.warning)}</p>
<section class="metrics"><div><small>Candidates</small><b>{quality.candidate_count}</b></div><div><small>Patches</small><b>{quality.patch_count}</b></div><div><small>Core mutations</small><b>{quality.core_scientific_mutation_count}</b></div><div><small>P5 development eligible</small><b>{quality.p5_development_eligible_count}</b></div><div><small>Engineering gate</small><b>{str(quality.engineering_gate_passed).lower()}</b></div></section></header>
<main>{''.join(cards)}</main></body></html>"""
