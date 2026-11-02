"""Cross-record validation that cannot be expressed by isolated schemas."""

from __future__ import annotations

from collections import Counter

from .models import ProjectBundle


class BundleIntegrityError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Bundle integrity failed:\n- " + "\n- ".join(errors))


def _duplicate_ids(values: list[str]) -> set[str]:
    return {value for value, count in Counter(values).items() if count > 1}


def validate_bundle_integrity(bundle: ProjectBundle) -> ProjectBundle:
    errors: list[str] = []
    all_records = [
        bundle.disease_brief,
        *bundle.evidence_records,
        *bundle.claims,
        *bundle.claim_relations,
        *bundle.hypotheses,
        *bundle.decisions,
        *bundle.experiment_actions,
        *bundle.review_records,
    ]
    all_ids = [record.id for record in all_records]
    duplicates = _duplicate_ids(all_ids)
    if duplicates:
        errors.append(f"duplicate IDs: {', '.join(sorted(duplicates))}")

    evidence_ids = {record.id for record in bundle.evidence_records}
    claim_ids = {claim.id for claim in bundle.claims}
    hypothesis_ids = {hypothesis.id for hypothesis in bundle.hypotheses}
    cutoff = bundle.disease_brief.as_of_date

    if bundle.scope_policy.decision_scope.value != "target_validation":
        errors.append("P0.2 frozen bundle must target the target_validation decision scope")

    anatomical_ids = [item.id for item in bundle.disease_brief.anatomical_contexts]
    if duplicates := _duplicate_ids(anatomical_ids):
        errors.append(f"duplicate anatomical context IDs: {', '.join(sorted(duplicates))}")

    for evidence in bundle.evidence_records:
        if evidence.available_on > cutoff:
            errors.append(
                f"{evidence.id} became available {evidence.available_on} after cutoff {cutoff}"
            )
        if evidence.publication_date and evidence.publication_date > evidence.available_on:
            errors.append(f"{evidence.id} publication_date is after available_on")

    for claim in bundle.claims:
        missing = set(claim.evidence_ids) - evidence_ids
        if missing:
            errors.append(f"{claim.id} references missing evidence: {', '.join(sorted(missing))}")

    for relation in bundle.claim_relations:
        for field, value in (
            ("source_claim_id", relation.source_claim_id),
            ("target_claim_id", relation.target_claim_id),
        ):
            if value not in claim_ids:
                errors.append(f"{relation.id}.{field} references missing claim {value}")
        if relation.source_claim_id == relation.target_claim_id:
            errors.append(f"{relation.id} cannot relate a claim to itself")

    disease = bundle.disease_brief.disease
    for hypothesis in bundle.hypotheses:
        if hypothesis.decision_scope != bundle.scope_policy.decision_scope:
            errors.append(f"{hypothesis.id} decision_scope does not match frozen scope policy")
        if hypothesis.current_gate != bundle.scope_policy.current_gate:
            errors.append(f"{hypothesis.id} current_gate does not match frozen scope policy")
        if hypothesis.as_of_date != cutoff:
            errors.append(f"{hypothesis.id} as_of_date does not match disease brief cutoff")
        if (hypothesis.indication.namespace, hypothesis.indication.identifier) != (
            disease.namespace,
            disease.identifier,
        ):
            errors.append(f"{hypothesis.id} indication does not match disease brief")
        referenced_claims = (
            hypothesis.mechanism_claim_ids
            + hypothesis.supporting_claim_ids
            + hypothesis.counterevidence_claim_ids
        )
        missing = set(referenced_claims) - claim_ids
        if missing:
            errors.append(f"{hypothesis.id} references missing claims: {', '.join(sorted(missing))}")
        open_blockers = [
            item.field
            for item in [
                *hypothesis.target.unknowns,
                *hypothesis.mechanism_context.unknowns,
                *hypothesis.intervention.unknowns,
                *hypothesis.biomarker.unknowns,
            ]
            if item.blocking_for_current_gate
        ]
        if open_blockers:
            errors.append(
                f"{hypothesis.id} claims current-gate readiness with blocking unknowns: "
                f"{', '.join(sorted(open_blockers))}"
            )

    biomarker_ids = [hypothesis.biomarker.id for hypothesis in bundle.hypotheses]
    if duplicates := _duplicate_ids(biomarker_ids):
        errors.append(f"duplicate biomarker IDs: {', '.join(sorted(duplicates))}")

    criterion_ids: list[str] = []
    for hypothesis in bundle.hypotheses:
        intervention = hypothesis.intervention
        criterion_ids.extend(
            criterion.id
            for criterion in [
                intervention.target_engagement_criterion,
                *intervention.pharmacodynamic_criteria,
                *intervention.safety_criteria,
                hypothesis.biomarker.cutoff_criterion,
                *(prediction.decision_criterion for prediction in hypothesis.falsifiable_predictions),
            ]
        )

    for decision in bundle.decisions:
        if decision.hypothesis_id not in hypothesis_ids:
            errors.append(f"{decision.id} references missing hypothesis {decision.hypothesis_id}")
        if decision.as_of_date != cutoff:
            errors.append(f"{decision.id} as_of_date does not match disease brief cutoff")

    for action in bundle.experiment_actions:
        if action.hypothesis_id not in hypothesis_ids:
            errors.append(f"{action.id} references missing hypothesis {action.hypothesis_id}")
        criterion_ids.extend(
            criterion.id
            for criterion in [
                action.primary_endpoint,
                *action.secondary_endpoints,
                *action.decision_criteria,
            ]
        )

    if duplicates := _duplicate_ids(criterion_ids):
        errors.append(f"duplicate measurement criterion IDs: {', '.join(sorted(duplicates))}")

    decisions_by_hypothesis = Counter(d.hypothesis_id for d in bundle.decisions)
    actions_by_hypothesis = Counter(a.hypothesis_id for a in bundle.experiment_actions)
    for hypothesis_id in hypothesis_ids:
        if decisions_by_hypothesis[hypothesis_id] != 1:
            errors.append(f"{hypothesis_id} requires exactly one decision snapshot")
        if actions_by_hypothesis[hypothesis_id] < 1:
            errors.append(f"{hypothesis_id} requires at least one experiment action")

    if errors:
        raise BundleIntegrityError(errors)
    return bundle
