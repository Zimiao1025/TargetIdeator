"""Build and load deterministic P4.1 conservative revision artifacts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.contracts.models import InterventionDirection, Modality, Verdict
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.models import (
    CriticAssessment,
    FailureTaxonomy,
    FalsificationResult,
)
from targetideator.falsification.store import (
    default_falsification_manifest_path,
    default_falsification_snapshot_path,
    load_default_falsification_store,
)
from targetideator.ids import canonical_json_bytes, content_digest, stable_id
from targetideator.ideation.models import ComposedHypothesis
from targetideator.ideation.store import (
    default_ideation_portfolio_path,
    load_default_ideation_store,
)
from targetideator.io import write_json
from targetideator.revision.models import (
    RevisionCandidate,
    RevisionConstraints,
    RevisionField,
    RevisionManifest,
    RevisionOperation,
    RevisionPatch,
    RevisionQuality,
    RevisionSnapshot,
    RevisionStatus,
)

BUILDER_VERSION = "p4-conservative-structured-revision-v1"
SNAPSHOT_ID = "ti:revision-snapshot:crohns-p4-1-development-v1"
CREATED_AT = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def default_revision_snapshot_path() -> Path:
    return fixture_path("p4_revision_snapshot.json")


def default_revision_manifest_path() -> Path:
    return fixture_path("p4_revision_manifest.json")


_P4_TO_PATCH_FIELD = {
    "causal_claim": RevisionField.CAUSAL_VALIDATION,
    "mechanism_chain": RevisionField.MECHANISM_CLAIM_IDS,
    "proposed_direction": RevisionField.PROPOSED_DIRECTION,
    "cell_state": RevisionField.CELL_STATE,
    "dose_context": RevisionField.DIRECTION_BOUNDARY,
    "population": RevisionField.POPULATION,
    "translation_boundary": RevisionField.TRANSLATION_BOUNDARY,
    "proposed_modality": RevisionField.PROPOSED_MODALITY,
    "exposure_window": RevisionField.EXPOSURE_WINDOW,
    "safety_constraints": RevisionField.SAFETY_CONSTRAINTS,
}

_FIELD_CRITIC_PRIORITY = {
    RevisionField.CAUSAL_VALIDATION: [FailureTaxonomy.CAUSAL],
    RevisionField.MECHANISM_CLAIM_IDS: [FailureTaxonomy.CAUSAL],
    RevisionField.PROPOSED_DIRECTION: [FailureTaxonomy.DIRECTION],
    RevisionField.CELL_STATE: [FailureTaxonomy.DIRECTION, FailureTaxonomy.TRANSLATION],
    RevisionField.DIRECTION_BOUNDARY: [FailureTaxonomy.DIRECTION],
    RevisionField.POPULATION: [FailureTaxonomy.TRANSLATION],
    RevisionField.TRANSLATION_BOUNDARY: [FailureTaxonomy.TRANSLATION],
    RevisionField.PROPOSED_MODALITY: [FailureTaxonomy.SAFETY],
    RevisionField.EXPOSURE_WINDOW: [FailureTaxonomy.SAFETY],
    RevisionField.SAFETY_CONSTRAINTS: [FailureTaxonomy.SAFETY],
}


def _assessment_for_field(
    result: FalsificationResult, field: RevisionField
) -> CriticAssessment:
    by_type = {item.critic_type: item for item in result.assessments}
    for critic_type in _FIELD_CRITIC_PRIORITY[field]:
        assessment = by_type[critic_type]
        if assessment.verdict != Verdict.SURVIVE:
            return assessment
    raise ValueError(f"no unresolved critic can justify revision field {field.value}")


def _base_value(hypothesis: ComposedHypothesis, field: RevisionField):
    if field == RevisionField.PROPOSED_DIRECTION:
        return hypothesis.proposed_direction.value
    if field == RevisionField.PROPOSED_MODALITY:
        return hypothesis.proposed_modality.value
    if field == RevisionField.POPULATION:
        return hypothesis.population
    if field == RevisionField.CELL_STATE:
        return hypothesis.cell_state
    if field == RevisionField.MECHANISM_CLAIM_IDS:
        return list(hypothesis.mechanism_claim_ids)
    return []


def _operation(hypothesis: ComposedHypothesis, field: RevisionField) -> RevisionOperation:
    constraint_fields = {
        RevisionField.CAUSAL_VALIDATION,
        RevisionField.DIRECTION_BOUNDARY,
        RevisionField.TRANSLATION_BOUNDARY,
        RevisionField.EXPOSURE_WINDOW,
        RevisionField.SAFETY_CONSTRAINTS,
    }
    if field in constraint_fields:
        return RevisionOperation.ADD_REQUIREMENT
    if (
        field == RevisionField.PROPOSED_DIRECTION
        and hypothesis.proposed_direction == InterventionDirection.UNKNOWN
    ) or (
        field == RevisionField.PROPOSED_MODALITY
        and hypothesis.proposed_modality == Modality.UNKNOWN
    ):
        return RevisionOperation.MARK_UNRESOLVED
    return RevisionOperation.RETAIN_PENDING_VALIDATION


def _build_patch(
    hypothesis: ComposedHypothesis,
    result: FalsificationResult,
    field: RevisionField,
) -> RevisionPatch:
    assessment = _assessment_for_field(result, field)
    operation = _operation(hypothesis, field)
    before = _base_value(hypothesis, field)
    requirement = assessment.falsifiable_prediction.required_observation
    after = [requirement] if operation == RevisionOperation.ADD_REQUIREMENT else before
    return RevisionPatch(
        id=stable_id(
            "revision-patch",
            f"{hypothesis.id}-{field.value}-{assessment.critic_type.value}",
        ),
        field_path=field,
        operation=operation,
        before_value=before,
        after_value=after,
        requirement=requirement,
        source_assessment_id=assessment.id,
        source_critic_type=assessment.critic_type,
        source_verdict=assessment.verdict,
        evidence_claim_ids=assessment.evidence_claim_ids,
        route_evidence_ids=assessment.route_evidence_ids,
        rationale=assessment.rationale,
    )


def _status(verdict: Verdict) -> RevisionStatus:
    return {
        Verdict.ABSTAIN: RevisionStatus.BLOCKED_PENDING_EVIDENCE,
        Verdict.REVISE: RevisionStatus.CONSTRAINED_REVISION_PROPOSED,
        Verdict.REJECT: RevisionStatus.RETIRED_BY_REJECTION,
        Verdict.SURVIVE: RevisionStatus.UNCHANGED_SURVIVED,
    }[verdict]


def _constraint_values(patches: list[RevisionPatch], field: RevisionField) -> list[str]:
    values = [
        item.requirement
        for item in patches
        if item.field_path == field and item.operation == RevisionOperation.ADD_REQUIREMENT
    ]
    return list(dict.fromkeys(values))


def _build_candidate(
    hypothesis: ComposedHypothesis, result: FalsificationResult
) -> RevisionCandidate:
    unknown_fields = set(result.revision_fields) - set(_P4_TO_PATCH_FIELD)
    if unknown_fields:
        raise ValueError(f"P4 revision fields are not mapped: {sorted(unknown_fields)}")
    fields = list(
        dict.fromkeys(_P4_TO_PATCH_FIELD[item] for item in result.revision_fields)
    )
    patches = [_build_patch(hypothesis, result, field) for field in fields]
    unresolved = [
        item for item in result.assessments if item.verdict != Verdict.SURVIVE
    ]
    constraints = RevisionConstraints(
        causal_validation=_constraint_values(patches, RevisionField.CAUSAL_VALIDATION),
        direction_boundary=_constraint_values(patches, RevisionField.DIRECTION_BOUNDARY),
        translation_boundary=_constraint_values(
            patches, RevisionField.TRANSLATION_BOUNDARY
        ),
        exposure_window=_constraint_values(patches, RevisionField.EXPOSURE_WINDOW),
        safety_constraints=_constraint_values(
            patches, RevisionField.SAFETY_CONSTRAINTS
        ),
        unresolved_assumptions=[item.fatal_assumption for item in unresolved],
        required_assessment_ids=[item.id for item in unresolved],
    )
    fingerprint = content_digest(hypothesis.model_dump(mode="json"))
    status = _status(result.combined_verdict)
    return RevisionCandidate(
        id=stable_id("revision-candidate", f"{hypothesis.id}-r1"),
        source_hypothesis_id=hypothesis.id,
        source_falsification_result_id=result.id,
        source_combined_verdict=result.combined_verdict,
        source_core_sha256=fingerprint,
        revised_core_sha256=fingerprint,
        source_hypothesis=hypothesis,
        revised_hypothesis=hypothesis.model_copy(deep=True),
        patches=patches,
        constraints=constraints,
        unresolved_critic_types=[item.critic_type for item in unresolved],
        revision_status=status,
        eligible_for_p5_development=status
        in {
            RevisionStatus.CONSTRAINED_REVISION_PROPOSED,
            RevisionStatus.UNCHANGED_SURVIVED,
        },
        rollback_source_hypothesis_id=hypothesis.id,
    )


def build_revision_snapshot() -> RevisionSnapshot:
    portfolio = load_default_ideation_store().portfolio
    falsification = load_default_falsification_store().snapshot
    hypotheses = {item.id: item for item in portfolio.hypotheses}
    candidates = [
        _build_candidate(hypotheses[result.hypothesis_id], result)
        for result in falsification.results
    ]
    patches = [item for candidate in candidates for item in candidate.patches]
    source_binding = sum(
        item.source_hypothesis_id in hypotheses for item in candidates
    ) / len(candidates)
    unresolved_pairs = [
        (candidate, critic_type)
        for candidate in candidates
        for critic_type in candidate.unresolved_critic_types
    ]
    unresolved_coverage = (
        sum(
            any(patch.source_critic_type == critic_type for patch in candidate.patches)
            for candidate, critic_type in unresolved_pairs
        )
        / len(unresolved_pairs)
        if unresolved_pairs
        else 1.0
    )
    whitelist_violations = sum(
        item.field_path not in set(RevisionField) for item in patches
    )
    core_mutations = sum(
        item.source_core_sha256 != item.revised_core_sha256 for item in candidates
    )
    imputations = sum(item.scientific_value_imputed for item in patches)
    engineering_gate = (
        len(candidates) == len(portfolio.hypotheses)
        and source_binding == 1.0
        and unresolved_coverage == 1.0
        and whitelist_violations == 0
        and core_mutations == 0
        and imputations == 0
    )
    quality = RevisionQuality(
        candidate_count=len(candidates),
        patch_count=len(patches),
        status_counts=dict(Counter(item.revision_status for item in candidates)),
        operation_counts=dict(Counter(item.operation for item in patches)),
        source_binding_coverage=source_binding,
        unresolved_critic_patch_coverage=unresolved_coverage,
        whitelist_violation_count=whitelist_violations,
        core_scientific_mutation_count=core_mutations,
        scientific_value_imputation_count=imputations,
        p5_development_eligible_count=sum(
            item.eligible_for_p5_development for item in candidates
        ),
        engineering_gate_passed=engineering_gate,
        blocking_limitations=[
            "P4.1 adds constraints and validation requirements but does not resolve missing evidence.",
            "No scientific direction, modality, population, cell state, or mechanism claim is automatically rewritten.",
            "Revision candidates inherit P3 model-silver and P4 deterministic-critic limitations.",
            "P5 eligibility is development workflow routing, not scientific readiness or target prioritization.",
            "No human or expert validation is used in this slice.",
        ],
    )
    return RevisionSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        as_of_date=portfolio.as_of_date,
        source_portfolio_id=portfolio.id,
        source_falsification_snapshot_id=falsification.id,
        source_falsification_sha256=file_sha256(
            default_falsification_snapshot_path()
        ),
        allowed_fields=list(RevisionField),
        candidates=candidates,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY STRUCTURED REVISION. Patches add explicit constraints or preserve "
            "unknown values; they do not fill scientific gaps, supersede source hypotheses, or "
            "constitute validation."
        ),
    )


def render_revision_markdown(snapshot: RevisionSnapshot) -> str:
    lines = [
        "# TargetIdeator P4.1 conservative structured revisions",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Snapshot: `{snapshot.id}`",
        f"- Source falsification: `{snapshot.source_falsification_snapshot_id}`",
        f"- Candidates / patches: {len(snapshot.candidates)} / {snapshot.quality.patch_count}",
        f"- P5 development eligible: {snapshot.quality.p5_development_eligible_count}",
        f"- Engineering gate: `{snapshot.quality.engineering_gate_passed}`",
        f"- Scientific validation gate: `{snapshot.quality.scientific_validation_gate_passed}`",
        "",
        "## Revision candidates",
        "",
    ]
    for candidate in snapshot.candidates:
        hypothesis = candidate.source_hypothesis
        lines.extend(
            [
                f"### {hypothesis.target.label}: {hypothesis.proposed_direction.value} / {hypothesis.proposed_modality.value}",
                "",
                f"- Source: `{candidate.source_hypothesis_id}`",
                f"- P4 verdict: `{candidate.source_combined_verdict.value}`",
                f"- Revision status: `{candidate.revision_status.value}`",
                f"- Core fingerprint unchanged: `{candidate.source_core_sha256 == candidate.revised_core_sha256}`",
                f"- P5 development eligible: `{candidate.eligible_for_p5_development}`",
                "",
            ]
        )
        for patch in candidate.patches:
            lines.extend(
                [
                    f"#### `{patch.field_path.value}` · {patch.operation.value}",
                    "",
                    f"- Critic / verdict: `{patch.source_critic_type.value}` / `{patch.source_verdict.value}`",
                    f"- Before: `{patch.before_value}`",
                    f"- After: `{patch.after_value}`",
                    f"- Requirement: {patch.requirement}",
                    "",
                ]
            )
    lines.extend(["## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in snapshot.quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums() -> dict[str, str]:
    return {
        "p3_ideation_portfolio": file_sha256(default_ideation_portfolio_path()),
        "p4_falsification_snapshot": file_sha256(default_falsification_snapshot_path()),
        "p4_falsification_manifest": file_sha256(default_falsification_manifest_path()),
    }


def write_revision_artifacts(
    output_dir: Path,
) -> tuple[RevisionSnapshot, RevisionManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_revision_snapshot()
    snapshot_path = output_dir / "p4_revision_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p4_revision_report.md").write_text(
        render_revision_markdown(snapshot), encoding="utf-8"
    )
    manifest = RevisionManifest(
        snapshot_id=snapshot.id,
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        candidate_count=len(snapshot.candidates),
        patch_count=snapshot.quality.patch_count,
    )
    write_json(output_dir / "p4_revision_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class RevisionStore:
    def __init__(
        self,
        snapshot: RevisionSnapshot,
        manifest: RevisionManifest | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.snapshot_path = snapshot_path

    @classmethod
    def load(
        cls, snapshot_path: Path, manifest_path: Path | None = None
    ) -> "RevisionStore":
        try:
            snapshot = RevisionSnapshot.model_validate(_load_json(snapshot_path))
            manifest = (
                RevisionManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P4.1 revision artifact: {exc}") from exc
        return cls(snapshot, manifest, snapshot_path)

    def candidate(self, hypothesis_id: str) -> RevisionCandidate | None:
        return next(
            (
                item
                for item in self.snapshot.candidates
                if item.source_hypothesis_id == hypothesis_id
            ),
            None,
        )

    def quality_report(self) -> dict:
        deterministic = canonical_json_bytes(
            build_revision_snapshot().model_dump(mode="json")
        ) == canonical_json_bytes(self.snapshot.model_dump(mode="json"))
        normalized_checksum_matches = bool(
            self.manifest
            and self.snapshot_path
            and file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
        )
        source_checksums_match = bool(
            self.manifest and self.manifest.source_checksums == _source_checksums()
        )
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "policy": self.snapshot.policy,
            "deterministic_rebuild_matches": deterministic,
            "normalized_checksum_matches": normalized_checksum_matches,
            "source_checksums_match": source_checksums_match,
            "warning": self.snapshot.warning,
        }


def load_default_revision_store() -> RevisionStore:
    return RevisionStore.load(
        default_revision_snapshot_path(), default_revision_manifest_path()
    )
