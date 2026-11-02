"""Contracts for P5.1 temporal outcomes, models, and calibration reports."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class TemporalSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class OutcomeCause(StrEnum):
    EFFICACY = "efficacy"
    SAFETY = "safety"
    PK = "pk"
    STRATEGY = "strategy"


class OutcomeCategory(StrEnum):
    ONGOING_RIGHT_CENSORED = "ongoing_right_censored"
    COMPLETED_REGISTRY = "completed_registry_not_efficacy_success"
    EFFICACY_TERMINATION = "efficacy_termination"
    SAFETY_TERMINATION = "safety_termination"
    PK_TERMINATION = "pk_termination"
    STRATEGY_TERMINATION = "strategy_termination"
    OTHER_TERMINATION = "other_or_operational_termination"
    UNKNOWN = "unknown_not_trainable"


class LabelObservation(StrEnum):
    OBSERVED_POSITIVE = "observed_positive"
    OBSERVED_NEGATIVE = "observed_negative"
    RIGHT_CENSORED_NEGATIVE_AT_HORIZON = "right_censored_negative_at_horizon"
    EXCLUDED_UNKNOWN = "excluded_unknown"


class ModelStatus(StrEnum):
    TRAINED_VALIDATION_CALIBRATED = "trained_validation_calibrated"
    NOT_TRAINABLE_MISSING_CLASS = "not_trainable_missing_class"


class BaselineFeatures(StrictModel):
    phase: str = Field(min_length=1)
    baseline_status: str = Field(min_length=1)
    enrollment: int | None = Field(default=None, ge=0)
    enrollment_type: str | None = None
    source_class: str = Field(min_length=1)
    number_of_arms: int | None = Field(default=None, ge=0)
    has_dmc: bool | None = None
    is_fda_regulated_drug: bool | None = None
    trial_age_days: int = Field(ge=0)
    indication_groups: list[str] = Field(min_length=1)


class CauseLabel(StrictModel):
    cause: OutcomeCause
    value: bool | None
    observation: LabelObservation

    @model_validator(mode="after")
    def label_matches_observation(self) -> "CauseLabel":
        if self.observation == LabelObservation.EXCLUDED_UNKNOWN:
            if self.value is not None:
                raise ValueError("unknown labels must have null value")
        elif self.value is None:
            raise ValueError("observed/censored labels require a binary value")
        if self.observation == LabelObservation.OBSERVED_POSITIVE and self.value is not True:
            raise ValueError("positive observation requires true value")
        return self


class TemporalOutcomeRecord(StrictModel):
    id: StableId
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    split: TemporalSplit
    baseline_snapshot: str = Field(pattern=r"^\d{8}$")
    baseline_date: date
    outcome_snapshot: str = Field(pattern=r"^\d{8}$")
    outcome_date: date
    horizon_days: int = Field(gt=0)
    baseline: BaselineFeatures
    outcome_status: str = Field(min_length=1)
    why_stopped: str | None = None
    outcome_category: OutcomeCategory
    classification_rule_id: str = Field(min_length=1)
    terminal_event_observed: bool
    administratively_right_censored: bool
    event_time_basis: Literal[
        "interval_censored_between_snapshots",
        "administratively_right_censored_at_fixed_horizon",
        "registry_completion_competing_event",
        "unknown_status_excluded",
    ]
    cause_labels: list[CauseLabel] = Field(min_length=4, max_length=4)
    repeated_nct_across_temporal_splits: bool
    baseline_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def outcome_integrity(self) -> "TemporalOutcomeRecord":
        if [item.cause for item in self.cause_labels] != list(OutcomeCause):
            raise ValueError("all four cause labels must be present in canonical order")
        if self.baseline_date >= self.outcome_date:
            raise ValueError("outcome snapshot must follow baseline snapshot")
        if (self.outcome_date - self.baseline_date).days != self.horizon_days:
            raise ValueError("outcome horizon differs from snapshot dates")
        if self.outcome_category == OutcomeCategory.ONGOING_RIGHT_CENSORED:
            if not self.administratively_right_censored or self.terminal_event_observed:
                raise ValueError("ongoing records must be administratively right-censored")
            if any(item.value is not False for item in self.cause_labels):
                raise ValueError("ongoing records must be event-free at the fixed horizon")
        elif self.administratively_right_censored:
            raise ValueError("only ongoing records can be administratively right-censored")
        if self.outcome_category == OutcomeCategory.UNKNOWN:
            if any(item.value is not None for item in self.cause_labels):
                raise ValueError("unknown outcomes must be excluded from every cause label")
        elif self.outcome_category == OutcomeCategory.COMPLETED_REGISTRY:
            if any(item.value is not False for item in self.cause_labels):
                raise ValueError("registry completion cannot be labeled as cause success")
        cause_categories = {
            OutcomeCategory.EFFICACY_TERMINATION: OutcomeCause.EFFICACY,
            OutcomeCategory.SAFETY_TERMINATION: OutcomeCause.SAFETY,
            OutcomeCategory.PK_TERMINATION: OutcomeCause.PK,
            OutcomeCategory.STRATEGY_TERMINATION: OutcomeCause.STRATEGY,
        }
        expected_positive = cause_categories.get(self.outcome_category)
        if expected_positive is not None:
            positives = [item.cause for item in self.cause_labels if item.value is True]
            if positives != [expected_positive]:
                raise ValueError("cause-specific termination requires exactly one matching label")
        elif self.outcome_category == OutcomeCategory.OTHER_TERMINATION:
            if any(item.value is not False for item in self.cause_labels):
                raise ValueError("ambiguous termination cannot be assigned to a modeled cause")
        terminal_categories = {
            OutcomeCategory.COMPLETED_REGISTRY,
            OutcomeCategory.EFFICACY_TERMINATION,
            OutcomeCategory.SAFETY_TERMINATION,
            OutcomeCategory.PK_TERMINATION,
            OutcomeCategory.STRATEGY_TERMINATION,
            OutcomeCategory.OTHER_TERMINATION,
        }
        if self.terminal_event_observed != (self.outcome_category in terminal_categories):
            raise ValueError("terminal event flag does not match outcome category")
        return self


class OutcomeDatasetQuality(StrictModel):
    record_count: int = Field(ge=0)
    split_counts: dict[TemporalSplit, int]
    category_counts: dict[OutcomeCategory, int]
    cause_positive_counts_by_split: dict[TemporalSplit, dict[OutcomeCause, int]]
    right_censored_count: int = Field(ge=0)
    unknown_excluded_count: int = Field(ge=0)
    explicit_reason_classification_count: int = Field(ge=0)
    repeated_nct_count: int = Field(ge=0)
    unique_nct_count: int = Field(ge=0)
    outcome_linkage_coverage: float = Field(ge=0, le=1)
    forbidden_feature_count: int = Field(ge=0)
    post_baseline_feature_leakage_count: int = Field(ge=0)
    completed_as_efficacy_success_count: int = Field(ge=0)
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class TemporalOutcomeDataset(StrictModel):
    schema_version: Literal["5.1.0"] = "5.1.0"
    id: StableId
    created_at: datetime
    source: Literal["AACT monthly historical snapshots"] = (
        "AACT monthly historical snapshots"
    )
    indication_scope: list[str] = Field(min_length=1)
    horizon_policy: Literal["fixed_six_month_landmark_pairs"] = (
        "fixed_six_month_landmark_pairs"
    )
    split_policy: Literal[
        "strict_forward_calendar_splits_no_random_row_split"
    ] = "strict_forward_calendar_splits_no_random_row_split"
    feature_policy: Literal[
        "baseline_snapshot_structured_fields_only_no_ids_titles_or_sponsor_names"
    ] = "baseline_snapshot_structured_fields_only_no_ids_titles_or_sponsor_names"
    records: list[TemporalOutcomeRecord] = Field(min_length=1)
    quality: OutcomeDatasetQuality
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def dataset_integrity(self) -> "TemporalOutcomeDataset":
        ids = [item.id for item in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("temporal outcome record IDs must be unique")
        if self.quality.record_count != len(self.records):
            raise ValueError("outcome record count mismatch")
        if self.quality.split_counts != dict(Counter(item.split for item in self.records)):
            raise ValueError("outcome split counts mismatch")
        if self.quality.category_counts != dict(
            Counter(item.outcome_category for item in self.records)
        ):
            raise ValueError("outcome category counts mismatch")
        split_dates = {
            split: (
                {item.baseline_date for item in self.records if item.split == split},
                {item.outcome_date for item in self.records if item.split == split},
            )
            for split in TemporalSplit
        }
        if any(
            len(baselines) != 1 or len(outcomes) != 1
            for baselines, outcomes in split_dates.values()
        ):
            raise ValueError("each temporal split requires one frozen landmark pair")
        train_outcome = next(iter(split_dates[TemporalSplit.TRAIN][1]))
        validation_baseline = next(iter(split_dates[TemporalSplit.VALIDATION][0]))
        validation_outcome = next(iter(split_dates[TemporalSplit.VALIDATION][1]))
        test_baseline = next(iter(split_dates[TemporalSplit.TEST][0]))
        if not train_outcome < validation_baseline or not validation_outcome < test_baseline:
            raise ValueError("train, validation, and test landmarks must move forward in time")
        return self


class BinaryMetrics(StrictModel):
    sample_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    brier_score: float | None = Field(default=None, ge=0, le=1)
    expected_calibration_error: float | None = Field(default=None, ge=0, le=1)
    pr_auc: float | None = Field(default=None, ge=0, le=1)
    roc_auc: float | None = Field(default=None, ge=0, le=1)
    precision_at_0_5: float | None = Field(default=None, ge=0, le=1)
    recall_at_0_5: float | None = Field(default=None, ge=0, le=1)


class OutcomePrediction(StrictModel):
    record_id: StableId
    cause: OutcomeCause
    split: Literal[TemporalSplit.TEST] = TemporalSplit.TEST
    label: bool
    uncalibrated_probability: float = Field(ge=0, le=1)
    calibrated_probability: float = Field(ge=0, le=1)


class CauseModelReport(StrictModel):
    cause: OutcomeCause
    status: ModelStatus
    estimator: Literal["l2_logistic_regression", "none"]
    class_weight: Literal["balanced", "none"]
    feature_names: list[str]
    train_metrics: BinaryMetrics
    validation_metrics_uncalibrated: BinaryMetrics
    validation_metrics_calibrated_in_sample: BinaryMetrics
    test_metrics_uncalibrated: BinaryMetrics
    test_metrics_calibrated: BinaryMetrics
    calibration_method: Literal["platt_sigmoid_validation_only", "none"]
    calibration_fit_split: Literal["validation", "none"]
    test_used_for_fit_or_calibration: Literal[False] = False
    coefficients: dict[str, float]
    intercept: float | None = None
    calibrator_coefficient: float | None = None
    calibrator_intercept: float | None = None
    predictions: list[OutcomePrediction]
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def model_report_integrity(self) -> "CauseModelReport":
        trained = self.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED
        if trained != (self.estimator == "l2_logistic_regression"):
            raise ValueError("model status and estimator mismatch")
        if trained != (self.calibration_method == "platt_sigmoid_validation_only"):
            raise ValueError("trained models require validation-only Platt calibration")
        if trained and not self.predictions:
            raise ValueError("trained models require frozen test predictions")
        if not trained and (
            self.coefficients or self.intercept is not None or self.predictions
        ):
            raise ValueError("untrainable heads cannot contain fitted parameters or predictions")
        return self


class OutcomeModelQuality(StrictModel):
    head_count: int = Field(ge=0)
    trained_head_count: int = Field(ge=0)
    calibrated_head_count: int = Field(ge=0)
    untrainable_head_count: int = Field(ge=0)
    validation_only_calibration_count: int = Field(ge=0)
    test_fit_leakage_count: int = Field(ge=0)
    forbidden_feature_count: int = Field(ge=0)
    trained_on_random_split: Literal[False] = False
    all_heads_trainable: bool
    engineering_gate_passed: bool
    calibration_protocol_gate_passed: bool
    calibration_performance_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class OutcomeModelSnapshot(StrictModel):
    schema_version: Literal["5.1.0"] = "5.1.0"
    id: StableId
    created_at: datetime
    source_dataset_id: StableId
    source_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sklearn_version: str = Field(min_length=1)
    model_reports: list[CauseModelReport] = Field(min_length=4, max_length=4)
    quality: OutcomeModelQuality
    use_policy: Literal[
        "development_only_sparse_cause_specific_models_not_target_success_probability"
    ] = "development_only_sparse_cause_specific_models_not_target_success_probability"
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def model_snapshot_integrity(self) -> "OutcomeModelSnapshot":
        if [item.cause for item in self.model_reports] != list(OutcomeCause):
            raise ValueError("all four outcome heads must be present in canonical order")
        trained = sum(
            item.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED
            for item in self.model_reports
        )
        if self.quality.trained_head_count != trained:
            raise ValueError("trained head count mismatch")
        return self


class OutcomeManifest(StrictModel):
    schema_version: Literal["5.1.0"] = "5.1.0"
    dataset_id: StableId
    model_snapshot_id: StableId
    dataset_path: str = Field(min_length=1)
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_path: str = Field(min_length=1)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=1)
    record_count: int = Field(ge=0)
    trained_head_count: int = Field(ge=0)
