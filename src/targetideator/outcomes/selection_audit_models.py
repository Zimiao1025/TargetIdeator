"""Contracts for P5.9 target-validation selection audit."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class SelectionAuditQuality(StrictModel):
    unique_nct_count: int = Field(gt=0)
    input_landmark_record_count: int = Field(gt=0)
    repeated_landmark_record_count_collapsed: int = Field(ge=0)
    support_stratum_counts: dict[str, int]
    baseline_feature_count: int = Field(gt=0)
    balance_contrast_count: int = Field(gt=0)
    balance_diagnostic_record_count: int = Field(gt=0)
    material_imbalance_threshold: Literal[0.1] = 0.1
    mapped_vs_unmapped_max_abs_smd: float = Field(ge=0)
    mapped_vs_unmapped_material_imbalance_count: int = Field(ge=0)
    max_abs_smd_by_contrast: dict[str, float]
    cross_fit_fold_count: Literal[5] = 5
    mapping_selection_roc_auc: float = Field(ge=0, le=1)
    mapping_selection_log_loss: float = Field(ge=0)
    mapping_common_support_lower: float = Field(ge=0, le=1)
    mapping_common_support_upper: float = Field(ge=0, le=1)
    mapping_common_support_fraction: float = Field(ge=0, le=1)
    mapped_group_common_support_fraction: float = Field(ge=0, le=1)
    unmapped_group_common_support_fraction: float = Field(ge=0, le=1)
    stratum_one_vs_rest_roc_auc: dict[str, float]
    stratum_one_vs_rest_common_support_fraction: dict[str, float]
    outcome_field_used_as_selection_feature_count: Literal[0] = 0
    identifier_used_as_selection_feature_count: Literal[0] = 0
    post_baseline_feature_used_count: Literal[0] = 0
    outcome_comparison_count: Literal[0] = 0
    causal_adjustment_count: Literal[0] = 0
    target_outcome_estimate_count: Literal[0] = 0
    fitted_outcome_model_count: Literal[0] = 0
    selection_bias_gate_passed: Literal[False] = False
    target_validation_ready: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class SelectionAuditSnapshot(StrictModel):
    schema_version: Literal["5.9.0"] = "5.9.0"
    id: StableId
    created_at: datetime
    cohort_policy: Literal[
        "one_earliest_baseline_landmark_per_nct"
    ] = "one_earliest_baseline_landmark_per_nct"
    feature_policy: Literal[
        "pre_outcome_baseline_trial_attributes_only_no_ids_text_drug_target_or_outcome_fields"
    ] = "pre_outcome_baseline_trial_attributes_only_no_ids_text_drug_target_or_outcome_fields"
    diagnostic_policy: Literal[
        "selection_detectability_and_overlap_only_no_outcome_comparison_or_causal_reweighting"
    ] = "selection_detectability_and_overlap_only_no_outcome_comparison_or_causal_reweighting"
    cohort_path: str = Field(min_length=1)
    cohort_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    balance_path: str = Field(min_length=1)
    balance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: SelectionAuditQuality
    warning: str = Field(min_length=1)


class SelectionAuditManifest(StrictModel):
    schema_version: Literal["5.9.0"] = "5.9.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    sklearn_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    cohort_path: str = Field(min_length=1)
    cohort_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cohort_record_count: int = Field(gt=0)
    balance_path: str = Field(min_length=1)
    balance_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    balance_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
