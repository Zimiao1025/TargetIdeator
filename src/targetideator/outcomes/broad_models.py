"""Contracts for the P5.2 broad temporal outcome benchmark."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel
from targetideator.outcomes.models import BinaryMetrics, ModelStatus, OutcomeCause, TemporalSplit


class BootstrapInterval(StrictModel):
    metric: str = Field(min_length=1)
    point_estimate: float
    lower_95: float
    upper_95: float
    resample_count: int = Field(gt=0)
    valid_resample_count: int = Field(gt=0)
    seed: int
    unit: Literal["nct_id"] = "nct_id"
    refit_per_resample: Literal[False] = False


class BroadBaselineEvaluation(StrictModel):
    name: Literal["train_prevalence", "phase_only_logistic", "full_structured_logistic"]
    calibrated: bool
    calibration_fit_split: Literal["validation", "none"]
    test_metrics: BinaryMetrics
    novel_nct_test_metrics: BinaryMetrics
    brier_interval: BootstrapInterval
    brier_delta_vs_prevalence_interval: BootstrapInterval | None = None


class BroadCauseReport(StrictModel):
    cause: OutcomeCause
    status: ModelStatus
    train_positive_count: int = Field(ge=0)
    validation_positive_count: int = Field(ge=0)
    test_positive_count: int = Field(ge=0)
    novel_nct_test_positive_count: int = Field(ge=0)
    feature_names: list[str]
    calibration_method: Literal["platt_sigmoid_validation_only", "none"]
    calibration_fit_split: Literal["validation", "none"]
    test_used_for_fit_or_calibration: Literal[False] = False
    evaluations: list[BroadBaselineEvaluation]
    parameters: dict[str, object]
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def report_integrity(self) -> "BroadCauseReport":
        trained = self.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED
        if trained and [item.name for item in self.evaluations] != [
            "train_prevalence",
            "phase_only_logistic",
            "full_structured_logistic",
        ]:
            raise ValueError("trained causes require all three frozen baselines")
        if not trained and (self.evaluations or self.parameters):
            raise ValueError("untrainable causes cannot contain fitted outputs")
        return self


class BroadOutcomeQuality(StrictModel):
    record_count: int = Field(gt=0)
    split_counts: dict[TemporalSplit, int]
    trainable_counts: dict[TemporalSplit, int]
    category_counts: dict[str, int]
    cause_positive_counts_by_split: dict[TemporalSplit, dict[OutcomeCause, int]]
    unique_nct_count: int = Field(gt=0)
    repeated_nct_count: int = Field(ge=0)
    missing_outcome_snapshot_count: int = Field(ge=0)
    unknown_excluded_count: int = Field(ge=0)
    right_censored_count: int = Field(ge=0)
    validation_nct_overlap_with_train: int = Field(ge=0)
    test_nct_overlap_with_prior_splits: int = Field(ge=0)
    novel_nct_test_count: int = Field(ge=0)
    forbidden_feature_count: int = Field(ge=0)
    post_baseline_feature_leakage_count: int = Field(ge=0)
    test_fit_leakage_count: int = Field(ge=0)
    trained_head_count: int = Field(ge=0)
    untrainable_head_count: int = Field(ge=0)
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class BroadOutcomeSnapshot(StrictModel):
    schema_version: Literal["5.2.0"] = "5.2.0"
    id: StableId
    created_at: datetime
    source: Literal["AACT monthly historical snapshots; all indications"] = (
        "AACT monthly historical snapshots; all indications"
    )
    split_policy: Literal["forward_calendar_landmarks_with_novel_nct_sensitivity"] = (
        "forward_calendar_landmarks_with_novel_nct_sensitivity"
    )
    feature_policy: Literal[
        "baseline_structured_fields_only_no_ids_text_sponsor_drug_or_outcome_fields"
    ] = "baseline_structured_fields_only_no_ids_text_sponsor_drug_or_outcome_fields"
    normalized_dataset_path: str = Field(min_length=1)
    normalized_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_path: str = Field(min_length=1)
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sklearn_version: str = Field(min_length=1)
    model_reports: list[BroadCauseReport] = Field(min_length=4, max_length=4)
    quality: BroadOutcomeQuality
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def canonical_heads(self) -> "BroadOutcomeSnapshot":
        if [item.cause for item in self.model_reports] != list(OutcomeCause):
            raise ValueError("all four cause reports must be present in canonical order")
        return self


class BroadOutcomeManifest(StrictModel):
    schema_version: Literal["5.2.0"] = "5.2.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    raw_checksums: dict[str, str] = Field(min_length=3)
    normalized_dataset_path: str = Field(min_length=1)
    normalized_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prediction_path: str = Field(min_length=1)
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(gt=0)
    test_prediction_count: int = Field(ge=0)
