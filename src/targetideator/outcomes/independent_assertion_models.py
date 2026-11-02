"""Contracts for P5.7 independent drug-target corroboration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class IndependentAssertionQuality(StrictModel):
    source_name: Literal["DrugCentral"] = "DrugCentral"
    source_release: Literal["2027"] = "2027"
    source_release_date: Literal["2026-09-25"] = "2026-09-25"
    source_admission_passed: bool
    raw_interaction_row_count: int = Field(gt=0)
    human_interaction_row_count: int = Field(ge=0)
    independently_sourced_human_row_count: int = Field(ge=0)
    exact_crosswalk_evidence_row_count: int = Field(ge=0)
    crosswalk_rejection_reason_counts: dict[str, int]
    independent_drug_target_pair_count: int = Field(ge=0)
    independent_drug_count: int = Field(ge=0)
    independent_target_count: int = Field(ge=0)
    current_source_assertion_count: int = Field(gt=0)
    current_source_pair_count: int = Field(gt=0)
    cross_source_supported_assertion_count: int = Field(ge=0)
    single_source_assertion_count: int = Field(ge=0)
    cross_source_supported_pair_count: int = Field(ge=0)
    single_source_pair_count: int = Field(ge=0)
    mapped_nct_count: int = Field(gt=0)
    cross_source_supported_nct_count: int = Field(ge=0)
    all_assertions_cross_source_nct_count: int = Field(ge=0)
    mixed_support_nct_count: int = Field(ge=0)
    single_source_only_nct_count: int = Field(ge=0)
    p5_5_candidate_promoted_to_trial_target_count: Literal[0] = 0
    newly_mapped_nct_count: Literal[0] = 0
    remaining_unresolved_nct_count: int = Field(ge=0)
    name_matching_used_count: Literal[0] = 0
    ambiguous_identity_admitted_count: Literal[0] = 0
    independent_source_used_as_temporal_model_feature_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class IndependentAssertionSnapshot(StrictModel):
    schema_version: Literal["5.7.0"] = "5.7.0"
    id: StableId
    created_at: datetime
    independent_pair_path: str = Field(min_length=1)
    independent_pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corroboration_path: str = Field(min_length=1)
    corroboration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: IndependentAssertionQuality
    warning: str = Field(min_length=1)


class IndependentAssertionManifest(StrictModel):
    schema_version: Literal["5.7.0"] = "5.7.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    independent_pair_path: str = Field(min_length=1)
    independent_pair_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    independent_pair_record_count: int = Field(ge=0)
    corroboration_path: str = Field(min_length=1)
    corroboration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corroboration_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
