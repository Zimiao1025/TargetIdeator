"""Contracts for P5.3 auditable trial→drug→target identity enrichment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class MappingCoverage(StrictModel):
    total_count: int = Field(ge=0)
    mapped_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)


class IdentityQuality(StrictModel):
    broad_unique_nct_count: int = Field(gt=0)
    source_evidence_row_count: int = Field(gt=0)
    valid_source_evidence_row_count: int = Field(ge=0)
    invalid_source_evidence_row_count: int = Field(ge=0)
    drug_dictionary_row_count: int = Field(ge=0)
    drug_dictionary_missing_id_count: int = Field(ge=0)
    unique_trial_drug_target_mapping_count: int = Field(ge=0)
    mapped_unique_nct_count: int = Field(ge=0)
    unmapped_unique_nct_count: int = Field(ge=0)
    unique_nct_mapping_coverage: float = Field(ge=0, le=1)
    multi_drug_trial_count: int = Field(ge=0)
    multi_target_trial_count: int = Field(ge=0)
    outcome_provenance_record_count: int = Field(ge=0)
    outcome_record_mapping_coverage: MappingCoverage
    mapping_coverage_by_outcome_category: dict[str, MappingCoverage]
    explicit_cause_event_mapping_coverage: MappingCoverage
    aact_name_crosscheck_available_mapping_count: int = Field(ge=0)
    aact_name_exact_agreement_count: int = Field(ge=0)
    aact_name_no_exact_agreement_count: int = Field(ge=0)
    aact_name_source_unavailable_mapping_count: int = Field(ge=0)
    aact_name_crosscheck_unavailable_mapping_count: int = Field(ge=0)
    classification_trace_coverage: float = Field(ge=0, le=1)
    source_complete_for_query: bool
    current_identity_used_as_temporal_model_feature_count: Literal[0] = 0
    fuzzy_auto_mapping_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class IdentitySnapshot(StrictModel):
    schema_version: Literal["5.3.0"] = "5.3.0"
    id: StableId
    created_at: datetime
    mapping_source: Literal["Open Targets 25.09 archived ChEMBL evidence"] = (
        "Open Targets 25.09 archived ChEMBL evidence"
    )
    mapping_policy: Literal[
        "source_asserted_trial_drug_target_only_no_fuzzy_inference"
    ] = "source_asserted_trial_drug_target_only_no_fuzzy_inference"
    name_crosscheck_policy: Literal[
        "AACT_20230301_exact_normalized_names_and_aliases_audit_only"
    ] = "AACT_20230301_exact_normalized_names_and_aliases_audit_only"
    temporal_use_policy: Literal[
        "identity_and_provenance_enrichment_only_not_outcome_model_feature"
    ] = "identity_and_provenance_enrichment_only_not_outcome_model_feature"
    mapping_path: str = Field(min_length=1)
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_path: str = Field(min_length=1)
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unresolved_path: str = Field(min_length=1)
    unresolved_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: IdentityQuality
    warning: str = Field(min_length=1)


class IdentityManifest(StrictModel):
    schema_version: Literal["5.3.0"] = "5.3.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    mapping_path: str = Field(min_length=1)
    mapping_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_path: str = Field(min_length=1)
    provenance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unresolved_path: str = Field(min_length=1)
    unresolved_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_count: int = Field(ge=0)
    provenance_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
