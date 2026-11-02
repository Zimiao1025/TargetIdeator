"""Contracts for P5.4 mapping missingness and unresolved triage."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class CoverageStratum(StrictModel):
    dimension: Literal[
        "split",
        "phase",
        "source_class",
        "baseline_status",
        "fda_regulated_drug",
        "outcome_category",
        "intervention_profile",
        "name_stability",
    ]
    value: str = Field(min_length=1)
    total_record_count: int = Field(gt=0)
    mapped_record_count: int = Field(ge=0)
    unmapped_record_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    coverage_difference_from_overall: float = Field(ge=-1, le=1)
    small_cell: bool


class MappingAuditQuality(StrictModel):
    outcome_record_count: int = Field(gt=0)
    unique_nct_count: int = Field(gt=0)
    mapped_unique_nct_count: int = Field(ge=0)
    unresolved_unique_nct_count: int = Field(ge=0)
    mapped_outcome_record_count: int = Field(ge=0)
    unresolved_reason_counts: dict[str, int]
    intervention_capture_count: int = Field(gt=0)
    intervention_capture_complete_count: int = Field(ge=0)
    nct_with_intervention_coverage: float = Field(ge=0, le=1)
    repeated_nct_count: int = Field(ge=0)
    repeated_nct_stable_name_count: int = Field(ge=0)
    repeated_nct_changed_name_count: int = Field(ge=0)
    mapped_nct_exact_name_agreement_count: int = Field(ge=0)
    mapped_nct_no_exact_name_agreement_count: int = Field(ge=0)
    mapped_nct_without_therapeutic_name_count: int = Field(ge=0)
    coverage_stratum_count: int = Field(gt=0)
    material_coverage_disparity_stratum_count: int = Field(ge=0)
    automatic_mapping_count: Literal[0] = 0
    fuzzy_mapping_count: Literal[0] = 0
    mapping_candidate_used_as_evidence_count: Literal[0] = 0
    current_identity_used_as_temporal_model_feature_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class MappingAuditSnapshot(StrictModel):
    schema_version: Literal["5.4.0"] = "5.4.0"
    id: StableId
    created_at: datetime
    audit_policy: Literal[
        "descriptive_missingness_and_exact_name_triage_no_inferred_mapping"
    ] = "descriptive_missingness_and_exact_name_triage_no_inferred_mapping"
    triage_path: str = Field(min_length=1)
    triage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    strata: list[CoverageStratum] = Field(min_length=1)
    quality: MappingAuditQuality
    warning: str = Field(min_length=1)


class MappingAuditManifest(StrictModel):
    schema_version: Literal["5.4.0"] = "5.4.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=6)
    triage_path: str = Field(min_length=1)
    triage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    triage_record_count: int = Field(gt=0)
