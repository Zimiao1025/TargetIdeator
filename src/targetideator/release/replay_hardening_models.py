"""Contracts for R2.6 replay hardening and drift diagnosis."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class ArtifactDriftDiagnosis(StrictModel):
    id: StableId
    execution_recipe_id: StableId
    command_group_id: StableId
    relative_path: str = Field(min_length=1)
    byte_status: Literal["exact_match", "checksum_mismatch", "missing"]
    diagnosis: Literal[
        "exact_byte_match",
        "declared_metadata_only_drift",
        "substantive_content_drift",
        "missing_capture_output",
        "missing_dependency_output",
        "missing_command_output",
    ]
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_normalized_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observed_normalized_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    missing_dependencies: list[str] = Field(default_factory=list)
    normalization_policy: Literal[
        "ignore_declared_capture_timestamps_retry_counters_and_checksum_lineage_values"
    ] = "ignore_declared_capture_timestamps_retry_counters_and_checksum_lineage_values"
    diagnosis_is_non_gating: Literal[True] = True


class ReplayHardeningQuality(StrictModel):
    artifact_count: int = Field(gt=0)
    exact_byte_match_count: int = Field(ge=0)
    declared_metadata_only_drift_count: int = Field(ge=0)
    substantive_content_drift_count: int = Field(ge=0)
    missing_capture_output_count: int = Field(ge=0)
    missing_dependency_output_count: int = Field(ge=0)
    missing_command_output_count: int = Field(ge=0)
    diagnostic_coverage: float = Field(ge=0, le=1)
    retry_hardening_enabled: Literal[True] = True
    maximum_download_attempt_count: Literal[3] = 3
    retryable_http_status_codes: list[int] = Field(min_length=1)
    byte_checksum_gate_passed: bool
    metadata_normalized_diagnostic_passed: bool
    projected_runtime_smoke_gate_passed: Literal[False] = False
    package_convergence_gate_passed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class ReplayHardeningSnapshot(StrictModel):
    schema_version: Literal["r2.6.0"] = "r2.6.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "bounded_capture_retry_and_non_gating_declared_metadata_drift_diagnosis"
    ] = "bounded_capture_retry_and_non_gating_declared_metadata_drift_diagnosis"
    parent_execution_replay_snapshot_id: StableId
    parent_execution_replay_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staging_root_label: str = Field(min_length=1)
    diagnosis_path: str = Field(min_length=1)
    diagnosis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: ReplayHardeningQuality
    warning: str = Field(min_length=1)


class ReplayHardeningManifest(StrictModel):
    schema_version: Literal["r2.6.0"] = "r2.6.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    parent_execution_replay_snapshot_id: StableId
    parent_execution_replay_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnosis_path: str = Field(min_length=1)
    diagnosis_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    diagnosis_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
