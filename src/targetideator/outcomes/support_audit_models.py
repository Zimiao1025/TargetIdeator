"""Contracts for P5.8 corroboration-aware outcome provenance audit."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


SupportStratum = Literal[
    "unmapped_no_source_assertion",
    "mapped_all_cross_source_pairs",
    "mapped_mixed_pair_support",
    "mapped_opentargets_chembl_only",
]


class SupportAuditQuality(StrictModel):
    outcome_provenance_record_count: int = Field(gt=0)
    unique_nct_count: int = Field(gt=0)
    mapped_nct_count: int = Field(ge=0)
    unmapped_nct_count: int = Field(ge=0)
    nct_counts_by_support_stratum: dict[str, int]
    outcome_record_counts_by_support_stratum: dict[str, int]
    explicit_event_record_count: int = Field(ge=0)
    explicit_event_counts_by_support_stratum: dict[str, int]
    explicit_event_counts_by_category_and_support_stratum: dict[str, dict[str, int]]
    source_assertion_record_count: int = Field(gt=0)
    support_stratum_coverage: float = Field(ge=0, le=1)
    mapping_status_change_count: Literal[0] = 0
    outcome_interpretation_change_count: Literal[0] = 0
    causal_comparison_count: Literal[0] = 0
    target_outcome_attribution_count: Literal[0] = 0
    support_stratum_used_as_model_feature_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class SupportAuditSnapshot(StrictModel):
    schema_version: Literal["5.8.0"] = "5.8.0"
    id: StableId
    created_at: datetime
    support_policy: Literal[
        "descriptive_trial_strata_from_existing_source_assertions_only"
    ] = "descriptive_trial_strata_from_existing_source_assertions_only"
    interpretation_policy: Literal[
        "counts_and_lineage_only_no_rate_comparison_or_target_attribution"
    ] = "counts_and_lineage_only_no_rate_comparison_or_target_attribution"
    enriched_outcome_path: str = Field(min_length=1)
    enriched_outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    explicit_event_path: str = Field(min_length=1)
    explicit_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: SupportAuditQuality
    warning: str = Field(min_length=1)


class SupportAuditManifest(StrictModel):
    schema_version: Literal["5.8.0"] = "5.8.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    enriched_outcome_path: str = Field(min_length=1)
    enriched_outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    enriched_outcome_record_count: int = Field(gt=0)
    explicit_event_path: str = Field(min_length=1)
    explicit_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    explicit_event_record_count: int = Field(ge=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
