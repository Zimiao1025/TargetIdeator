"""Deterministic JSON and human-readable Markdown dossier exports."""

from __future__ import annotations

import json
from pathlib import Path

from targetideator.contracts import ProjectBundle
from targetideator.contracts.models import MeasurementCriterion

WARNING = (
    "ILLUSTRATIVE / NOT SCIENTIFIC EVIDENCE — this frozen P0.2 fixture validates the product "
    "workflow and must not be used for research or clinical decisions."
)


def bundle_json(bundle: ProjectBundle) -> str:
    return json.dumps(
        bundle.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"


def _claim_lines(bundle: ProjectBundle, claim_ids: list[str]) -> list[str]:
    by_id = {claim.id: claim for claim in bundle.claims}
    lines: list[str] = []
    for claim_id in claim_ids:
        claim = by_id[claim_id]
        target = claim.object.entity.label if claim.object.entity else claim.object.text
        lines.append(
            f"- `{claim.id}` — {claim.subject.label} {claim.predicate} {target} "
            f"_(polarity: {claim.polarity.value}; evidence: {', '.join(f'`{item}`' for item in claim.evidence_ids)}; "
            f"role: {claim.context.mechanistic_role.value}; uncertainty: {claim.uncertainty})_"
        )
    return lines or ["- None recorded"]


def _criterion_lines(criteria: list[MeasurementCriterion]) -> list[str]:
    lines: list[str] = []
    for criterion in criteria:
        if criterion.threshold is None:
            threshold = criterion.threshold_status.value.upper()
        else:
            threshold = criterion.threshold.description
        lines.append(
            f"- **{criterion.role.value}: {criterion.endpoint}** — method: {criterion.method}; "
            f"matrix: {criterion.matrix}; timepoint: {criterion.timepoint}; threshold: `{threshold}`  \n"
            f"  Decision role: {criterion.decision_role.value}; required for current gate: "
            f"{str(criterion.required_for_current_gate).lower()}  \n"
            f"  Derivation: {criterion.threshold_derivation}  \n"
            f"  Fail: {criterion.failure_condition}  \n"
            f"  Inconclusive: {criterion.inconclusive_condition}"
        )
    return lines


def bundle_markdown(bundle: ProjectBundle) -> str:
    brief = bundle.disease_brief
    decisions = {item.hypothesis_id: item for item in bundle.decisions}
    actions: dict[str, list] = {}
    for action in bundle.experiment_actions:
        actions.setdefault(action.hypothesis_id, []).append(action)

    lines = [
        "# TargetIdeator P0.2 frozen hypothesis dossier",
        "",
        f"> **{WARNING}**",
        "",
        f"- Snapshot: `{bundle.snapshot_id}`",
        f"- Evidence cutoff: `{brief.as_of_date.isoformat()}`",
        f"- Schema: `{bundle.schema_version}`",
        f"- Contract status: `{bundle.scope_policy.status}`",
        f"- Decision scope / gate: `{bundle.scope_policy.decision_scope.value}` / "
        f"`{bundle.scope_policy.current_gate}`",
        f"- Indication: {brief.disease.label} (`{brief.disease.identifier}`)",
        f"- Population: {brief.population}",
        "",
        "## Disease brief",
        "",
        f"- Target tissues: {', '.join(brief.target_tissues)}",
        f"- Key cell states: {', '.join(brief.key_cell_states)}",
        f"- Desired outcomes: {', '.join(brief.desired_outcomes)}",
        f"- Constraints: {'; '.join(brief.constraints)}",
        f"- Treatment context: {brief.treatment_context.severity}; "
        f"prior therapy: {', '.join(brief.treatment_context.prior_therapy_requirements)}",
        "",
        "Anatomical and sampling scope:",
        "",
        *[
            f"- {item.region} / {item.compartment} — {item.sampling_method}; {item.accessibility}; "
            f"decision window: {item.decision_window}"
            for item in brief.anatomical_contexts
        ],
        "",
        "## Hypothesis cards",
        "",
    ]

    for index, hypothesis in enumerate(bundle.hypotheses, start=1):
        decision = decisions[hypothesis.id]
        lines.extend(
            [
                f"### {index}. {hypothesis.target.entity.label} — {hypothesis.intervention.direction.value}",
                "",
                f"- ID: `{hypothesis.id}`",
                f"- Decision scope / gate: {hypothesis.decision_scope.value} / {hypothesis.current_gate}",
                f"- Explicit non-goals: {'; '.join(hypothesis.non_goals)}",
                f"- Target form: {hypothesis.target.biological_form.value} — {hypothesis.target.molecular_scope}",
                f"- Population / state: {hypothesis.population} / {hypothesis.cell_state}",
                f"- Intervention: {hypothesis.intervention.direction.value}; "
                f"{hypothesis.intervention.degree}; {hypothesis.intervention.modality.value}",
                f"- Molecular action: {hypothesis.intervention.molecular_action}",
                f"- Selectivity: {'; '.join(hypothesis.intervention.selectivity_requirements)}",
                f"- Distribution / route: {hypothesis.intervention.desired_distribution}; {hypothesis.intervention.route}",
                f"- Mechanistic role: {hypothesis.mechanism_context.mechanistic_role.value}",
                f"- Source → responding → effector cells: {', '.join(hypothesis.mechanism_context.source_cells)} → "
                f"{', '.join(hypothesis.mechanism_context.responding_cells)} → "
                f"{', '.join(hypothesis.mechanism_context.effector_cells)}",
                f"- Bypass / compensation: {'; '.join(hypothesis.mechanism_context.bypass_or_compensation)}",
                f"- Biomarker ({hypothesis.biomarker.role.value}): {hypothesis.biomarker.name}; "
                f"matrix: {hypothesis.biomarker.matrix}; assay: {hypothesis.biomarker.assay}",
                f"- Biomarker validation: analytical={hypothesis.biomarker.analytical_validation.value}; "
                f"clinical={hypothesis.biomarker.clinical_validation.value}",
                f"- Fatal assumption: {hypothesis.fatal_assumption}",
                f"- Decision: **{decision.verdict.value}**",
            ]
        )
        if decision.abstention_reason:
            lines.append(f"- Abstention reason: {decision.abstention_reason}")
        lines.extend(["", "Supporting claims:", "", *_claim_lines(bundle, hypothesis.supporting_claim_ids)])
        lines.extend(["", "Counterevidence / qualifiers:", "", *_claim_lines(bundle, hypothesis.counterevidence_claim_ids)])
        lines.extend(["", "Falsifiable predictions:", ""])
        for prediction in hypothesis.falsifiable_predictions:
            lines.append(
                f"- {prediction.statement} **Refute if:** {prediction.refutation_condition} "
                f"_(criterion: `{prediction.decision_criterion.id}`; "
                f"threshold: {prediction.decision_criterion.threshold_status.value})_"
            )
        lines.extend(["", "Target engagement, PD, safety, and biomarker criteria:", ""])
        lines.extend(
            _criterion_lines(
                [
                    hypothesis.intervention.target_engagement_criterion,
                    *hypothesis.intervention.pharmacodynamic_criteria,
                    *hypothesis.intervention.safety_criteria,
                    hypothesis.biomarker.cutoff_criterion,
                ]
            )
        )
        lines.extend(["", "Decision-head status:", ""])
        for name, assessment in decision.assessments.items():
            lines.append(f"- {name}: `{assessment.status}` — {assessment.reason}")
        lines.extend(["", "Proposed next experiments:", ""])
        for action in actions.get(hypothesis.id, []):
            lines.append(
                f"- **{action.assay_type}:** {action.design}  \n"
                f"  Assumption: {action.assumption_tested}  \n"
                f"  Model: {action.model_system}  \n"
                f"  Controls: {', '.join(control.name for control in action.controls)}  \n"
                f"  Sample plan: {action.sample_plan.status.value} — {action.sample_plan.rationale}  \n"
                f"  Primary endpoint: {action.primary_endpoint.endpoint} "
                f"({action.primary_endpoint.threshold_status.value})  \n"
                f"  Threshold derivation: {action.primary_endpoint.threshold_derivation}  \n"
                f"  Information gain: {action.expected_information_gain}  \n"
                f"  Go/no-go: {action.go_no_go_rule}"
            )
        lines.append("")

    lines.extend(
        [
            "## Evidence ledger",
            "",
            "| Evidence ID | Level | Source / locator | Polarity | Available on | Status |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for evidence in bundle.evidence_records:
        lines.append(
            f"| `{evidence.id}` | {evidence.evidence_level.value} | "
            f"{evidence.source_record_id}; {evidence.locator} | {evidence.polarity.value} | {evidence.available_on.isoformat()} "
            f"| {evidence.curation_status.value} |"
        )
    if bundle.review_records:
        lines.extend(["", "## Review history", ""])
        for review in bundle.review_records:
            lines.append(
                f"- Round {review.review_round} — **{review.outcome.value}** — {review.reviewer_label}; "
                f"{review.resolution_status} (`{review.source_path}`)"
            )
    lines.extend(
        [
            "",
            "## Frozen scope and change control",
            "",
            f"Acceptance rule: {bundle.scope_policy.acceptance_rule}",
            "",
            f"Change-control rule: {bundle.scope_policy.change_control_rule}",
            "",
            "Explicitly deferred:",
            "",
            *[f"- {item}" for item in bundle.scope_policy.explicitly_deferred],
        ]
    )
    lines.append("")
    return "\n".join(lines)


def export_dossier(bundle: ProjectBundle, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dossier.json"
    markdown_path = output_dir / "dossier.md"
    json_path.write_text(bundle_json(bundle), encoding="utf-8")
    markdown_path.write_text(bundle_markdown(bundle), encoding="utf-8")
    return [json_path, markdown_path]
