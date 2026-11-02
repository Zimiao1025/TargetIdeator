"""Contracts for the P6.5 frozen claim-disposition synthesis."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evaluation.models import ClaimEvaluationStatus
from targetideator.evidence.models import StrictModel


class ExperimentResultClass(StrEnum):
    AUDIT_BOUNDARY = "audit_boundary"
    STRUCTURAL_SENSITIVITY = "structural_sensitivity"
    ENGINEERING_INVARIANCE = "engineering_invariance"
    UNVALIDATED_PROXY_REDUCTION = "unvalidated_proxy_reduction"
    DECISION_LEVEL_NEGATIVE = "decision_level_negative"


class ClaimDispositionRecord(StrictModel):
    id: StableId
    claim_code: Literal["C1", "C2", "C3", "C4", "C5", "C6"]
    title: str = Field(min_length=1)
    baseline_status: ClaimEvaluationStatus
    synthesized_status: ClaimEvaluationStatus
    status_changed: Literal[False] = False
    supporting_experiment_ids: list[Literal["P6.0", "P6.1", "P6.2", "P6.3", "P6.4"]] = Field(
        min_length=1
    )
    completed_engineering_control_count: int = Field(ge=0)
    scientifically_decisive_metric_count: Literal[0] = 0
    scientifically_supported: Literal[False] = False
    positive_conclusion_allowed: Literal[False] = False
    synthesized_finding: str = Field(min_length=1)
    remaining_blockers: list[str] = Field(min_length=1)
    forbidden_conclusions: list[str] = Field(min_length=1)


class ExperimentDispositionRecord(StrictModel):
    id: StableId
    experiment_id: Literal["P6.0", "P6.1", "P6.2", "P6.3", "P6.4"]
    source_snapshot_id: StableId
    source_manifest_filename: str = Field(min_length=1)
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    primary_claim_codes: list[Literal["C1", "C2", "C3", "C4", "C5", "C6"]] = Field(
        min_length=1
    )
    result_class: ExperimentResultClass
    observed_finding: str = Field(min_length=1)
    intended_scope: str = Field(min_length=1)
    source_manifest_frozen: Literal[True] = True
    scope_preserved: Literal[True] = True
    result_reported_without_gate_promotion: Literal[True] = True
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    future_outcome_reveal_count: Literal[0] = 0
    scientific_validation_gate_passed: Literal[False] = False


class ClaimSynthesisQuality(StrictModel):
    claim_count: Literal[6] = 6
    experiment_count: Literal[5] = 5
    source_manifest_count: Literal[5] = 5
    source_manifest_checksum_coverage: Literal[1.0] = 1.0
    scientifically_supported_claim_count: Literal[0] = 0
    engineering_evidence_only_claim_count: Literal[2] = 2
    blocked_claim_count: Literal[3] = 3
    deferred_claim_count: Literal[1] = 1
    claim_status_changed_count: Literal[0] = 0
    scientifically_decisive_metric_count: Literal[0] = 0
    completed_engineering_control_count: Literal[4] = 4
    decision_level_negative_result_count: Literal[1] = 1
    future_outcome_reveal_count: Literal[0] = 0
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class ClaimSynthesisSnapshot(StrictModel):
    schema_version: Literal["6.5.0"] = "6.5.0"
    id: StableId
    created_at: datetime
    synthesis_policy: Literal[
        "frozen_manifest_claim_disposition_without_gate_promotion"
    ] = "frozen_manifest_claim_disposition_without_gate_promotion"
    claim_disposition_path: str = Field(min_length=1)
    claim_disposition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_disposition_path: str = Field(min_length=1)
    experiment_disposition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_table_path: str = Field(min_length=1)
    paper_table_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: ClaimSynthesisQuality
    warning: str = Field(min_length=1)


class ClaimSynthesisManifest(StrictModel):
    schema_version: Literal["6.5.0"] = "6.5.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=5, max_length=5)
    claim_disposition_path: str = Field(min_length=1)
    claim_disposition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_disposition_record_count: Literal[6] = 6
    experiment_disposition_path: str = Field(min_length=1)
    experiment_disposition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_disposition_record_count: Literal[5] = 5
    paper_table_path: str = Field(min_length=1)
    paper_table_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
