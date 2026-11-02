"""Strict contracts for P4.1 structure-only hypothesis revision."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.contracts.models import StableId, Verdict
from targetideator.evidence.models import StrictModel
from targetideator.falsification.models import FailureTaxonomy
from targetideator.ideation.models import ComposedHypothesis


class RevisionField(StrEnum):
    PROPOSED_DIRECTION = "proposed_direction"
    PROPOSED_MODALITY = "proposed_modality"
    POPULATION = "population"
    CELL_STATE = "cell_state"
    MECHANISM_CLAIM_IDS = "mechanism_claim_ids"
    CAUSAL_VALIDATION = "constraints.causal_validation"
    DIRECTION_BOUNDARY = "constraints.direction_boundary"
    TRANSLATION_BOUNDARY = "constraints.translation_boundary"
    EXPOSURE_WINDOW = "constraints.exposure_window"
    SAFETY_CONSTRAINTS = "constraints.safety_constraints"


class RevisionOperation(StrEnum):
    ADD_REQUIREMENT = "add_requirement"
    RETAIN_PENDING_VALIDATION = "retain_pending_validation"
    MARK_UNRESOLVED = "mark_unresolved"


class RevisionStatus(StrEnum):
    BLOCKED_PENDING_EVIDENCE = "blocked_pending_evidence"
    CONSTRAINED_REVISION_PROPOSED = "constrained_revision_proposed"
    RETIRED_BY_REJECTION = "retired_by_rejection"
    UNCHANGED_SURVIVED = "unchanged_survived"


PatchValue = str | list[str]


class RevisionPatch(StrictModel):
    id: StableId
    field_path: RevisionField
    operation: RevisionOperation
    before_value: PatchValue
    after_value: PatchValue
    requirement: str = Field(min_length=1)
    source_assessment_id: StableId
    source_critic_type: FailureTaxonomy
    source_verdict: Verdict
    evidence_claim_ids: list[StableId]
    route_evidence_ids: list[StableId]
    rationale: str = Field(min_length=1)
    scientific_value_imputed: Literal[False] = False

    @model_validator(mode="after")
    def patch_is_conservative(self) -> "RevisionPatch":
        if self.source_verdict == Verdict.SURVIVE:
            raise ValueError("surviving critics cannot create revision patches")
        if self.operation == RevisionOperation.ADD_REQUIREMENT:
            if self.before_value != [] or not isinstance(self.after_value, list) or not self.after_value:
                raise ValueError("add_requirement must append to an empty constraint slot")
        elif self.before_value != self.after_value:
            raise ValueError("retain/mark-unresolved patches cannot mutate scientific values")
        if self.operation == RevisionOperation.MARK_UNRESOLVED and self.after_value != "unknown":
            raise ValueError("mark_unresolved must preserve an explicit unknown value")
        return self


class RevisionConstraints(StrictModel):
    causal_validation: list[str]
    direction_boundary: list[str]
    translation_boundary: list[str]
    exposure_window: list[str]
    safety_constraints: list[str]
    unresolved_assumptions: list[str]
    required_assessment_ids: list[StableId]


class RevisionCandidate(StrictModel):
    id: StableId
    revision_number: Literal[1] = 1
    source_hypothesis_id: StableId
    source_falsification_result_id: StableId
    source_combined_verdict: Verdict
    source_core_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revised_core_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hypothesis: ComposedHypothesis
    revised_hypothesis: ComposedHypothesis
    patches: list[RevisionPatch]
    constraints: RevisionConstraints
    unresolved_critic_types: list[FailureTaxonomy]
    revision_status: RevisionStatus
    eligible_for_p5_development: bool
    eligible_for_scientific_use: Literal[False] = False
    supersedes_source: Literal[False] = False
    rollback_source_hypothesis_id: StableId

    @model_validator(mode="after")
    def candidate_preserves_source(self) -> "RevisionCandidate":
        if self.source_hypothesis.id != self.source_hypothesis_id:
            raise ValueError("embedded source hypothesis ID mismatch")
        if self.revised_hypothesis.id != self.source_hypothesis_id:
            raise ValueError("P4.1 cannot silently mint or replace a core hypothesis")
        if self.source_hypothesis != self.revised_hypothesis:
            raise ValueError("P4.1 may add constraints but cannot mutate core scientific values")
        if self.source_core_sha256 != self.revised_core_sha256:
            raise ValueError("core hypothesis fingerprint changed during conservative revision")
        if self.rollback_source_hypothesis_id != self.source_hypothesis_id:
            raise ValueError("rollback pointer must reference the source hypothesis")
        patch_types = {item.source_critic_type for item in self.patches}
        if patch_types != set(self.unresolved_critic_types):
            raise ValueError("every unresolved critic must contribute at least one patch")
        if self.source_combined_verdict == Verdict.ABSTAIN:
            expected = RevisionStatus.BLOCKED_PENDING_EVIDENCE
        elif self.source_combined_verdict == Verdict.REVISE:
            expected = RevisionStatus.CONSTRAINED_REVISION_PROPOSED
        elif self.source_combined_verdict == Verdict.REJECT:
            expected = RevisionStatus.RETIRED_BY_REJECTION
        else:
            expected = RevisionStatus.UNCHANGED_SURVIVED
        if self.revision_status != expected:
            raise ValueError("revision status must be derived from the source combined verdict")
        eligible = self.revision_status in {
            RevisionStatus.CONSTRAINED_REVISION_PROPOSED,
            RevisionStatus.UNCHANGED_SURVIVED,
        }
        if self.eligible_for_p5_development != eligible:
            raise ValueError("P5 development eligibility differs from revision status")
        return self


class RevisionQuality(StrictModel):
    candidate_count: int = Field(ge=0)
    patch_count: int = Field(ge=0)
    status_counts: dict[RevisionStatus, int]
    operation_counts: dict[RevisionOperation, int]
    source_binding_coverage: float = Field(ge=0, le=1)
    unresolved_critic_patch_coverage: float = Field(ge=0, le=1)
    whitelist_violation_count: int = Field(ge=0)
    core_scientific_mutation_count: int = Field(ge=0)
    scientific_value_imputation_count: int = Field(ge=0)
    p5_development_eligible_count: int = Field(ge=0)
    human_review_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p4_revision_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class RevisionSnapshot(StrictModel):
    schema_version: Literal["4.1-development.1"] = "4.1-development.1"
    id: StableId
    created_at: datetime
    as_of_date: date
    source_portfolio_id: StableId
    source_falsification_snapshot_id: StableId
    source_falsification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_fields: list[RevisionField] = Field(min_length=1)
    candidates: list[RevisionCandidate] = Field(min_length=1)
    quality: RevisionQuality
    policy: Literal[
        "constraints_only_no_scientific_value_imputation_no_source_supersession"
    ] = "constraints_only_no_scientific_value_imputation_no_source_supersession"
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def snapshot_integrity(self) -> "RevisionSnapshot":
        if self.allowed_fields != list(RevisionField):
            raise ValueError("revision whitelist must be fixed and canonically ordered")
        source_ids = [item.source_hypothesis_id for item in self.candidates]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("each source hypothesis may have only one revision candidate")
        patches = [item for candidate in self.candidates for item in candidate.patches]
        if any(item.field_path not in self.allowed_fields for item in patches):
            raise ValueError("revision patch escaped the field whitelist")
        if self.quality.candidate_count != len(self.candidates):
            raise ValueError("revision candidate count mismatch")
        if self.quality.patch_count != len(patches):
            raise ValueError("revision patch count mismatch")
        if self.quality.status_counts != dict(
            Counter(item.revision_status for item in self.candidates)
        ):
            raise ValueError("revision status counts mismatch")
        if self.quality.operation_counts != dict(Counter(item.operation for item in patches)):
            raise ValueError("revision operation counts mismatch")
        return self


class RevisionManifest(StrictModel):
    schema_version: Literal["4.1-development.1"] = "4.1-development.1"
    snapshot_id: StableId
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    patch_count: int = Field(ge=0)
    scientific_validation_gate_passed: Literal[False] = False
