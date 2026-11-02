"""Build the P5.2 broad temporal outcome benchmark and frozen baselines."""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.outcomes.broad_models import (
    BootstrapInterval,
    BroadBaselineEvaluation,
    BroadCauseReport,
    BroadOutcomeManifest,
    BroadOutcomeQuality,
    BroadOutcomeSnapshot,
)
from targetideator.outcomes.models import ModelStatus, OutcomeCategory, OutcomeCause, TemporalSplit
from targetideator.outcomes.store import (
    _boolean,
    _cause_labels,
    _date,
    _enum,
    _integer,
    _metrics,
    _outcome_category,
    _phase,
    _raw_sha,
)

BUILDER_VERSION = "p5.2-broad-temporal-baselines-v1"
SNAPSHOT_ID = "ti:outcome-benchmark:aact-broad-six-month-v1"
CREATED_AT = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)
BOOTSTRAP_SEED = 20261102
BOOTSTRAP_RESAMPLES = 200
_SPLITS = (TemporalSplit.TRAIN, TemporalSplit.VALIDATION, TemporalSplit.TEST)

PHASE_FEATURE_NAMES = [
    "phase_phase1_phase2",
    "phase_phase2",
    "phase_phase2_phase3",
    "phase_phase3",
]
FULL_FEATURE_NAMES = [
    *PHASE_FEATURE_NAMES,
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
    "trial_age_missing",
    "source_class_industry",
    "source_class_nih",
    "source_class_fed",
    "source_class_other",
    "has_dmc_true",
    "has_dmc_missing",
    "fda_regulated_drug_true",
    "fda_regulated_drug_missing",
]


def default_broad_raw_paths() -> list[Path]:
    return [
        fixture_path(f"aact_broad_outcomes_{split.value}_raw.json.gz")
        for split in _SPLITS
    ]


def default_broad_snapshot_path() -> Path:
    return fixture_path("p5_2_broad_outcome_snapshot.json")


def default_broad_manifest_path() -> Path:
    return fixture_path("p5_2_broad_outcome_manifest.json")


def _read_capture(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _write_jsonl_gzip(path: Path, rows: list[dict]) -> None:
    with path.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            for row in rows:
                compressed.write(canonical_json_bytes(row) + b"\n")


def _record(
    split: TemporalSplit,
    capture: dict,
    baseline: dict,
    outcome: dict | None,
    repeated: bool,
) -> dict:
    baseline_date = date.fromisoformat(capture["baseline_date"])
    first_posted = _date(baseline.get("study_first_posted_date"))
    if first_posted and first_posted > baseline_date:
        raise ValueError(f"{baseline['nct_id']} was posted after its baseline snapshot")
    if outcome is None:
        category = OutcomeCategory.UNKNOWN
        rule_id = "p5.2.outcome.unknown.missing-from-outcome-snapshot"
        outcome_status = "MISSING_FROM_OUTCOME_SNAPSHOT"
        why_stopped = None
        outcome_sha = "0" * 64
    else:
        category, rule_id = _outcome_category(outcome)
        outcome_status = _enum(outcome.get("overall_status")) or "UNKNOWN"
        why_stopped = outcome.get("why_stopped") or None
        outcome_sha = _raw_sha(outcome)
    labels = {item.cause.value: item.value for item in _cause_labels(category)}
    if category == OutcomeCategory.UNKNOWN:
        observation = "excluded_unknown"
    elif category == OutcomeCategory.ONGOING_RIGHT_CENSORED:
        observation = "right_censored_negative_at_horizon"
    else:
        observation = "observed"
    return {
        "id": stable_id(
            "broad-temporal-outcome",
            f"{split.value}-{capture['baseline_version']}-{baseline['nct_id']}",
        ),
        "nct_id": baseline["nct_id"],
        "split": split.value,
        "baseline_snapshot": capture["baseline_version"],
        "baseline_date": capture["baseline_date"],
        "outcome_snapshot": capture["outcome_version"],
        "outcome_date": capture["outcome_date"],
        "horizon_days": capture["horizon_days"],
        "phase": _phase(baseline.get("phase")),
        "baseline_status": _enum(baseline.get("overall_status")) or "UNKNOWN",
        "enrollment": _integer(baseline.get("enrollment")),
        "enrollment_type": _enum(baseline.get("enrollment_type")) or None,
        "source_class": _enum(baseline.get("source_class")) or "UNKNOWN",
        "number_of_arms": _integer(baseline.get("number_of_arms")),
        "has_dmc": _boolean(baseline.get("has_dmc")),
        "is_fda_regulated_drug": _boolean(baseline.get("is_fda_regulated_drug")),
        "trial_age_days": (baseline_date - first_posted).days if first_posted else None,
        "outcome_status": outcome_status,
        "why_stopped": why_stopped,
        "outcome_category": category.value,
        "classification_rule_id": rule_id,
        "label_observation": observation,
        **{f"label_{cause.value}": labels[cause.value] for cause in OutcomeCause},
        "repeated_nct_across_splits": repeated,
        "baseline_raw_sha256": _raw_sha(baseline),
        "outcome_raw_sha256": outcome_sha,
    }


def build_broad_records(raw_paths: list[Path] | None = None) -> list[dict]:
    paths = raw_paths or default_broad_raw_paths()
    captures = {}
    for path in paths:
        capture = _read_capture(path)
        captures[capture["split"]] = capture
    if set(captures) != {item.value for item in _SPLITS}:
        raise ValueError("train, validation, and test broad captures are required")
    nct_counts = Counter(
        row["nct_id"]
        for split in _SPLITS
        for row in captures[split.value]["baseline_rows"]
    )
    records = []
    for split in _SPLITS:
        capture = captures[split.value]
        outcomes = {row["nct_id"]: row for row in capture["outcome_rows"]}
        for baseline in capture["baseline_rows"]:
            records.append(
                _record(
                    split,
                    capture,
                    baseline,
                    outcomes.get(baseline["nct_id"]),
                    nct_counts[baseline["nct_id"]] > 1,
                )
            )
    records.sort(key=lambda item: (_SPLITS.index(TemporalSplit(item["split"])), item["nct_id"]))
    return records


def _phase_vector(record: dict) -> list[float]:
    phase = record["phase"]
    return [
        float(phase == "PHASE1_PHASE2"),
        float(phase == "PHASE2"),
        float(phase == "PHASE2_PHASE3"),
        float(phase == "PHASE3"),
    ]


def _full_vector(record: dict) -> list[float]:
    enrollment = record["enrollment"]
    arms = record["number_of_arms"]
    age = record["trial_age_days"]
    source = record["source_class"]
    status = record["baseline_status"]
    return [
        *_phase_vector(record),
        float(status == "NOT_YET_RECRUITING"),
        float(status == "RECRUITING"),
        float(status == "ENROLLING_BY_INVITATION"),
        float(status == "ACTIVE_NOT_RECRUITING"),
        math.log1p(enrollment or 0),
        float(enrollment is None),
        float(record["enrollment_type"] == "ACTUAL"),
        math.log1p(arms or 0),
        float(arms is None),
        (age or 0) / 365.25,
        float(age is None),
        float(source == "INDUSTRY"),
        float(source == "NIH"),
        float(source == "FED"),
        float(source not in {"INDUSTRY", "NIH", "FED"}),
        float(record["has_dmc"] is True),
        float(record["has_dmc"] is None),
        float(record["is_fda_regulated_drug"] is True),
        float(record["is_fda_regulated_drug"] is None),
    ]


def _arrays(records: list[dict], split: TemporalSplit, cause: OutcomeCause):
    rows = [
        row
        for row in records
        if row["split"] == split.value and row[f"label_{cause.value}"] is not None
    ]
    return (
        np.asarray([_phase_vector(row) for row in rows], dtype=float),
        np.asarray([_full_vector(row) for row in rows], dtype=float),
        np.asarray([int(row[f"label_{cause.value}"]) for row in rows], dtype=int),
        rows,
    )


def _fit_calibrated(train_x, train_y, validation_x, validation_y, test_x):
    estimator = LogisticRegression(
        class_weight="balanced", solver="lbfgs", max_iter=2000, random_state=0
    )
    estimator.fit(train_x, train_y)
    validation_probability = estimator.predict_proba(validation_x)[:, 1]
    test_probability = estimator.predict_proba(test_x)[:, 1]
    clipped = np.clip(validation_probability, 1e-6, 1 - 1e-6)
    validation_logit = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    calibrator = LogisticRegression(
        C=1_000_000.0, solver="lbfgs", max_iter=2000, random_state=0
    )
    calibrator.fit(validation_logit, validation_y)
    test_clipped = np.clip(test_probability, 1e-6, 1 - 1e-6)
    test_logit = np.log(test_clipped / (1 - test_clipped)).reshape(-1, 1)
    calibrated = calibrator.predict_proba(test_logit)[:, 1]
    return estimator, calibrator, calibrated


def _interval(metric: str, point: float, values: list[float]) -> BootstrapInterval:
    array = np.asarray(values, dtype=float)
    return BootstrapInterval(
        metric=metric,
        point_estimate=point,
        lower_95=float(np.quantile(array, 0.025)),
        upper_95=float(np.quantile(array, 0.975)),
        resample_count=BOOTSTRAP_RESAMPLES,
        valid_resample_count=len(values),
        seed=BOOTSTRAP_SEED,
    )


def _bootstrap_brier(
    labels: np.ndarray,
    probabilities: np.ndarray,
    prevalence_probabilities: np.ndarray,
) -> tuple[BootstrapInterval, BootstrapInterval]:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    briers = []
    deltas = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        indexes = rng.integers(0, len(labels), size=len(labels))
        model_brier = float(np.mean((probabilities[indexes] - labels[indexes]) ** 2))
        prevalence_brier = float(
            np.mean((prevalence_probabilities[indexes] - labels[indexes]) ** 2)
        )
        briers.append(model_brier)
        deltas.append(model_brier - prevalence_brier)
    point = float(np.mean((probabilities - labels) ** 2))
    delta = point - float(np.mean((prevalence_probabilities - labels) ** 2))
    return _interval("brier_score", point, briers), _interval(
        "brier_delta_vs_train_prevalence", delta, deltas
    )


def _serialize_estimator(estimator, calibrator, names: list[str]) -> dict[str, object]:
    return {
        "feature_names": names,
        "coefficients": {
            name: float(value)
            for name, value in zip(names, estimator.coef_[0], strict=True)
        },
        "intercept": float(estimator.intercept_[0]),
        "calibrator_coefficient": float(calibrator.coef_[0][0]),
        "calibrator_intercept": float(calibrator.intercept_[0]),
    }


def _fit_cause(
    records: list[dict], cause: OutcomeCause, prior_nct_ids: set[str]
) -> tuple[BroadCauseReport, list[dict]]:
    train_phase, train_full, train_y, _ = _arrays(records, TemporalSplit.TRAIN, cause)
    validation_phase, validation_full, validation_y, _ = _arrays(
        records, TemporalSplit.VALIDATION, cause
    )
    test_phase, test_full, test_y, test_rows = _arrays(records, TemporalSplit.TEST, cause)
    positives = (int(train_y.sum()), int(validation_y.sum()), int(test_y.sum()))
    novel_mask = np.asarray(
        [row["nct_id"] not in prior_nct_ids for row in test_rows], dtype=bool
    )
    novel_positive = int(test_y[novel_mask].sum())
    if (
        min(positives[0], positives[1]) == 0
        or len(train_y) == positives[0]
        or len(validation_y) == positives[1]
    ):
        return (
            BroadCauseReport(
                cause=cause,
                status=ModelStatus.NOT_TRAINABLE_MISSING_CLASS,
                train_positive_count=positives[0],
                validation_positive_count=positives[1],
                test_positive_count=positives[2],
                novel_nct_test_positive_count=novel_positive,
                feature_names=FULL_FEATURE_NAMES,
                calibration_method="none",
                calibration_fit_split="none",
                evaluations=[],
                parameters={},
                limitations=[
                    "Train or validation lacks a positive class; no model or calibrator was fitted."
                ],
            ),
            [],
        )
    phase_model, phase_calibrator, phase_probability = _fit_calibrated(
        train_phase, train_y, validation_phase, validation_y, test_phase
    )
    full_model, full_calibrator, full_probability = _fit_calibrated(
        train_full, train_y, validation_full, validation_y, test_full
    )
    prevalence = float(train_y.mean())
    prevalence_probability = np.full(len(test_y), prevalence)
    evaluations = []
    for name, probability, calibrated in (
        ("train_prevalence", prevalence_probability, False),
        ("phase_only_logistic", phase_probability, True),
        ("full_structured_logistic", full_probability, True),
    ):
        interval, delta = _bootstrap_brier(
            test_y, probability, prevalence_probability
        )
        evaluations.append(
            BroadBaselineEvaluation(
                name=name,
                calibrated=calibrated,
                calibration_fit_split="validation" if calibrated else "none",
                test_metrics=_metrics(test_y, probability),
                novel_nct_test_metrics=_metrics(
                    test_y[novel_mask], probability[novel_mask]
                ),
                brier_interval=interval,
                brier_delta_vs_prevalence_interval=(
                    None if name == "train_prevalence" else delta
                ),
            )
        )
    predictions = [
        {
            "record_id": row["id"],
            "nct_id": row["nct_id"],
            "cause": cause.value,
            "label": bool(label),
            "novel_nct_vs_prior_splits": bool(novel),
            "train_prevalence_probability": float(prevalence_value),
            "phase_only_calibrated_probability": float(phase_value),
            "full_structured_calibrated_probability": float(full_value),
        }
        for row, label, novel, prevalence_value, phase_value, full_value in zip(
            test_rows,
            test_y,
            novel_mask,
            prevalence_probability,
            phase_probability,
            full_probability,
            strict=True,
        )
    ]
    return (
        BroadCauseReport(
            cause=cause,
            status=ModelStatus.TRAINED_VALIDATION_CALIBRATED,
            train_positive_count=positives[0],
            validation_positive_count=positives[1],
            test_positive_count=positives[2],
            novel_nct_test_positive_count=novel_positive,
            feature_names=FULL_FEATURE_NAMES,
            calibration_method="platt_sigmoid_validation_only",
            calibration_fit_split="validation",
            evaluations=evaluations,
            parameters={
                "phase_only": _serialize_estimator(
                    phase_model, phase_calibrator, PHASE_FEATURE_NAMES
                ),
                "full_structured": _serialize_estimator(
                    full_model, full_calibrator, FULL_FEATURE_NAMES
                ),
            },
            limitations=[
                "Termination causes are conservative registry-text labels, not adjudicated clinical outcomes.",
                "Bootstrap intervals resample frozen test predictions by NCT and do not include training uncertainty.",
                "Novel-NCT sensitivity may have too few or zero positives for discrimination metrics.",
            ],
        ),
        predictions,
    )


def _quality(records: list[dict], reports: list[BroadCauseReport]) -> BroadOutcomeQuality:
    nct_counts = Counter(row["nct_id"] for row in records)
    split_ids = {
        split: {row["nct_id"] for row in records if row["split"] == split.value}
        for split in _SPLITS
    }
    categories = Counter(row["outcome_category"] for row in records)
    positives = {
        split: {
            cause: sum(
                row[f"label_{cause.value}"] is True
                for row in records
                if row["split"] == split.value
            )
            for cause in OutcomeCause
        }
        for split in _SPLITS
    }
    trained = sum(
        item.status == ModelStatus.TRAINED_VALIDATION_CALIBRATED for item in reports
    )
    return BroadOutcomeQuality(
        record_count=len(records),
        split_counts=dict(Counter(TemporalSplit(row["split"]) for row in records)),
        trainable_counts={
            split: sum(
                row["split"] == split.value and row["label_efficacy"] is not None
                for row in records
            )
            for split in _SPLITS
        },
        category_counts=dict(categories),
        cause_positive_counts_by_split=positives,
        unique_nct_count=len(nct_counts),
        repeated_nct_count=sum(value > 1 for value in nct_counts.values()),
        missing_outcome_snapshot_count=sum(
            row["outcome_status"] == "MISSING_FROM_OUTCOME_SNAPSHOT" for row in records
        ),
        unknown_excluded_count=categories[OutcomeCategory.UNKNOWN.value],
        right_censored_count=categories[OutcomeCategory.ONGOING_RIGHT_CENSORED.value],
        validation_nct_overlap_with_train=len(
            split_ids[TemporalSplit.VALIDATION] & split_ids[TemporalSplit.TRAIN]
        ),
        test_nct_overlap_with_prior_splits=len(
            split_ids[TemporalSplit.TEST]
            & (split_ids[TemporalSplit.TRAIN] | split_ids[TemporalSplit.VALIDATION])
        ),
        novel_nct_test_count=len(
            split_ids[TemporalSplit.TEST]
            - (split_ids[TemporalSplit.TRAIN] | split_ids[TemporalSplit.VALIDATION])
        ),
        forbidden_feature_count=0,
        post_baseline_feature_leakage_count=0,
        test_fit_leakage_count=0,
        trained_head_count=trained,
        untrainable_head_count=len(OutcomeCause) - trained,
        engineering_gate_passed=(len(records) > 70_000 and trained >= 3),
        blocking_limitations=[
            "Labels are unadjudicated explicit registry stop reasons and undercapture implicit causes.",
            "PK has no positive class and remains untrainable.",
            "Calendar splits contain repeated NCTs; novel-NCT metrics are mandatory sensitivity results.",
            "No disease, target, mechanism, intervention identity, or sponsor-name feature is modeled.",
            "The benchmark estimates six-month registry cause incidence, not target or drug success.",
        ],
    )


def render_broad_report(snapshot: BroadOutcomeSnapshot) -> str:
    quality = snapshot.quality
    lines = [
        "# TargetIdeator P5.2 broad temporal outcome benchmark",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Records / unique NCT: {quality.record_count} / {quality.unique_nct_count}",
        f"- Right-censored: {quality.right_censored_count}",
        f"- Novel-NCT test: {quality.novel_nct_test_count}",
        f"- Trained heads: {quality.trained_head_count}/4",
        "",
        "## Cause models and baselines",
        "",
    ]
    for report in snapshot.model_reports:
        lines.append(f"### {report.cause.value}: {report.status.value}")
        lines.append("")
        lines.append(
            f"- Positives train/validation/test/novel-test: {report.train_positive_count}/"
            f"{report.validation_positive_count}/{report.test_positive_count}/"
            f"{report.novel_nct_test_positive_count}"
        )
        for evaluation in report.evaluations:
            metrics = evaluation.test_metrics
            novel = evaluation.novel_nct_test_metrics
            lines.append(
                f"- `{evaluation.name}`: Brier={metrics.brier_score}; PR-AUC={metrics.pr_auc}; "
                f"novel-NCT PR-AUC={novel.pr_auc}"
            )
        lines.append("")
    lines.extend(["## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def write_broad_outcome_artifacts(
    output_dir: Path, raw_paths: list[Path] | None = None
) -> tuple[BroadOutcomeSnapshot, BroadOutcomeManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = raw_paths or default_broad_raw_paths()
    records = build_broad_records(paths)
    dataset_path = output_dir / "p5_2_broad_outcomes.jsonl.gz"
    _write_jsonl_gzip(dataset_path, records)
    prior_ids = {
        row["nct_id"]
        for row in records
        if row["split"] in {TemporalSplit.TRAIN.value, TemporalSplit.VALIDATION.value}
    }
    reports = []
    predictions = []
    for cause in OutcomeCause:
        report, cause_predictions = _fit_cause(records, cause, prior_ids)
        reports.append(report)
        predictions.extend(cause_predictions)
    predictions.sort(key=lambda item: (item["cause"], item["nct_id"]))
    prediction_path = output_dir / "p5_2_broad_test_predictions.jsonl.gz"
    _write_jsonl_gzip(prediction_path, predictions)
    quality = _quality(records, reports)
    snapshot = BroadOutcomeSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        normalized_dataset_path=dataset_path.name,
        normalized_dataset_sha256=file_sha256(dataset_path),
        prediction_path=prediction_path.name,
        prediction_sha256=file_sha256(prediction_path),
        sklearn_version=sklearn.__version__,
        model_reports=reports,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY ALL-INDICATION REGISTRY BENCHMARK. Sparse explicit stop-reason "
            "labels and repeated trial landmarks prevent target, drug, efficacy, or safety claims."
        ),
    )
    snapshot_path = output_dir / "p5_2_broad_outcome_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_2_broad_outcome_report.md").write_text(
        render_broad_report(snapshot), encoding="utf-8"
    )
    manifest = BroadOutcomeManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        raw_checksums={path.name: file_sha256(path) for path in paths},
        normalized_dataset_path=dataset_path.name,
        normalized_dataset_sha256=file_sha256(dataset_path),
        prediction_path=prediction_path.name,
        prediction_sha256=file_sha256(prediction_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
        record_count=len(records),
        test_prediction_count=len(predictions),
    )
    write_json(
        output_dir / "p5_2_broad_outcome_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class BroadOutcomeStore:
    def __init__(
        self,
        snapshot: BroadOutcomeSnapshot,
        manifest: BroadOutcomeManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "BroadOutcomeStore":
        snapshot = BroadOutcomeSnapshot.model_validate(_load_json(snapshot_path))
        manifest = BroadOutcomeManifest.model_validate(_load_json(manifest_path))
        return cls(snapshot, manifest, snapshot_path.parent)

    def sample_records(self, limit: int = 20) -> list[dict]:
        result = []
        path = artifact_path(self.root, self.manifest.normalized_dataset_path)
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                result.append(json.loads(line))
                if len(result) >= limit:
                    break
        return result

    def quality_report(self) -> dict:
        dataset_path = artifact_path(self.root, self.manifest.normalized_dataset_path)
        prediction_path = artifact_path(self.root, self.manifest.prediction_path)
        snapshot_path = artifact_path(self.root, self.manifest.snapshot_path)
        raw_checksums = {path.name: file_sha256(path) for path in default_broad_raw_paths()}
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(dataset_path) == self.manifest.normalized_dataset_sha256
                and file_sha256(prediction_path) == self.manifest.prediction_sha256
                and file_sha256(snapshot_path) == self.manifest.snapshot_sha256
            ),
            "raw_checksums_match": raw_checksums == self.manifest.raw_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_broad_outcome_store() -> BroadOutcomeStore:
    return BroadOutcomeStore.load(
        default_broad_snapshot_path(), default_broad_manifest_path()
    )
