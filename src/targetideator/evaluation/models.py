"""Contracts for the P6.0 reproducible evaluation claim audit."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class ClaimEvaluationStatus(StrEnum):
    ENGINEERING_EVIDENCE_ONLY = "engineering_evidence_only"
    BLOCKED_BY_IDENTIFICATION = "blocked_by_identification"
    BLOCKED_BY_MISSING_GOLD = "blocked_by_missing_gold"
    DEFERRED_OUT_OF_SCOPE = "deferred_out_of_scope"


class PaperClaimRecord(StrictModel):
    id: StableId
    claim_code: Literal["C1", "C2", "C3", "C4", "C5", "C6"]
    title: str = Field(min_length=1)
    headline_for_first_paper: bool
    predeclared_claim: str = Field(min_length=1)
    falsification_condition: str = Field(min_length=1)
    required_metrics: list[str] = Field(min_length=1)
    bound_stage_ids: list[str] = Field(min_length=1)
    current_status: ClaimEvaluationStatus
    current_evidence: list[str] = Field(min_length=1)
    blockers: list[str] = Field(min_length=1)
    forbidden_conclusions: list[str] = Field(min_length=1)
    scientifically_supported: Literal[False] = False


class ArtifactInventoryRecord(StrictModel):
    id: StableId
    stage_id: str = Field(pattern=r"^P[1-5](?:\.[0-9]+)?$")
    manifest_filename: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_id: str = Field(min_length=1)
    bound_claim_codes: list[Literal["C1", "C2", "C3", "C4", "C5", "C6"]]
    checksum_frozen: Literal[True] = True
    scientific_gate_declared_passed: Literal[False] = False


class DecisionReplayRecord(StrictModel):
    id: StableId
    hypothesis_id: StableId
    as_of_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    target_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    disease_id: str = Field(min_length=1)
    population: str = Field(min_length=1)
    cell_state: str = Field(min_length=1)
    proposed_direction: str = Field(min_length=1)
    proposed_modality: str = Field(min_length=1)
    supporting_claim_count: int = Field(ge=0)
    counterevidence_claim_count: int = Field(ge=0)
    p3_verification_status: str = Field(min_length=1)
    p4_combined_verdict: str = Field(min_length=1)
    p4_critic_verdicts: dict[str, str] = Field(min_length=4)
    p4_evidence_gap_count: int = Field(ge=0)
    p4_1_revision_status: str = Field(min_length=1)
    p4_1_patch_count: int = Field(ge=0)
    p4_1_unresolved_critic_types: list[str]
    p5_decision_status: str = Field(min_length=1)
    p5_head_scores: dict[str, float | None] = Field(min_length=5)
    p5_missing_required_heads: list[str]
    p5_pareto_status: str = Field(min_length=1)
    future_outcome_reveal_status: Literal[
        "withheld_target_linkage_not_identifiable"
    ] = "withheld_target_linkage_not_identifiable"
    scientific_comparison_allowed: Literal[False] = False


class EvaluationQuality(StrictModel):
    paper_claim_count: Literal[6] = 6
    headline_claim_count: int = Field(ge=0)
    scientifically_supported_claim_count: Literal[0] = 0
    engineering_evidence_only_claim_count: int = Field(ge=0)
    blocked_claim_count: int = Field(ge=0)
    deferred_claim_count: int = Field(ge=0)
    artifact_inventory_count: int = Field(gt=0)
    artifact_checksum_coverage: float = Field(ge=0, le=1)
    replay_hypothesis_count: int = Field(gt=0)
    replay_stage_count: Literal[4] = 4
    future_outcome_reveal_count: Literal[0] = 0
    unsupported_positive_claim_count: Literal[0] = 0
    target_level_metric_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class EvaluationSnapshot(StrictModel):
    schema_version: Literal["6.0.0"] = "6.0.0"
    id: StableId
    created_at: datetime
    as_of_date: Literal["2026-10-31"] = "2026-10-31"
    claim_policy: Literal[
        "predeclared_claims_with_falsification_conditions_and_forbidden_conclusions"
    ] = "predeclared_claims_with_falsification_conditions_and_forbidden_conclusions"
    replay_policy: Literal[
        "p3_to_p5_pipeline_replay_without_future_outcome_reveal"
    ] = "p3_to_p5_pipeline_replay_without_future_outcome_reveal"
    claim_registry_path: str = Field(min_length=1)
    claim_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_inventory_path: str = Field(min_length=1)
    artifact_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_replay_path: str = Field(min_length=1)
    decision_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: EvaluationQuality
    warning: str = Field(min_length=1)


class EvaluationManifest(StrictModel):
    schema_version: Literal["6.0.0"] = "6.0.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=10)
    claim_registry_path: str = Field(min_length=1)
    claim_registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_registry_count: Literal[6] = 6
    artifact_inventory_path: str = Field(min_length=1)
    artifact_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_inventory_count: int = Field(gt=0)
    decision_replay_path: str = Field(min_length=1)
    decision_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_replay_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
