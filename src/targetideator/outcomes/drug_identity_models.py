"""Contracts for P5.5 versioned drug-identity family resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class DrugIdentityQuality(StrictModel):
    full_dictionary_row_count: int = Field(gt=0)
    normalized_dictionary_name_count: int = Field(gt=0)
    molecule_family_count: int = Field(gt=0)
    parent_link_count: int = Field(ge=0)
    dangling_parent_link_count: int = Field(ge=0)
    hierarchy_cycle_count: int = Field(ge=0)
    unresolved_trial_count: int = Field(gt=0)
    therapeutic_unresolved_trial_count: int = Field(ge=0)
    resolution_status_counts: dict[str, int]
    exact_name_matched_trial_count: int = Field(ge=0)
    exact_name_match_coverage_of_therapeutic_unresolved: float = Field(ge=0, le=1)
    single_family_nonambiguous_trial_count: int = Field(ge=0)
    multi_family_nonambiguous_trial_count: int = Field(ge=0)
    ambiguous_name_trial_count: int = Field(ge=0)
    target_assertion_gap_count: int = Field(ge=0)
    automatic_trial_drug_mapping_count: Literal[0] = 0
    automatic_trial_target_mapping_count: Literal[0] = 0
    fuzzy_matching_count: Literal[0] = 0
    identity_candidate_used_as_target_evidence_count: Literal[0] = 0
    current_identity_used_as_temporal_model_feature_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class DrugIdentitySnapshot(StrictModel):
    schema_version: Literal["5.5.0"] = "5.5.0"
    id: StableId
    created_at: datetime
    release_version: Literal["25.09"] = "25.09"
    resolution_policy: Literal[
        "exact_normalized_name_plus_source_parent_hierarchy_no_target_inference"
    ] = "exact_normalized_name_plus_source_parent_hierarchy_no_target_inference"
    resolution_path: str = Field(min_length=1)
    resolution_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: DrugIdentityQuality
    warning: str = Field(min_length=1)


class DrugIdentityManifest(StrictModel):
    schema_version: Literal["5.5.0"] = "5.5.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    resolution_path: str = Field(min_length=1)
    resolution_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution_record_count: int = Field(gt=0)
