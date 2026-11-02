"""Contracts for the P6.6 reproducible paper artifact bundle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class PaperFileRole(StrEnum):
    INDEX = "index"
    POSITIONING = "positioning"
    METHODS = "methods"
    RESULTS = "results"
    LIMITATIONS = "limitations"
    REPRODUCIBILITY = "reproducibility"
    TABLE = "table"


class ReadinessGateStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


class SourceManifestInventoryRecord(StrictModel):
    id: StableId
    stage_id: str = Field(pattern=r"^P[1-6](?:\.[0-9]+)?$")
    manifest_filename: str = Field(min_length=1)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_id: str = Field(min_length=1)
    checksum_frozen: Literal[True] = True


class ReadinessGateRecord(StrictModel):
    id: StableId
    gate_id: Literal[
        "artifact_checksum_completeness",
        "deterministic_rebuild_contract",
        "negative_result_preservation",
        "headline_scientific_claim_support",
        "target_benchmark_identification",
        "final_human_gold",
    ]
    status: ReadinessGateStatus
    gate_scope: Literal["artifact_release", "scientific_submission"]
    evidence: str = Field(min_length=1)
    blocking_reason: str | None = None


class PaperFileInventoryRecord(StrictModel):
    id: StableId
    relative_path: str = Field(pattern=r"^paper/.+\.md$")
    role: PaperFileRole
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)


class PaperBundleQuality(StrictModel):
    source_manifest_count: Literal[22] = 22
    source_manifest_checksum_coverage: Literal[1.0] = 1.0
    paper_file_count: Literal[9] = 9
    readiness_gate_count: Literal[6] = 6
    passed_artifact_gate_count: Literal[3] = 3
    blocked_scientific_gate_count: Literal[3] = 3
    artifact_release_ready: bool
    scientific_submission_ready: Literal[False] = False
    scientifically_supported_claim_count: Literal[0] = 0
    claim_status_changed_count: Literal[0] = 0
    negative_result_preserved: bool
    future_outcome_reveal_count: Literal[0] = 0
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class PaperBundleSnapshot(StrictModel):
    schema_version: Literal["6.6.0"] = "6.6.0"
    id: StableId
    created_at: datetime
    positioning: Literal[
        "reproducible_methods_artifact_and_negative_results_not_validated_target_discovery"
    ] = "reproducible_methods_artifact_and_negative_results_not_validated_target_discovery"
    source_manifest_inventory_path: str = Field(min_length=1)
    source_manifest_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    readiness_gate_path: str = Field(min_length=1)
    readiness_gate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_file_inventory_path: str = Field(min_length=1)
    paper_file_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_index_path: Literal["paper/README.md"] = "paper/README.md"
    quality: PaperBundleQuality
    warning: str = Field(min_length=1)


class PaperBundleManifest(StrictModel):
    schema_version: Literal["6.6.0"] = "6.6.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=22, max_length=22)
    source_manifest_inventory_path: str = Field(min_length=1)
    source_manifest_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_inventory_record_count: Literal[22] = 22
    readiness_gate_path: str = Field(min_length=1)
    readiness_gate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    readiness_gate_record_count: Literal[6] = 6
    paper_file_inventory_path: str = Field(min_length=1)
    paper_file_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paper_file_inventory_record_count: Literal[9] = 9
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
