"""Contracts for P6.4 explicit-counterevidence masking ablation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId, Verdict
from targetideator.evidence.models import StrictModel
from targetideator.falsification.models import FailureTaxonomy


class CounterevidenceMaskLedgerRecord(StrictModel):
    id: StableId
    hypothesis_id: StableId
    target_id: str = Field(min_length=1)
    counterevidence_claim_id: StableId
    mechanism_chain_membership_retained: Literal[True] = True
    semantic_counter_role_masked: Literal[True] = True
    source_document_removed: Literal[False] = False


class CounterevidenceCellComparison(StrictModel):
    id: StableId
    hypothesis_id: StableId
    critic_type: FailureTaxonomy
    full_verdict: Verdict
    masked_verdict: Verdict
    verdict_changed: bool
    full_rule_id: str = Field(min_length=1)
    masked_rule_id: str = Field(min_length=1)
    rule_changed: bool
    full_evidence_claim_count: int = Field(ge=0)
    masked_evidence_claim_count: int = Field(ge=0)
    evidence_reference_count_changed: bool
    full_counterevidence_reference_count: int = Field(ge=0)
    masked_counterevidence_reference_count: Literal[0] = 0
    removed_counterevidence_reference_count: int = Field(ge=0)
    full_evidence_gap_count: int = Field(ge=0)
    masked_evidence_gap_count: int = Field(ge=0)
    scientific_correctness_label_available: Literal[False] = False


class CounterevidenceHypothesisComparison(StrictModel):
    id: StableId
    hypothesis_id: StableId
    target_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    masked_binding_count: int = Field(ge=0)
    full_combined_verdict: Verdict
    masked_combined_verdict: Verdict
    combined_verdict_changed: bool
    full_binding_critic_types: list[FailureTaxonomy] = Field(min_length=1)
    masked_binding_critic_types: list[FailureTaxonomy] = Field(min_length=1)
    binding_critic_set_changed: bool
    full_non_survive_critic_count: int = Field(ge=0, le=4)
    masked_non_survive_critic_count: int = Field(ge=0, le=4)
    qualification_proxy_lost_count: int = Field(ge=0, le=4)
    full_projected_revision_field_count: int = Field(ge=0)
    masked_projected_revision_field_count: int = Field(ge=0)
    projected_revision_fields_changed: bool
    full_blocked: bool
    masked_blocked: bool
    block_decision_changed: bool
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0


class CounterevidenceAblationQuality(StrictModel):
    paired_hypothesis_count: Literal[5] = 5
    critic_cell_count: Literal[20] = 20
    mask_ledger_record_count: Literal[4] = 4
    hypotheses_with_masked_counterevidence_count: Literal[4] = 4
    removed_counterevidence_reference_count: Literal[8] = 8
    cell_verdict_changed_count: Literal[1] = 1
    cell_rule_changed_count: Literal[2] = 2
    cell_evidence_reference_changed_count: Literal[7] = 7
    combined_verdict_changed_count: Literal[0] = 0
    binding_critic_set_changed_count: Literal[0] = 0
    projected_revision_fields_changed_count: Literal[1] = 1
    full_non_survive_critic_count: Literal[16] = 16
    masked_non_survive_critic_count: Literal[15] = 15
    qualification_proxy_lost_count: Literal[1] = 1
    full_blocked_hypothesis_count: Literal[3] = 3
    masked_blocked_hypothesis_count: Literal[3] = 3
    block_decision_changed_count: Literal[0] = 0
    counterevidence_local_sensitivity_detected: bool
    counterevidence_decision_level_sensitivity_detected: Literal[False] = False
    c3_counterevidence_decision_value_supported: Literal[False] = False
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class CounterevidenceAblationSnapshot(StrictModel):
    schema_version: Literal["6.4.0"] = "6.4.0"
    id: StableId
    created_at: datetime
    mask_policy: Literal[
        "retain_mechanism_documents_but_hide_explicit_refutes_counter_role"
    ] = "retain_mechanism_documents_but_hide_explicit_refutes_counter_role"
    comparison_policy: Literal[
        "same_hypothesis_same_rules_full_vs_counter_role_masked"
    ] = "same_hypothesis_same_rules_full_vs_counter_role_masked"
    mask_ledger_path: str = Field(min_length=1)
    mask_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_comparison_path: str = Field(min_length=1)
    cell_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis_comparison_path: str = Field(min_length=1)
    hypothesis_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: CounterevidenceAblationQuality
    warning: str = Field(min_length=1)


class CounterevidenceAblationManifest(StrictModel):
    schema_version: Literal["6.4.0"] = "6.4.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    mask_ledger_path: str = Field(min_length=1)
    mask_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_ledger_record_count: Literal[4] = 4
    cell_comparison_path: str = Field(min_length=1)
    cell_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_comparison_record_count: Literal[20] = 20
    hypothesis_comparison_path: str = Field(min_length=1)
    hypothesis_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hypothesis_comparison_record_count: Literal[5] = 5
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
