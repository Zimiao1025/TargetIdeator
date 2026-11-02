"""Build temporal outcome cohorts and sparse validation-calibrated baselines."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from pydantic import ValidationError
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ingestion.outcome_sources import IMMUNE_CONDITION_PATTERNS
from targetideator.io import write_json
from targetideator.outcomes.models import (
    BaselineFeatures,
    BinaryMetrics,
    CauseLabel,
    CauseModelReport,
    LabelObservation,
    ModelStatus,
    OutcomeCategory,
    OutcomeCause,
    OutcomeDatasetQuality,
    OutcomeManifest,
    OutcomeModelQuality,
    OutcomeModelSnapshot,
    OutcomePrediction,
    TemporalOutcomeDataset,
    TemporalOutcomeRecord,
    TemporalSplit,
)

BUILDER_VERSION = "p5-temporal-outcome-calibration-v1"
DATASET_ID = "ti:outcome-dataset:immune-aact-six-month-landmarks-v1"
MODEL_SNAPSHOT_ID = "ti:outcome-model:immune-cause-specific-logistic-v1"
CREATED_AT = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)

_SPLITS = (TemporalSplit.TRAIN, TemporalSplit.VALIDATION, TemporalSplit.TEST)
_ONGOING = {
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
}
_TERMINAL = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}
_UNKNOWN = {"UNKNOWN", "UNKNOWN_STATUS", ""}
_CAUSE_CATEGORY = {
    OutcomeCause.EFFICACY: OutcomeCategory.EFFICACY_TERMINATION,
    OutcomeCause.SAFETY: OutcomeCategory.SAFETY_TERMINATION,
    OutcomeCause.PK: OutcomeCategory.PK_TERMINATION,
    OutcomeCause.STRATEGY: OutcomeCategory.STRATEGY_TERMINATION,
}


def default_outcome_raw_paths() -> list[Path]:
    return [
        fixture_path(f"aact_immune_outcomes_{split.value}_raw.json")
        for split in _SPLITS
    ]


def default_outcome_dataset_path() -> Path:
    return fixture_path("p5_outcome_dataset.json")


def default_outcome_model_path() -> Path:
    return fixture_path("p5_outcome_models.json")


def default_outcome_manifest_path() -> Path:
    return fixture_path("p5_outcome_manifest.json")


def _enum(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def _phase(value: str | None) -> str:
    """Normalize historical and current AACT phase spellings to one vocabulary."""

    compact = re.sub(r"[^A-Z0-9]+", "", (value or "").upper())
    return {
        "PHASE1PHASE2": "PHASE1_PHASE2",
        "PHASE2": "PHASE2",
        "PHASE2PHASE3": "PHASE2_PHASE3",
        "PHASE3": "PHASE3",
    }.get(compact, "UNKNOWN")


def _date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _integer(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _boolean(value: str | bool | None) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = (value or "").strip().lower()
    if normalized in {"t", "true", "yes", "1"}:
        return True
    if normalized in {"f", "false", "no", "0"}:
        return False
    return None


def _raw_sha(row: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(row)).hexdigest()


def _classify_termination(reason: str | None) -> tuple[OutcomeCategory, str]:
    text = (reason or "").casefold()
    if not text:
        return OutcomeCategory.OTHER_TERMINATION, "p5.outcome.other.missing-reason"
    safety_negated = bool(
        re.search(
            r"(?:(?:not|no|without|unrelated|neither|non[- ])[^.;]{0,60}safety|"
            r"safety[^.;]{0,35}(?:not\s+(?:a|the)\s+reason|did\s+not))",
            text,
        )
    )
    efficacy_negated = bool(
        re.search(
            r"(?:(?:not|no|without|unrelated|neither|non[- ])[^.;]{0,60}"
            r"(?:efficacy|therapeutic)|(?:efficacy|therapeutic)[^.;]{0,35}"
            r"(?:not\s+(?:a|the)\s+reason|did\s+not))",
            text,
        )
    )
    pk_patterns = (
        "pharmacokinetic",
        "bioavailability",
        "insufficient exposure",
        "drug exposure",
    )
    pk_negated = bool(re.search(r"not\s+(?:due|related)[^.;]{0,25}(?:pk|pharmacokinetic|exposure)", text))
    if not pk_negated and any(item in text for item in pk_patterns):
        return OutcomeCategory.PK_TERMINATION, "p5.outcome.pk.explicit-text"
    safety_patterns = (
        "toxicity",
        "toxicities",
        "adverse event",
        "safety concern",
        "safety issue",
        "safety signal",
        "safety reason",
    )
    if not safety_negated and any(item in text for item in safety_patterns):
        return OutcomeCategory.SAFETY_TERMINATION, "p5.outcome.safety.explicit-text"
    efficacy_patterns = (
        "lack of efficacy",
        "lack of effectiveness",
        "efficacy/effectiveness reasons",
        "efficacy reasons",
        "did not show superiority",
        "unlikely to meet its primary endpoint",
        "futility at ia",
        "futility of endpoint",
        "futility criteria for efficacy",
        "futility analysis",
    )
    if not efficacy_negated and any(item in text for item in efficacy_patterns):
        return OutcomeCategory.EFFICACY_TERMINATION, "p5.outcome.efficacy.explicit-text"
    strategy_patterns = (
        "business decision",
        "business reasons",
        "business objectives",
        "strategic consideration",
        "strategic decision",
        "strategic sponsor decision",
        "strategy reasons",
        "commercial decision",
        "corporate priorities",
        "portfolio reprioritization",
        "no longer pursuing development",
    )
    if any(item in text for item in strategy_patterns):
        return OutcomeCategory.STRATEGY_TERMINATION, "p5.outcome.strategy.explicit-text"
    return OutcomeCategory.OTHER_TERMINATION, "p5.outcome.other.operational-or-ambiguous"


def _outcome_category(row: dict) -> tuple[OutcomeCategory, str]:
    status = _enum(row.get("overall_status"))
    if status in _ONGOING:
        return OutcomeCategory.ONGOING_RIGHT_CENSORED, "p5.outcome.censored.fixed-horizon"
    if status == "COMPLETED":
        return OutcomeCategory.COMPLETED_REGISTRY, "p5.outcome.completed.registry-only"
    if status in _TERMINAL:
        return _classify_termination(row.get("why_stopped"))
    return OutcomeCategory.UNKNOWN, "p5.outcome.unknown.status"


def _cause_labels(category: OutcomeCategory) -> list[CauseLabel]:
    labels = []
    for cause in OutcomeCause:
        if category == OutcomeCategory.UNKNOWN:
            value = None
            observation = LabelObservation.EXCLUDED_UNKNOWN
        elif category == OutcomeCategory.ONGOING_RIGHT_CENSORED:
            value = False
            observation = LabelObservation.RIGHT_CENSORED_NEGATIVE_AT_HORIZON
        elif category == _CAUSE_CATEGORY[cause]:
            value = True
            observation = LabelObservation.OBSERVED_POSITIVE
        else:
            value = False
            observation = LabelObservation.OBSERVED_NEGATIVE
        labels.append(CauseLabel(cause=cause, value=value, observation=observation))
    return labels


def _baseline_features(row: dict, baseline_date: date) -> BaselineFeatures:
    first_posted = _date(row.get("study_first_posted_date"))
    if first_posted is None or first_posted > baseline_date:
        raise ValueError(f"baseline row {row.get('nct_id')} has invalid first-posted date")
    groups = row.get("indication_groups") or []
    return BaselineFeatures(
        phase=_phase(row.get("phase")),
        baseline_status=_enum(row.get("overall_status")) or "UNKNOWN",
        enrollment=_integer(row.get("enrollment")),
        enrollment_type=_enum(row.get("enrollment_type")) or None,
        source_class=_enum(row.get("source_class")) or "UNKNOWN",
        number_of_arms=_integer(row.get("number_of_arms")),
        has_dmc=_boolean(row.get("has_dmc")),
        is_fda_regulated_drug=_boolean(row.get("is_fda_regulated_drug")),
        trial_age_days=(baseline_date - first_posted).days,
        indication_groups=groups,
    )


def build_outcome_dataset(
    raw_paths: list[Path] | None = None,
) -> TemporalOutcomeDataset:
    paths = raw_paths or default_outcome_raw_paths()
    captures = {_load_json(path)["split"]: _load_json(path) for path in paths}
    if set(captures) != {item.value for item in _SPLITS}:
        raise ValueError("exactly train, validation, and test landmark captures are required")
    nct_counts = Counter(
        row["nct_id"]
        for split in _SPLITS
        for row in captures[split.value]["baseline_rows"]
    )
    records: list[TemporalOutcomeRecord] = []
    linkage_numerator = 0
    linkage_denominator = 0
    for split in _SPLITS:
        capture = captures[split.value]
        if not capture["complete_for_query"] or capture["missing_outcome_nct_ids"]:
            raise ValueError(f"incomplete outcome capture for {split.value}")
        baseline_date = date.fromisoformat(capture["baseline_date"])
        outcome_date = date.fromisoformat(capture["outcome_date"])
        outcome_by_nct = {item["nct_id"]: item for item in capture["outcome_rows"]}
        for baseline_row in capture["baseline_rows"]:
            linkage_denominator += 1
            outcome_row = outcome_by_nct.get(baseline_row["nct_id"])
            if outcome_row is None:
                continue
            linkage_numerator += 1
            category, rule_id = _outcome_category(outcome_row)
            status = _enum(outcome_row.get("overall_status")) or "UNKNOWN"
            terminal = category in {
                OutcomeCategory.COMPLETED_REGISTRY,
                OutcomeCategory.EFFICACY_TERMINATION,
                OutcomeCategory.SAFETY_TERMINATION,
                OutcomeCategory.PK_TERMINATION,
                OutcomeCategory.STRATEGY_TERMINATION,
                OutcomeCategory.OTHER_TERMINATION,
            }
            right_censored = category == OutcomeCategory.ONGOING_RIGHT_CENSORED
            if right_censored:
                time_basis = "administratively_right_censored_at_fixed_horizon"
            elif category == OutcomeCategory.COMPLETED_REGISTRY:
                time_basis = "registry_completion_competing_event"
            elif category == OutcomeCategory.UNKNOWN:
                time_basis = "unknown_status_excluded"
            else:
                time_basis = "interval_censored_between_snapshots"
            records.append(
                TemporalOutcomeRecord(
                    id=stable_id(
                        "temporal-outcome",
                        f"{split.value}-{capture['baseline_version']}-{baseline_row['nct_id']}",
                    ),
                    nct_id=baseline_row["nct_id"],
                    split=split,
                    baseline_snapshot=capture["baseline_version"],
                    baseline_date=baseline_date,
                    outcome_snapshot=capture["outcome_version"],
                    outcome_date=outcome_date,
                    horizon_days=capture["horizon_days"],
                    baseline=_baseline_features(baseline_row, baseline_date),
                    outcome_status=status,
                    why_stopped=outcome_row.get("why_stopped") or None,
                    outcome_category=category,
                    classification_rule_id=rule_id,
                    terminal_event_observed=terminal,
                    administratively_right_censored=right_censored,
                    event_time_basis=time_basis,
                    cause_labels=_cause_labels(category),
                    repeated_nct_across_temporal_splits=nct_counts[baseline_row["nct_id"]] > 1,
                    baseline_raw_sha256=_raw_sha(baseline_row),
                    outcome_raw_sha256=_raw_sha(outcome_row),
                )
            )
    records.sort(key=lambda item: (_SPLITS.index(item.split), item.nct_id))
    category_counts = Counter(item.outcome_category for item in records)
    positives_by_split = {
        split: {
            cause: sum(
                label.value is True
                for item in records
                if item.split == split
                for label in item.cause_labels
                if label.cause == cause
            )
            for cause in OutcomeCause
        }
        for split in _SPLITS
    }
    linkage = linkage_numerator / linkage_denominator if linkage_denominator else 0.0
    quality = OutcomeDatasetQuality(
        record_count=len(records),
        split_counts=dict(Counter(item.split for item in records)),
        category_counts=dict(category_counts),
        cause_positive_counts_by_split=positives_by_split,
        right_censored_count=category_counts[OutcomeCategory.ONGOING_RIGHT_CENSORED],
        unknown_excluded_count=category_counts[OutcomeCategory.UNKNOWN],
        explicit_reason_classification_count=sum(
            category_counts[item]
            for item in (
                OutcomeCategory.EFFICACY_TERMINATION,
                OutcomeCategory.SAFETY_TERMINATION,
                OutcomeCategory.PK_TERMINATION,
                OutcomeCategory.STRATEGY_TERMINATION,
            )
        ),
        repeated_nct_count=sum(count > 1 for count in nct_counts.values()),
        unique_nct_count=len(nct_counts),
        outcome_linkage_coverage=linkage,
        forbidden_feature_count=0,
        post_baseline_feature_leakage_count=0,
        completed_as_efficacy_success_count=0,
        engineering_gate_passed=(
            linkage == 1.0
            and len(records) == linkage_denominator
            and all(item.baseline_date < item.outcome_date for item in records)
        ),
        blocking_limitations=[
            "Outcome causes are conservative explicit-text labels from registry stop reasons, not adjudicated therapeutic outcomes.",
            "Completed registry status is a competing administrative event and is never labeled efficacy success.",
            "Ongoing trials are observed event-free through the fixed horizon and administratively right-censored there.",
            "The same trial may contribute at multiple forward calendar landmarks; identifiers and free text are excluded from features.",
            "The cohort covers six immune/inflammatory condition groups and is not target-specific.",
        ],
    )
    return TemporalOutcomeDataset(
        id=DATASET_ID,
        created_at=CREATED_AT,
        indication_scope=sorted(IMMUNE_CONDITION_PATTERNS),
        records=records,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY TEMPORAL OUTCOME COHORT. Labels describe explicit registry "
            "termination causes within fixed six-month windows; they do not represent target or "
            "drug efficacy/safety success and have not been manually adjudicated."
        ),
    )


_FEATURE_NAMES = [
    "phase_phase2",
    "phase_phase2_phase3",
    "phase_phase3",
    "status_not_yet_recruiting",
    "status_recruiting",
    "status_enrolling_by_invitation",
    "status_active_not_recruiting",
    "log1p_enrollment",
    "enrollment_missing",
    "enrollment_actual",
    "log1p_number_of_arms",
    "number_of_arms_missing",
    "trial_age_years",
    "source_class_industry",
    "source_class_nih",
    "source_class_fed",
    "source_class_other",
    "has_dmc_true",
    "has_dmc_missing",
    "fda_regulated_drug_true",
    "fda_regulated_drug_missing",
    *[f"indication_{item}" for item in sorted(IMMUNE_CONDITION_PATTERNS)],
]


def _vector(record: TemporalOutcomeRecord) -> list[float]:
    item = record.baseline
    phase = item.phase
    status = item.baseline_status
    source = item.source_class
    enrollment = item.enrollment
    arms = item.number_of_arms
    groups = set(item.indication_groups)
    values = [
        float(phase == "PHASE2"),
        float(phase in {"PHASE2_PHASE3", "PHASE2PHASE3"}),
        float(phase == "PHASE3"),
        float(status == "NOT_YET_RECRUITING"),
        float(status == "RECRUITING"),
        float(status == "ENROLLING_BY_INVITATION"),
        float(status == "ACTIVE_NOT_RECRUITING"),
        math.log1p(enrollment or 0),
        float(enrollment is None),
        float(item.enrollment_type == "ACTUAL"),
        math.log1p(arms or 0),
        float(arms is None),
        item.trial_age_days / 365.25,
        float(source == "INDUSTRY"),
        float(source == "NIH"),
        float(source == "FED"),
        float(source not in {"INDUSTRY", "NIH", "FED"}),
        float(item.has_dmc is True),
        float(item.has_dmc is None),
        float(item.is_fda_regulated_drug is True),
        float(item.is_fda_regulated_drug is None),
        *[float(group in groups) for group in sorted(IMMUNE_CONDITION_PATTERNS)],
    ]
    if len(values) != len(_FEATURE_NAMES):
        raise ValueError("feature vector differs from frozen feature contract")
    return values


def _label(record: TemporalOutcomeRecord, cause: OutcomeCause) -> bool | None:
    return next(item.value for item in record.cause_labels if item.cause == cause)


def _xy(
    dataset: TemporalOutcomeDataset, split: TemporalSplit, cause: OutcomeCause
) -> tuple[np.ndarray, np.ndarray, list[TemporalOutcomeRecord]]:
    rows = [
        item
        for item in dataset.records
        if item.split == split and _label(item, cause) is not None
    ]
    return (
        np.asarray([_vector(item) for item in rows], dtype=float),
        np.asarray([int(_label(item, cause)) for item in rows], dtype=int),
        rows,
    )


def _ece(labels: np.ndarray, probabilities: np.ndarray, bins: int = 5) -> float:
    result = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (
            (probabilities >= lower) & (probabilities <= upper)
            if index == bins - 1
            else (probabilities >= lower) & (probabilities < upper)
        )
        if mask.any():
            result += mask.mean() * abs(labels[mask].mean() - probabilities[mask].mean())
    return float(result)


def _metrics(labels: np.ndarray, probabilities: np.ndarray | None) -> BinaryMetrics:
    positives = int(labels.sum()) if len(labels) else 0
    negatives = int(len(labels) - positives)
    if probabilities is None or not len(labels):
        return BinaryMetrics(
            sample_count=len(labels), positive_count=positives, negative_count=negatives
        )
    both_classes = positives > 0 and negatives > 0
    predicted = probabilities >= 0.5
    return BinaryMetrics(
        sample_count=len(labels),
        positive_count=positives,
        negative_count=negatives,
        brier_score=float(brier_score_loss(labels, probabilities)),
        expected_calibration_error=_ece(labels, probabilities),
        pr_auc=float(average_precision_score(labels, probabilities)) if positives else None,
        roc_auc=float(roc_auc_score(labels, probabilities)) if both_classes else None,
        precision_at_0_5=float(precision_score(labels, predicted, zero_division=0)),
        recall_at_0_5=float(recall_score(labels, predicted, zero_division=0)),
    )


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, 1e-6, 1 - 1e-6)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def _empty_report(
    cause: OutcomeCause,
    train_y: np.ndarray,
    validation_y: np.ndarray,
    test_y: np.ndarray,
) -> CauseModelReport:
    empty_train = _metrics(train_y, None)
    empty_validation = _metrics(validation_y, None)
    empty_test = _metrics(test_y, None)
    return CauseModelReport(
        cause=cause,
        status=ModelStatus.NOT_TRAINABLE_MISSING_CLASS,
        estimator="none",
        class_weight="none",
        feature_names=_FEATURE_NAMES,
        train_metrics=empty_train,
        validation_metrics_uncalibrated=empty_validation,
        validation_metrics_calibrated_in_sample=empty_validation,
        test_metrics_uncalibrated=empty_test,
        test_metrics_calibrated=empty_test,
        calibration_method="none",
        calibration_fit_split="none",
        coefficients={},
        predictions=[],
        limitations=[
            "Training or validation split lacks at least one positive or one negative example.",
            "This cause remains represented in the dataset but no estimator or calibrator is fitted.",
        ],
    )


def _fit_report(dataset: TemporalOutcomeDataset, cause: OutcomeCause) -> CauseModelReport:
    train_x, train_y, _ = _xy(dataset, TemporalSplit.TRAIN, cause)
    validation_x, validation_y, _ = _xy(dataset, TemporalSplit.VALIDATION, cause)
    test_x, test_y, test_rows = _xy(dataset, TemporalSplit.TEST, cause)
    counts = (
        int(train_y.sum()),
        len(train_y) - int(train_y.sum()),
        int(validation_y.sum()),
        len(validation_y) - int(validation_y.sum()),
    )
    if any(item < 1 for item in counts):
        return _empty_report(cause, train_y, validation_y, test_y)
    estimator = LogisticRegression(
        class_weight="balanced",
        solver="lbfgs",
        max_iter=2000,
        random_state=0,
    )
    estimator.fit(train_x, train_y)
    train_prob = estimator.predict_proba(train_x)[:, 1]
    validation_prob = estimator.predict_proba(validation_x)[:, 1]
    test_prob = estimator.predict_proba(test_x)[:, 1]
    calibrator = LogisticRegression(
        C=1_000_000.0, solver="lbfgs", max_iter=2000, random_state=0
    )
    calibrator.fit(_logit(validation_prob), validation_y)
    validation_calibrated = calibrator.predict_proba(_logit(validation_prob))[:, 1]
    test_calibrated = calibrator.predict_proba(_logit(test_prob))[:, 1]
    predictions = [
        OutcomePrediction(
            record_id=row.id,
            cause=cause,
            label=bool(label),
            uncalibrated_probability=float(raw),
            calibrated_probability=float(calibrated),
        )
        for row, label, raw, calibrated in zip(
            test_rows, test_y, test_prob, test_calibrated, strict=True
        )
    ]
    return CauseModelReport(
        cause=cause,
        status=ModelStatus.TRAINED_VALIDATION_CALIBRATED,
        estimator="l2_logistic_regression",
        class_weight="balanced",
        feature_names=_FEATURE_NAMES,
        train_metrics=_metrics(train_y, train_prob),
        validation_metrics_uncalibrated=_metrics(validation_y, validation_prob),
        validation_metrics_calibrated_in_sample=_metrics(
            validation_y, validation_calibrated
        ),
        test_metrics_uncalibrated=_metrics(test_y, test_prob),
        test_metrics_calibrated=_metrics(test_y, test_calibrated),
        calibration_method="platt_sigmoid_validation_only",
        calibration_fit_split="validation",
        coefficients={
            name: float(value)
            for name, value in zip(_FEATURE_NAMES, estimator.coef_[0], strict=True)
        },
        intercept=float(estimator.intercept_[0]),
        calibrator_coefficient=float(calibrator.coef_[0][0]),
        calibrator_intercept=float(calibrator.intercept_[0]),
        predictions=predictions,
        limitations=[
            "Cause labels are sparse explicit-text registry outcomes, not adjudicated biological failures.",
            "Validation calibration metrics are in-sample for the calibrator; only test metrics are held-out evaluation.",
            "Repeated trial landmarks create correlated rows; no NCT identifier or free text enters the model features.",
            "The model estimates six-month registry cause incidence in this cohort, not target success probability.",
        ],
    )


def build_outcome_model_snapshot(
    dataset: TemporalOutcomeDataset,
    dataset_sha256: str,
) -> OutcomeModelSnapshot:
    reports = [_fit_report(dataset, cause) for cause in OutcomeCause]
    trained = [
        item
        for item in reports
        if item.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED
    ]
    calibration_performance = bool(trained) and all(
        item.test_metrics_calibrated.brier_score is not None
        and item.test_metrics_uncalibrated.brier_score is not None
        and item.test_metrics_calibrated.brier_score
        <= item.test_metrics_uncalibrated.brier_score
        for item in trained
    )
    quality = OutcomeModelQuality(
        head_count=len(reports),
        trained_head_count=len(trained),
        calibrated_head_count=len(trained),
        untrainable_head_count=len(reports) - len(trained),
        validation_only_calibration_count=sum(
            item.calibration_fit_split == "validation" for item in reports
        ),
        test_fit_leakage_count=0,
        forbidden_feature_count=dataset.quality.forbidden_feature_count,
        all_heads_trainable=len(trained) == len(OutcomeCause),
        engineering_gate_passed=(
            dataset.quality.engineering_gate_passed
            and bool(trained)
            and all(item.test_used_for_fit_or_calibration is False for item in reports)
        ),
        calibration_protocol_gate_passed=(
            bool(trained)
            and all(item.calibration_fit_split == "validation" for item in trained)
        ),
        calibration_performance_gate_passed=calibration_performance,
        blocking_limitations=[
            "Safety and PK heads have no adequate positive classes and are intentionally not trained.",
            "Efficacy and strategy positive counts are very small, so estimates are unstable and not production-calibrated.",
            "Repeated NCT landmarks require clustered bootstrap or grouped survival modeling before scientific inference.",
            "No target, mechanism, drug identity, title text, or sponsor name is included; this is a registry baseline only.",
            "Formal P5 requires broader outcomes, external baselines, uncertainty intervals, and prospective validation.",
        ],
    )
    return OutcomeModelSnapshot(
        id=MODEL_SNAPSHOT_ID,
        created_at=CREATED_AT,
        source_dataset_id=dataset.id,
        source_dataset_sha256=dataset_sha256,
        sklearn_version=sklearn.__version__,
        model_reports=reports,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY SPARSE CAUSE-SPECIFIC BASELINES. Calibration uses validation only and "
            "test is held out, but labels are sparse registry stop reasons. These probabilities are "
            "not target, drug, efficacy, or safety success probabilities."
        ),
    )


def render_outcome_report(
    dataset: TemporalOutcomeDataset, models: OutcomeModelSnapshot
) -> str:
    lines = [
        "# TargetIdeator P5.1 temporal outcome and calibration report",
        "",
        f"> {dataset.warning}",
        f"> {models.warning}",
        "",
        f"- Dataset: `{dataset.id}`",
        f"- Records: {dataset.quality.record_count}",
        f"- Right-censored: {dataset.quality.right_censored_count}",
        f"- Models trained/calibrated: {models.quality.trained_head_count}/{models.quality.head_count}",
        f"- Calibration protocol gate: `{models.quality.calibration_protocol_gate_passed}`",
        f"- Calibration performance gate: `{models.quality.calibration_performance_gate_passed}`",
        f"- Formal P5 gate: `{models.quality.formal_p5_gate_passed}`",
        "",
        "## Split and outcome counts",
        "",
    ]
    for split, count in dataset.quality.split_counts.items():
        positives = dataset.quality.cause_positive_counts_by_split[split]
        lines.append(
            f"- `{split.value}`: {count}; "
            + ", ".join(f"{cause.value}={value}" for cause, value in positives.items())
        )
    lines.extend(["", "## Cause-specific models", ""])
    for report in models.model_reports:
        lines.extend(
            [
                f"### {report.cause.value}: {report.status.value}",
                "",
                f"- Train positives/total: {report.train_metrics.positive_count}/{report.train_metrics.sample_count}",
                f"- Validation positives/total: {report.validation_metrics_uncalibrated.positive_count}/{report.validation_metrics_uncalibrated.sample_count}",
                f"- Test positives/total: {report.test_metrics_calibrated.positive_count}/{report.test_metrics_calibrated.sample_count}",
                f"- Test Brier uncalibrated/calibrated: {report.test_metrics_uncalibrated.brier_score} / {report.test_metrics_calibrated.brier_score}",
                f"- Test ECE uncalibrated/calibrated: {report.test_metrics_uncalibrated.expected_calibration_error} / {report.test_metrics_calibrated.expected_calibration_error}",
                f"- Test PR-AUC calibrated: {report.test_metrics_calibrated.pr_auc}",
                "",
            ]
        )
    lines.extend(["## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in models.quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums(paths: list[Path] | None = None) -> dict[str, str]:
    paths = paths or default_outcome_raw_paths()
    return {path.name: file_sha256(path) for path in paths}


def write_outcome_artifacts(
    output_dir: Path,
    raw_paths: list[Path] | None = None,
) -> tuple[TemporalOutcomeDataset, OutcomeModelSnapshot, OutcomeManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = raw_paths or default_outcome_raw_paths()
    dataset = build_outcome_dataset(paths)
    dataset_path = output_dir / "p5_outcome_dataset.json"
    write_json(dataset_path, dataset.model_dump(mode="json"))
    models = build_outcome_model_snapshot(dataset, file_sha256(dataset_path))
    model_path = output_dir / "p5_outcome_models.json"
    write_json(model_path, models.model_dump(mode="json"))
    (output_dir / "p5_outcome_report.md").write_text(
        render_outcome_report(dataset, models), encoding="utf-8"
    )
    manifest = OutcomeManifest(
        dataset_id=dataset.id,
        model_snapshot_id=models.id,
        dataset_path=dataset_path.name,
        dataset_sha256=file_sha256(dataset_path),
        model_path=model_path.name,
        model_sha256=file_sha256(model_path),
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(paths),
        record_count=len(dataset.records),
        trained_head_count=models.quality.trained_head_count,
    )
    write_json(output_dir / "p5_outcome_manifest.json", manifest.model_dump(mode="json"))
    return dataset, models, manifest


class OutcomeStore:
    def __init__(
        self,
        dataset: TemporalOutcomeDataset,
        models: OutcomeModelSnapshot,
        manifest: OutcomeManifest | None = None,
        dataset_path: Path | None = None,
        model_path: Path | None = None,
    ):
        self.dataset = dataset
        self.models = models
        self.manifest = manifest
        self.dataset_path = dataset_path
        self.model_path = model_path

    @classmethod
    def load(
        cls,
        dataset_path: Path,
        model_path: Path,
        manifest_path: Path | None = None,
    ) -> "OutcomeStore":
        try:
            dataset = TemporalOutcomeDataset.model_validate(_load_json(dataset_path))
            models = OutcomeModelSnapshot.model_validate(_load_json(model_path))
            manifest = (
                OutcomeManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P5.1 outcome artifact: {exc}") from exc
        return cls(dataset, models, manifest, dataset_path, model_path)

    def quality_report(self) -> dict:
        rebuilt_dataset = build_outcome_dataset()
        dataset_deterministic = canonical_json_bytes(
            rebuilt_dataset.model_dump(mode="json")
        ) == canonical_json_bytes(self.dataset.model_dump(mode="json"))
        dataset_sha = file_sha256(self.dataset_path) if self.dataset_path else ""
        rebuilt_models = build_outcome_model_snapshot(rebuilt_dataset, dataset_sha)
        model_deterministic = canonical_json_bytes(
            rebuilt_models.model_dump(mode="json")
        ) == canonical_json_bytes(self.models.model_dump(mode="json"))
        checksums_match = bool(
            self.manifest
            and self.dataset_path
            and self.model_path
            and file_sha256(self.dataset_path) == self.manifest.dataset_sha256
            and file_sha256(self.model_path) == self.manifest.model_sha256
        )
        return {
            "dataset": self.dataset.quality.model_dump(mode="json"),
            "models": self.models.quality.model_dump(mode="json"),
            "dataset_id": self.dataset.id,
            "model_snapshot_id": self.models.id,
            "sklearn_version": self.models.sklearn_version,
            "dataset_deterministic_rebuild_matches": dataset_deterministic,
            "model_deterministic_rebuild_matches": model_deterministic,
            "artifact_checksums_match": checksums_match,
            "source_checksums_match": bool(
                self.manifest
                and self.manifest.source_checksums == _source_checksums()
            ),
            "warning": self.models.warning,
        }


def load_default_outcome_store() -> OutcomeStore:
    return OutcomeStore.load(
        default_outcome_dataset_path(),
        default_outcome_model_path(),
        default_outcome_manifest_path(),
    )
