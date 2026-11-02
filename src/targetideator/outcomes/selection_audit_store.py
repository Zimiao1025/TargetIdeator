"""Audit whether mapping/support strata are selected by baseline trial attributes."""

from __future__ import annotations

import gzip
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.broad_store import (
    default_broad_manifest_path,
    load_default_broad_outcome_store,
)
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.outcomes.selection_audit_models import (
    SelectionAuditManifest,
    SelectionAuditQuality,
    SelectionAuditSnapshot,
)
from targetideator.outcomes.support_audit_store import (
    STRATA,
    default_support_audit_manifest_path,
    load_default_support_audit_store,
)

BUILDER_VERSION = "p5.9-target-validation-selection-audit-v1"
SNAPSHOT_ID = "ti:selection-audit:target-validation-readiness-v1"
CREATED_AT = datetime(2026, 11, 2, 23, 0, tzinfo=timezone.utc)
RANDOM_SEED = 20261102
MATERIAL_IMBALANCE_THRESHOLD = 0.1
CATEGORICAL_FIELDS = (
    "phase",
    "baseline_status",
    "source_class",
    "baseline_snapshot",
    "enrollment_type",
)
NUMERIC_FIELDS = ("enrollment", "number_of_arms", "trial_age_days")
BOOLEAN_FIELDS = ("has_dmc", "is_fda_regulated_drug")
BASELINE_FIELDS = CATEGORICAL_FIELDS + NUMERIC_FIELDS + BOOLEAN_FIELDS


def default_selection_audit_snapshot_path() -> Path:
    return fixture_path("p5_9_selection_audit_snapshot.json")


def default_selection_audit_manifest_path() -> Path:
    return fixture_path("p5_9_selection_audit_manifest.json")


def _load_support_strata() -> dict[str, str]:
    store = load_default_support_audit_store()
    result = {}
    with gzip.open(
        artifact_path(store.root, store.manifest.enriched_outcome_path),
        "rt",
        encoding="utf-8",
    ) as stream:
        for line in stream:
            row = json.loads(line)
            result[row["nct_id"]] = row["support_stratum"]
    return result


def _earliest_baseline_records() -> tuple[list[dict], int]:
    store = load_default_broad_outcome_store()
    earliest = {}
    input_count = 0
    with gzip.open(
        artifact_path(store.root, store.manifest.normalized_dataset_path),
        "rt",
        encoding="utf-8",
    ) as stream:
        for line in stream:
            input_count += 1
            source = json.loads(line)
            record = {
                "nct_id": source["nct_id"],
                "baseline_date": source["baseline_date"],
                **{field: source.get(field) for field in BASELINE_FIELDS},
            }
            previous = earliest.get(record["nct_id"])
            if previous is None or record["baseline_date"] < previous["baseline_date"]:
                earliest[record["nct_id"]] = record
    return [earliest[nct_id] for nct_id in sorted(earliest)], input_count


def _raw_model_matrix(records: list[dict]) -> np.ndarray:
    return np.asarray(
        [[record.get(field) for field in BASELINE_FIELDS] for record in records],
        dtype=object,
    )


def _pipeline() -> object:
    categorical_indices = list(range(len(CATEGORICAL_FIELDS)))
    numeric_start = len(CATEGORICAL_FIELDS)
    numeric_indices = list(range(numeric_start, numeric_start + len(NUMERIC_FIELDS)))
    boolean_start = numeric_start + len(NUMERIC_FIELDS)
    boolean_indices = list(range(boolean_start, boolean_start + len(BOOLEAN_FIELDS)))
    transformer = ColumnTransformer(
        [
            (
                "categorical",
                make_pipeline(
                    SimpleImputer(strategy="most_frequent"),
                    OneHotEncoder(handle_unknown="ignore"),
                ),
                categorical_indices,
            ),
            (
                "numeric",
                make_pipeline(
                    SimpleImputer(strategy="median"),
                    StandardScaler(),
                ),
                numeric_indices,
            ),
            (
                "boolean",
                make_pipeline(
                    SimpleImputer(strategy="most_frequent"),
                    OneHotEncoder(handle_unknown="ignore"),
                ),
                boolean_indices,
            ),
        ]
    )
    return make_pipeline(transformer, LogisticRegression(max_iter=1000))


def _balance_matrix(records: list[dict]) -> tuple[np.ndarray, list[str]]:
    columns = []
    names = []
    for field in CATEGORICAL_FIELDS:
        levels = sorted(
            {
                str(record.get(field) if record.get(field) is not None else "MISSING")
                for record in records
            }
        )
        for level in levels:
            names.append(f"{field}={level}")
            columns.append(
                np.asarray(
                    [
                        float(
                            str(
                                record.get(field)
                                if record.get(field) is not None
                                else "MISSING"
                            )
                            == level
                        )
                        for record in records
                    ]
                )
            )
    for field in NUMERIC_FIELDS:
        names.extend((f"log1p_{field}", f"{field}_missing"))
        columns.extend(
            (
                np.asarray(
                    [
                        math.log1p(max(record[field], 0))
                        if record[field] is not None
                        else 0.0
                        for record in records
                    ]
                ),
                np.asarray([float(record[field] is None) for record in records]),
            )
        )
    for field in BOOLEAN_FIELDS:
        names.extend((f"{field}=true", f"{field}=missing"))
        columns.extend(
            (
                np.asarray([float(record[field] is True) for record in records]),
                np.asarray([float(record[field] is None) for record in records]),
            )
        )
    return np.vstack(columns).T, names


def _smd(group: np.ndarray, rest: np.ndarray) -> float:
    denominator = math.sqrt((float(group.var(ddof=1)) + float(rest.var(ddof=1))) / 2)
    if denominator == 0:
        return 0.0
    return (float(group.mean()) - float(rest.mean())) / denominator


def _common_support(probability: np.ndarray, positive: np.ndarray) -> dict[str, float]:
    positive_probability = probability[positive]
    negative_probability = probability[~positive]
    lower = max(
        float(np.quantile(positive_probability, 0.01)),
        float(np.quantile(negative_probability, 0.01)),
    )
    upper = min(
        float(np.quantile(positive_probability, 0.99)),
        float(np.quantile(negative_probability, 0.99)),
    )
    in_support = (probability >= lower) & (probability <= upper)
    return {
        "lower": lower,
        "upper": upper,
        "overall_fraction": float(in_support.mean()),
        "positive_fraction": float(in_support[positive].mean()),
        "negative_fraction": float(in_support[~positive].mean()),
    }


def build_selection_audit_records() -> tuple[list[dict], list[dict], SelectionAuditQuality]:
    records, input_count = _earliest_baseline_records()
    support = _load_support_strata()
    if set(support) != {record["nct_id"] for record in records}:
        raise ValueError("P5.2 baseline NCT and P5.8 support-audit NCT must match")
    strata = np.asarray([support[record["nct_id"]] for record in records])
    mapped = strata != "unmapped_no_source_assertion"
    raw_matrix = _raw_model_matrix(records)
    cross_fit = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_SEED)
    binary_probability = cross_val_predict(
        _pipeline(), raw_matrix, mapped.astype(int), cv=cross_fit, method="predict_proba"
    )[:, 1]
    stratum_index = np.asarray([STRATA.index(value) for value in strata])
    stratum_probability = cross_val_predict(
        _pipeline(), raw_matrix, stratum_index, cv=cross_fit, method="predict_proba"
    )

    balance_matrix, feature_names = _balance_matrix(records)
    contrasts = [("mapped_vs_unmapped", mapped)] + [
        (f"{stratum}_vs_rest", strata == stratum) for stratum in STRATA
    ]
    balance_records = []
    max_smd = {}
    material_counts = {}
    for contrast, positive in contrasts:
        contrast_values = []
        for column_index, feature_name in enumerate(feature_names):
            group = balance_matrix[positive, column_index]
            rest = balance_matrix[~positive, column_index]
            value = _smd(group, rest)
            contrast_values.append(abs(value))
            balance_records.append(
                {
                    "id": stable_id("selection-balance", f"{contrast}-{feature_name}"),
                    "contrast": contrast,
                    "feature_name": feature_name,
                    "group_count": int(positive.sum()),
                    "rest_count": int((~positive).sum()),
                    "group_mean": float(group.mean()),
                    "rest_mean": float(rest.mean()),
                    "standardized_mean_difference": value,
                    "absolute_standardized_mean_difference": abs(value),
                    "material_imbalance": abs(value) >= MATERIAL_IMBALANCE_THRESHOLD,
                    "outcome_field_used": False,
                }
            )
        max_smd[contrast] = max(contrast_values)
        material_counts[contrast] = sum(
            value >= MATERIAL_IMBALANCE_THRESHOLD for value in contrast_values
        )
    balance_records.sort(
        key=lambda row: (row["contrast"], -row["absolute_standardized_mean_difference"], row["feature_name"])
    )

    binary_support = _common_support(binary_probability, mapped)
    one_vs_rest_auc = {}
    one_vs_rest_support = {}
    for index, stratum in enumerate(STRATA):
        positive = stratum_index == index
        probability = stratum_probability[:, index]
        one_vs_rest_auc[stratum] = float(roc_auc_score(positive, probability))
        one_vs_rest_support[stratum] = _common_support(
            probability, positive
        )["overall_fraction"]

    cohort = []
    for index, record in enumerate(records):
        cohort.append(
            {
                "id": stable_id("selection-audit-trial", record["nct_id"]),
                **record,
                "support_stratum": strata[index],
                "mapping_status": "mapped" if mapped[index] else "unmapped",
                "cross_fitted_mapping_propensity": float(binary_probability[index]),
                "cross_fitted_stratum_probabilities": {
                    stratum: float(stratum_probability[index, stratum_index_value])
                    for stratum_index_value, stratum in enumerate(STRATA)
                },
                "model_feature_fields": list(BASELINE_FIELDS),
                "outcome_field_used_as_feature": False,
                "identifier_used_as_feature": False,
                "post_baseline_feature_used": False,
            }
        )

    quality = SelectionAuditQuality(
        unique_nct_count=len(records),
        input_landmark_record_count=input_count,
        repeated_landmark_record_count_collapsed=input_count - len(records),
        support_stratum_counts={name: int((strata == name).sum()) for name in STRATA},
        baseline_feature_count=len(feature_names),
        balance_contrast_count=len(contrasts),
        balance_diagnostic_record_count=len(balance_records),
        mapped_vs_unmapped_max_abs_smd=max_smd["mapped_vs_unmapped"],
        mapped_vs_unmapped_material_imbalance_count=material_counts["mapped_vs_unmapped"],
        max_abs_smd_by_contrast=max_smd,
        mapping_selection_roc_auc=float(roc_auc_score(mapped, binary_probability)),
        mapping_selection_log_loss=float(log_loss(mapped, binary_probability)),
        mapping_common_support_lower=binary_support["lower"],
        mapping_common_support_upper=binary_support["upper"],
        mapping_common_support_fraction=binary_support["overall_fraction"],
        mapped_group_common_support_fraction=binary_support["positive_fraction"],
        unmapped_group_common_support_fraction=binary_support["negative_fraction"],
        stratum_one_vs_rest_roc_auc=one_vs_rest_auc,
        stratum_one_vs_rest_common_support_fraction=one_vs_rest_support,
        engineering_gate_passed=(
            len(records) == 36086
            and input_count == 71947
            and len(feature_names) == 32
            and len(balance_records) == 160
            and max_smd["mapped_vs_unmapped"] > 0.5
            and float(roc_auc_score(mapped, binary_probability)) > 0.65
        ),
        blocking_limitations=[
            "Baseline trial attributes predict mapping availability, so mapped records are not an exchangeable subset of all trials.",
            "Large standardized differences remain across calendar snapshot, enrollment metadata, and trial age.",
            "Common-support diagnostics do not establish conditional exchangeability or justify causal reweighting.",
            "The audit intentionally excludes all outcome fields and produces no target-level outcome estimate.",
            "Target-level validation remains no-go until trial-specific linkage or a defensible identification design is available.",
        ],
    )
    return cohort, balance_records, quality


def render_selection_audit_report(snapshot: SelectionAuditSnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P5.9 target-validation selection audit",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Unique NCT: {q.unique_nct_count}",
            f"- Baseline balance features: {q.baseline_feature_count}",
            f"- Mapping-selection cross-fitted ROC-AUC: {q.mapping_selection_roc_auc:.4f}",
            f"- Maximum mapped/unmapped |SMD|: {q.mapped_vs_unmapped_max_abs_smd:.4f}",
            f"- Common-support fraction: {q.mapping_common_support_fraction:.4f}",
            f"- Target validation ready: {str(q.target_validation_ready).lower()}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def _source_checksums() -> dict[str, str]:
    broad = load_default_broad_outcome_store()
    support = load_default_support_audit_store()
    broad_path = artifact_path(broad.root, broad.manifest.normalized_dataset_path)
    support_path = artifact_path(support.root, support.manifest.enriched_outcome_path)
    return {
        broad_path.name: file_sha256(broad_path),
        default_broad_manifest_path().name: file_sha256(default_broad_manifest_path()),
        support_path.name: file_sha256(support_path),
        default_support_audit_manifest_path().name: file_sha256(default_support_audit_manifest_path()),
    }


def write_selection_audit_artifacts(output_dir: Path) -> tuple[SelectionAuditSnapshot, SelectionAuditManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cohort, balance, quality = build_selection_audit_records()
    cohort_path = output_dir / "p5_9_selection_cohort.jsonl.gz"
    balance_path = output_dir / "p5_9_balance_diagnostics.jsonl.gz"
    _write_jsonl_gzip(cohort_path, cohort)
    _write_jsonl_gzip(balance_path, balance)
    snapshot = SelectionAuditSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        cohort_path=cohort_path.name,
        cohort_sha256=file_sha256(cohort_path),
        balance_path=balance_path.name,
        balance_sha256=file_sha256(balance_path),
        quality=quality,
        warning=(
            "TARGET VALIDATION NO-GO. Selection diagnostics reveal non-random mapping "
            "coverage; no outcome comparison, causal weighting, or target estimate is permitted."
        ),
    )
    snapshot_path = output_dir / "p5_9_selection_audit_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_9_selection_audit_report.md").write_text(
        render_selection_audit_report(snapshot), encoding="utf-8"
    )
    manifest = SelectionAuditManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        sklearn_version=sklearn.__version__,
        source_checksums=_source_checksums(),
        cohort_path=cohort_path.name,
        cohort_sha256=file_sha256(cohort_path),
        cohort_record_count=len(cohort),
        balance_path=balance_path.name,
        balance_sha256=file_sha256(balance_path),
        balance_record_count=len(balance),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p5_9_selection_audit_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class SelectionAuditStore:
    def __init__(self, snapshot: SelectionAuditSnapshot, manifest: SelectionAuditManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "SelectionAuditStore":
        return cls(
            SelectionAuditSnapshot.model_validate(_load_json(snapshot_path)),
            SelectionAuditManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, filename: str, limit: int, predicate=None) -> list[dict]:
        rows = []
        with gzip.open(artifact_path(self.root, filename), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if predicate is not None and not predicate(row):
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    break
        return rows

    def sample_cohort(self, limit: int = 20, stratum: str | None = None) -> list[dict]:
        return self._sample(
            self.manifest.cohort_path,
            limit,
            None if stratum is None else lambda row: row["support_stratum"] == stratum,
        )

    def sample_balance(self, limit: int = 20, contrast: str | None = None, material_only: bool = False) -> list[dict]:
        return self._sample(
            self.manifest.balance_path,
            limit,
            lambda row: (
                (contrast is None or row["contrast"] == contrast)
                and (not material_only or row["material_imbalance"])
            ),
        )

    def trial(self, nct_id: str) -> dict | None:
        rows = self._sample(
            self.manifest.cohort_path, 1, lambda row: row["nct_id"] == nct_id
        )
        return rows[0] if rows else None

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.cohort_path))
                == self.manifest.cohort_sha256
                and file_sha256(artifact_path(self.root, self.manifest.balance_path))
                == self.manifest.balance_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_selection_audit_store() -> SelectionAuditStore:
    return SelectionAuditStore.load(default_selection_audit_snapshot_path(), default_selection_audit_manifest_path())
