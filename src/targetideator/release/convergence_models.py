"""Contracts for the R2.8 applied package-convergence and runtime-smoke gate."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class PackageFileAuditRecord(StrictModel):
    id: StableId
    relative_path: str = Field(min_length=1)
    exclusion_origin: Literal[
        "existing_bulk_split",
        "r2_4_owner_disposition",
        "r2_8_external_self_attestation",
    ]
    source_file_present: bool
    wheel_exclusion_configured: bool
    sdist_exclusion_configured: bool
    absent_from_built_wheel: bool
    external_resolution_required: bool
    external_resolution_smoke_passed: bool


class RuntimeSmokeRecord(StrictModel):
    id: StableId
    check_name: Literal[
        "offline_wheel_build",
        "isolated_venv_creation",
        "offline_wheel_install",
        "installed_import",
        "cli_help",
        "missing_data_error_contract",
        "external_data_and_app_factory",
    ]
    command: list[str] = Field(min_length=1)
    exit_code: int
    status: Literal["passed", "failed"]
    duration_seconds: float = Field(ge=0)
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    offline_mode: Literal[True] = True


class PackageConvergenceQuality(StrictModel):
    canonical_content_gate_passed: Literal[True] = True
    byte_checksum_gate_passed: Literal[False] = False
    owner_disposition_exclusion_count: Literal[113] = 113
    existing_bulk_exclusion_count: Literal[24] = 24
    external_self_attestation_exclusion_count: Literal[4] = 4
    governed_data_exclusion_count: Literal[137] = 137
    combined_exclusion_count: Literal[141] = 141
    source_file_present_count: int = Field(ge=0, le=141)
    source_file_delete_count: Literal[0] = 0
    wheel_config_exclusion_count: int = Field(ge=0)
    sdist_config_exclusion_count: int = Field(ge=0)
    configuration_mutation_applied: bool
    built_wheel_byte_count: int = Field(gt=0)
    built_wheel_file_count: int = Field(gt=0)
    built_wheel_fixture_count: int = Field(ge=0)
    unexpectedly_packaged_excluded_count: int = Field(ge=0)
    external_resolution_smoke_count: int = Field(ge=0, le=137)
    runtime_smoke_check_count: Literal[7] = 7
    runtime_smoke_passed_count: int = Field(ge=0, le=7)
    runtime_smoke_network_request_count: Literal[0] = 0
    projected_runtime_smoke_gate_passed: bool
    package_convergence_gate_passed: bool
    public_release_authorized: Literal[False] = False
    data_bundle_publication_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class PackageConvergenceSnapshot(StrictModel):
    schema_version: Literal["r2.8.0"] = "r2.8.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "applied_explicit_exclusions_offline_wheel_smoke_and_external_data_resolution"
    ] = "applied_explicit_exclusions_offline_wheel_smoke_and_external_data_resolution"
    parent_canonical_acceptance_snapshot_id: StableId
    parent_canonical_acceptance_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pyproject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wheel_path: str = Field(min_length=1)
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_audit_path: str = Field(min_length=1)
    file_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_smoke_path: str = Field(min_length=1)
    runtime_smoke_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: PackageConvergenceQuality
    warning: str = Field(min_length=1)


class PackageConvergenceManifest(StrictModel):
    schema_version: Literal["r2.8.0"] = "r2.8.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    parent_canonical_acceptance_snapshot_id: StableId
    parent_canonical_acceptance_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pyproject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    wheel_path: str = Field(min_length=1)
    wheel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_audit_path: str = Field(min_length=1)
    file_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_audit_record_count: Literal[141] = 141
    runtime_smoke_path: str = Field(min_length=1)
    runtime_smoke_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_smoke_record_count: Literal[7] = 7
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
