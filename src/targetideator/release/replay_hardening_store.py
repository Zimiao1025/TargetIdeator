"""R2.6 bounded capture retry orchestration and non-gating drift diagnosis."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ingestion.clinical_sources import (
    DOWNLOAD_RETRY_DELAYS_SECONDS,
    RETRYABLE_HTTP_STATUS_CODES,
)
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.execution_plan_store import load_default_execution_plan_store
from targetideator.release.replay_hardening_models import (
    ArtifactDriftDiagnosis,
    ReplayHardeningManifest,
    ReplayHardeningQuality,
    ReplayHardeningSnapshot,
)
from targetideator.release.replay_store import ExecutionReplayStore, run_execution_replay

BUILDER_VERSION = "r2.6-replay-hardening-v1"
VOLATILE_KEYS = {
    "captured_at",
    "created_at",
    "attempt_count",
    "retry_count",
    "dataTimestamp",
    "data_timestamp",
}
HEX_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_checksums() -> dict[str, str]:
    root = _project_root()
    paths = (
        "src/targetideator/ingestion/clinical_sources.py",
        "src/targetideator/evidence/models.py",
        "src/targetideator/release/replay_hardening_models.py",
        "src/targetideator/release/replay_hardening_store.py",
        "src/targetideator/release/replay_store.py",
    )
    return {path: file_sha256(root / path) for path in paths}


def _load_structured(path: Path) -> Any:
    if path.name.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".md":
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported replay-diagnosis artifact: {path}")


def _normalize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        volatile_current_api_version = value.get("source") in {
            "chembl_api",
            "ctgov_api",
        }
        return {
            key: _normalize_metadata(item)
            for key, item in value.items()
            if key not in VOLATILE_KEYS
            and key != "source_checksums"
            and key != "sha256"
            and not key.endswith("sha256")
            and not (key == "version" and volatile_current_api_version)
        }
    if isinstance(value, list):
        return [_normalize_metadata(item) for item in value]
    if isinstance(value, str):
        return HEX_SHA256.sub("<DECLARED_SHA256_METADATA>", value)
    return value


def _normalized_sha256(path: Path) -> str:
    normalized = _normalize_metadata(_load_structured(path))
    if isinstance(normalized, str):
        payload = normalized.encode("utf-8")
    else:
        payload = canonical_json_bytes(normalized)
    return hashlib.sha256(payload).hexdigest()


def write_replay_hardening_artifacts(
    replay_root: Path,
    output_dir: Path | None = None,
    expected_root: Path | None = None,
) -> tuple[ReplayHardeningSnapshot, ReplayHardeningManifest]:
    output = output_dir or replay_root
    output.mkdir(parents=True, exist_ok=True)
    expected = expected_root or (_project_root() / "src" / "targetideator" / "fixtures")
    replay = ExecutionReplayStore.load(
        replay_root / "r2_5_execution_replay_snapshot.json",
        replay_root / "r2_5_execution_replay_manifest.json",
    )
    plan = load_default_execution_plan_store()
    recipes = {row.id: row for row in plan.recipe()}
    data_root = replay_root / "data"
    records = []
    for row in replay.artifacts():
        recipe = recipes[row.execution_recipe_id]
        expected_path = expected / row.relative_path
        observed_path = replay_root / recipe.projected_output_path
        missing_dependencies = [
            dependency for dependency in recipe.dependencies if not (data_root / dependency).is_file()
        ]
        expected_normalized = None
        observed_normalized = None
        if row.status == "exact_match":
            diagnosis = "exact_byte_match"
        elif row.status == "missing":
            if recipe.network_required:
                diagnosis = "missing_capture_output"
            elif missing_dependencies:
                diagnosis = "missing_dependency_output"
            else:
                diagnosis = "missing_command_output"
        else:
            expected_normalized = _normalized_sha256(expected_path)
            observed_normalized = _normalized_sha256(observed_path)
            diagnosis = (
                "declared_metadata_only_drift"
                if expected_normalized == observed_normalized
                else "substantive_content_drift"
            )
        records.append(
            ArtifactDriftDiagnosis(
                id=stable_id("artifact-drift-diagnosis", row.relative_path),
                execution_recipe_id=row.execution_recipe_id,
                command_group_id=row.command_group_id,
                relative_path=row.relative_path,
                byte_status=row.status,
                diagnosis=diagnosis,
                expected_sha256=row.expected_sha256,
                observed_sha256=row.observed_sha256,
                expected_normalized_sha256=expected_normalized,
                observed_normalized_sha256=observed_normalized,
                missing_dependencies=missing_dependencies,
            )
        )
    counts = Counter(row.diagnosis for row in records)
    artifact_count = len(records)
    diagnosed = sum(counts.values())
    missing = sum(
        counts[key]
        for key in (
            "missing_capture_output",
            "missing_dependency_output",
            "missing_command_output",
        )
    )
    quality = ReplayHardeningQuality(
        artifact_count=artifact_count,
        exact_byte_match_count=counts["exact_byte_match"],
        declared_metadata_only_drift_count=counts["declared_metadata_only_drift"],
        substantive_content_drift_count=counts["substantive_content_drift"],
        missing_capture_output_count=counts["missing_capture_output"],
        missing_dependency_output_count=counts["missing_dependency_output"],
        missing_command_output_count=counts["missing_command_output"],
        diagnostic_coverage=diagnosed / artifact_count,
        maximum_download_attempt_count=len(DOWNLOAD_RETRY_DELAYS_SECONDS) + 1,
        retryable_http_status_codes=sorted(RETRYABLE_HTTP_STATUS_CODES),
        byte_checksum_gate_passed=counts["exact_byte_match"] == artifact_count,
        metadata_normalized_diagnostic_passed=(
            missing == 0 and counts["substantive_content_drift"] == 0
        ),
        blocking_limitations=[
            "Metadata-normalized equality is diagnostic and never waives a byte checksum mismatch.",
            "Checksum fields are ignored only to locate drift propagation; referenced artifacts remain independently audited.",
            "Bounded retries improve transport robustness but do not pin mutable upstream content.",
            "Projected-wheel runtime smoke and package configuration mutation remain separate closed gates.",
            "R2.6 does not authorize redistribution or alter scientific claim status or C1/C4.",
        ],
    )
    diagnosis_path = output / "r2_6_artifact_diagnosis.jsonl.gz"
    _write_jsonl_gzip(
        diagnosis_path, [row.model_dump(mode="json") for row in records]
    )
    parent_manifest_path = replay_root / "r2_5_execution_replay_manifest.json"
    completed_at = max(row.completed_at for row in replay.groups())
    snapshot = ReplayHardeningSnapshot(
        id=stable_id("replay-hardening", replay_root.name),
        created_at=completed_at,
        parent_execution_replay_snapshot_id=replay.snapshot.id,
        parent_execution_replay_manifest_sha256=file_sha256(parent_manifest_path),
        staging_root_label=replay_root.name,
        diagnosis_path=diagnosis_path.name,
        diagnosis_sha256=file_sha256(diagnosis_path),
        quality=quality,
        warning=(
            "NON-GATING DRIFT DIAGNOSIS. Metadata normalization does not accept changed bytes, "
            "authorize package mutation, or replace runtime smoke."
        ),
    )
    snapshot_path = output / "r2_6_replay_hardening_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = ReplayHardeningManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        parent_execution_replay_snapshot_id=replay.snapshot.id,
        parent_execution_replay_manifest_sha256=file_sha256(parent_manifest_path),
        diagnosis_path=diagnosis_path.name,
        diagnosis_sha256=file_sha256(diagnosis_path),
        diagnosis_record_count=artifact_count,
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output / "r2_6_replay_hardening_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


def run_hardened_execution_replay(
    staging_root: Path,
    bundle_root: Path,
    *,
    command_timeout_seconds: int = 7200,
) -> tuple[ReplayHardeningSnapshot, ReplayHardeningManifest]:
    run_execution_replay(
        staging_root,
        bundle_root,
        command_timeout_seconds=command_timeout_seconds,
    )
    return write_replay_hardening_artifacts(staging_root)


class ReplayHardeningStore:
    def __init__(
        self,
        snapshot: ReplayHardeningSnapshot,
        manifest: ReplayHardeningManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "ReplayHardeningStore":
        return cls(
            ReplayHardeningSnapshot.model_validate(_load_json(snapshot_path)),
            ReplayHardeningManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def diagnosis(self) -> list[ArtifactDriftDiagnosis]:
        with gzip.open(
            self.root / self.manifest.diagnosis_path, "rt", encoding="utf-8"
        ) as stream:
            return [ArtifactDriftDiagnosis.model_validate(json.loads(line)) for line in stream]

    def quality_report(self) -> dict:
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        parent_manifest = self.root / "r2_5_execution_replay_manifest.json"
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "parent_execution_replay_link_matches": (
                parent_manifest.is_file()
                and file_sha256(parent_manifest)
                == self.manifest.parent_execution_replay_manifest_sha256
            ),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.diagnosis_path)
                == self.manifest.diagnosis_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }
