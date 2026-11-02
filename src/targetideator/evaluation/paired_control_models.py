"""Contracts for the P6.3 proposer-only versus falsify-revise paired control."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId, Verdict
from targetideator.evidence.models import StrictModel
from targetideator.falsification.models import FailureTaxonomy
from targetideator.revision.models import RevisionStatus


class CriticCellAuditRecord(StrictModel):
    id: StableId
    pair_id: StableId
    hypothesis_id: StableId
    assessment_id: StableId
    critic_type: FailureTaxonomy
    verdict: Verdict
    evidence_gap_count: int = Field(ge=0)
    counterevidence_claim_count: int = Field(ge=0)
    critic_exposed_unsupported_proxy: bool
    proposer_only_qualification_present: Literal[False] = False
    revision_patch_count: int = Field(ge=0)
    full_path_qualification_present: bool
    counterevidence_retained_in_revised_core: bool
    survive_patch_leak: bool
    scientific_correctness_label_available: Literal[False] = False
    human_adjudication_count: Literal[0] = 0


class PairedControlRecord(StrictModel):
    id: StableId
    hypothesis_id: StableId
    target_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    proposer_only_arm: Literal["p3_unqualified_emit"] = "p3_unqualified_emit"
    full_path_arm: Literal[
        "p3_generate_p4_falsify_p4_1_constraint_revision"
    ] = "p3_generate_p4_falsify_p4_1_constraint_revision"
    critic_cell_count: Literal[4] = 4
    surviving_critic_count: int = Field(ge=0, le=4)
    critic_exposed_unsupported_proxy_count: int = Field(ge=0, le=4)
    proposer_only_unqualified_proxy_count: int = Field(ge=0, le=4)
    full_path_unqualified_proxy_count: int = Field(ge=0, le=4)
    unsupported_proxy_reduction_count: int = Field(ge=0, le=4)
    unsupported_proxy_reduction_fraction: float = Field(ge=0, le=1)
    source_counterevidence_binding_count: int = Field(ge=0)
    critic_counterevidence_retained_count: int = Field(ge=0)
    revised_counterevidence_retained_count: int = Field(ge=0)
    counterevidence_retention_fraction: float | None = Field(default=None, ge=0, le=1)
    combined_verdict: Verdict
    revision_status: RevisionStatus
    revision_patch_count: int = Field(ge=0)
    covered_non_survive_critic_count: int = Field(ge=0, le=4)
    abstain_critic_count: int = Field(ge=0, le=4)
    abstain_to_block_propagated: bool
    potential_false_rejection_review_required: bool
    false_rejection_label_available: Literal[False] = False
    surviving_critic_patch_leak_count: Literal[0] = 0
    core_scientific_mutation_count: Literal[0] = 0
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0


class FalseRejectionPropagationRecord(StrictModel):
    id: StableId
    pair_id: StableId
    hypothesis_id: StableId
    target_id: str = Field(min_length=1)
    abstaining_assessment_ids: list[StableId] = Field(min_length=1)
    abstaining_critic_types: list[FailureTaxonomy] = Field(min_length=1)
    combined_verdict: Literal[Verdict.ABSTAIN] = Verdict.ABSTAIN
    revision_status: Literal[RevisionStatus.BLOCKED_PENDING_EVIDENCE] = (
        RevisionStatus.BLOCKED_PENDING_EVIDENCE
    )
    propagation_path: Literal[
        "critic_abstention_to_hypothesis_block_pending_evidence"
    ] = "critic_abstention_to_hypothesis_block_pending_evidence"
    adjudication_status: Literal["unresolved_no_human_gold"] = "unresolved_no_human_gold"
    included_in_false_rejection_rate: Literal[False] = False


class PairedControlQuality(StrictModel):
    paired_hypothesis_count: Literal[5] = 5
    critic_cell_count: Literal[20] = 20
    false_rejection_queue_count: Literal[3] = 3
    proposer_only_unqualified_proxy_count: Literal[16] = 16
    full_path_unqualified_proxy_count: Literal[0] = 0
    unsupported_proxy_reduction_count: Literal[16] = 16
    unsupported_proxy_reduction_fraction: Literal[1.0] = 1.0
    source_counterevidence_binding_count: Literal[4] = 4
    critic_counterevidence_retained_count: Literal[4] = 4
    revised_counterevidence_retained_count: Literal[4] = 4
    counterevidence_retention_fraction: Literal[1.0] = 1.0
    surviving_critic_count: Literal[4] = 4
    surviving_critic_patch_leak_count: Literal[0] = 0
    abstain_critic_count: Literal[8] = 8
    abstain_to_block_propagation_count: Literal[3] = 3
    false_rejection_rate_computed: Literal[False] = False
    human_adjudicated_false_rejection_count: Literal[0] = 0
    retired_by_rejection_count: Literal[0] = 0
    core_scientific_mutation_count: Literal[0] = 0
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c3_paired_engineering_control_completed: bool
    c3_scientific_claim_unlocked: Literal[False] = False
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class PairedControlSnapshot(StrictModel):
    schema_version: Literal["6.3.0"] = "6.3.0"
    id: StableId
    created_at: datetime
    pair_policy: Literal[
        "same_frozen_hypothesis_proposer_only_vs_deterministic_falsify_constraint_revision"
    ] = "same_frozen_hypothesis_proposer_only_vs_deterministic_falsify_constraint_revision"
    unsupported_proxy_policy: Literal[
        "non_survive_critic_cell_with_gap_is_unqualified_in_proposer_and_covered_by_revision_provenance"
    ] = "non_survive_critic_cell_with_gap_is_unqualified_in_proposer_and_covered_by_revision_provenance"
    false_rejection_policy: Literal[
        "trace_abstain_to_block_but_do_not_compute_rate_without_gold"
    ] = "trace_abstain_to_block_but_do_not_compute_rate_without_gold"
    pair_path: str = Field(min_length=1)
    pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    critic_audit_path: str = Field(min_length=1)
    critic_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    false_rejection_queue_path: str = Field(min_length=1)
    false_rejection_queue_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: PairedControlQuality
    warning: str = Field(min_length=1)


class PairedControlManifest(StrictModel):
    schema_version: Literal["6.3.0"] = "6.3.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    pair_path: str = Field(min_length=1)
    pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pair_record_count: Literal[5] = 5
    critic_audit_path: str = Field(min_length=1)
    critic_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    critic_audit_record_count: Literal[20] = 20
    false_rejection_queue_path: str = Field(min_length=1)
    false_rejection_queue_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    false_rejection_queue_record_count: Literal[3] = 3
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
