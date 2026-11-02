"""Contracts for the R1 artifact release-candidate audit."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class ReleaseGateStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


class ReleaseGateOwner(StrEnum):
    AUTOMATION = "automation"
    PROJECT_OWNER = "project_owner"
    DATA_STEWARD = "data_steward"


class ReleaseGateRecord(StrictModel):
    id: StableId
    gate_id: Literal[
        "dependency_lock_present",
        "python_bounds_declared",
        "package_version_consistent",
        "reproducibility_runbook_present",
        "release_surface_local_path_clean",
        "ignore_hygiene_present",
        "project_license_declared",
        "citation_metadata_complete",
        "data_redistribution_ledger_complete",
        "project_vcs_root_isolated",
        "package_payload_within_budget",
    ]
    status: ReleaseGateStatus
    owner: ReleaseGateOwner
    evidence: str = Field(min_length=1)
    remediation: str | None = None


class PackagePayloadRecord(StrictModel):
    id: StableId
    relative_path: str = Field(min_length=1)
    byte_count: int = Field(ge=0)
    payload_class: Literal["code", "fixture_or_artifact", "other"]
    redistribution_review_required: bool


class ReleaseAuditQuality(StrictModel):
    release_gate_count: Literal[11] = 11
    passed_gate_count: Literal[6] = 6
    blocked_gate_count: Literal[5] = 5
    release_candidate_ready: Literal[False] = False
    safe_automated_hardening_complete: bool
    legal_metadata_ready: Literal[False] = False
    citation_metadata_ready: Literal[False] = False
    data_redistribution_ready: Literal[False] = False
    vcs_isolation_ready: Literal[False] = False
    package_size_budget_ready: Literal[False] = False
    sensitive_local_path_finding_count: Literal[0] = 0
    package_payload_file_count: int = Field(gt=0)
    package_payload_byte_count: int = Field(gt=0)
    package_payload_budget_bytes: Literal[52428800] = 52428800
    package_payload_over_budget_bytes: int = Field(gt=0)
    redistribution_review_file_count: int = Field(gt=0)
    oversized_payload_file_count: int = Field(gt=0)
    license_file_count: Literal[0] = 0
    citation_file_count: Literal[0] = 0
    redistribution_ledger_file_count: Literal[0] = 0
    engineering_gate_passed: bool
    publication_or_upload_authorized: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class ReleaseAuditSnapshot(StrictModel):
    schema_version: Literal["r1.0.0"] = "r1.0.0"
    id: StableId
    created_at: datetime
    audit_policy: Literal[
        "static_release_surface_and_package_payload_audit_no_upload"
    ] = "static_release_surface_and_package_payload_audit_no_upload"
    gate_audit_path: str = Field(min_length=1)
    gate_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_inventory_path: str = Field(min_length=1)
    payload_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: ReleaseAuditQuality
    warning: str = Field(min_length=1)


class ReleaseAuditManifest(StrictModel):
    schema_version: Literal["r1.0.0"] = "r1.0.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    gate_audit_path: str = Field(min_length=1)
    gate_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_audit_record_count: Literal[11] = 11
    payload_inventory_path: str = Field(min_length=1)
    payload_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_inventory_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
