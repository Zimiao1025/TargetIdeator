"""Contracts for P5.6 versioned source-asserted mapping evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class AssertionHistoryQuality(StrictModel):
    release_count: int = Field(ge=2)
    release_evidence_row_counts: dict[str, int]
    release_assertion_counts: dict[str, int]
    release_mapped_nct_counts: dict[str, int]
    union_evidence_row_count: int = Field(gt=0)
    persistent_evidence_row_count: int = Field(ge=0)
    removed_evidence_row_count: int = Field(ge=0)
    added_evidence_row_count: int = Field(ge=0)
    content_changed_evidence_row_count: int = Field(ge=0)
    union_assertion_count: int = Field(gt=0)
    persistent_assertion_count: int = Field(ge=0)
    removed_assertion_count: int = Field(ge=0)
    added_assertion_count: int = Field(ge=0)
    union_mapped_nct_count: int = Field(gt=0)
    newly_recovered_nct_count: int = Field(ge=0)
    p5_5_exact_identity_candidate_nct_count: int = Field(ge=0)
    p5_5_candidate_target_assertion_recovery_count: int = Field(ge=0)
    p5_5_candidate_target_assertion_recovery_coverage: float = Field(ge=0, le=1)
    remaining_unresolved_nct_count: int = Field(ge=0)
    invalid_source_identity_row_count: int = Field(ge=0)
    source_field_provenance_coverage: float = Field(ge=0, le=1)
    name_inferred_assertion_count: Literal[0] = 0
    fuzzy_assertion_count: Literal[0] = 0
    source_assertion_used_as_temporal_model_feature_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class AssertionHistorySnapshot(StrictModel):
    schema_version: Literal["5.6.0"] = "5.6.0"
    id: StableId
    created_at: datetime
    releases: list[Literal["25.03", "25.09"]] = ["25.03", "25.09"]
    assertion_policy: Literal[
        "source_fields_only_no_name_or_target_inference"
    ] = "source_fields_only_no_name_or_target_inference"
    evidence_history_path: str = Field(min_length=1)
    evidence_history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_path: str = Field(min_length=1)
    assertion_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: AssertionHistoryQuality
    warning: str = Field(min_length=1)


class AssertionHistoryManifest(StrictModel):
    schema_version: Literal["5.6.0"] = "5.6.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    evidence_history_path: str = Field(min_length=1)
    evidence_history_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_history_record_count: int = Field(gt=0)
    assertion_path: str = Field(min_length=1)
    assertion_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assertion_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
