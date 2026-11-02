"""Contracts for the R2.7 versioned canonical-content acceptance gate."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class CanonicalFieldRule(StrictModel):
    id: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    semantic_guard: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class CanonicalAcceptanceRecord(StrictModel):
    id: StableId
    execution_recipe_id: StableId
    relative_path: str = Field(min_length=1)
    byte_status: Literal["exact_match", "checksum_mismatch", "missing"]
    acceptance_status: Literal[
        "accepted_byte_identity",
        "accepted_canonical_content_v1",
        "rejected",
    ]
    changed_paths: list[str]
    applied_rule_ids: list[str]
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_canonical_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    observed_canonical_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    approved_path_set_matches: bool
    semantic_guards_passed: bool
    canonical_content_matches: bool


class CanonicalAcceptanceQuality(StrictModel):
    artifact_count: Literal[113] = 113
    byte_identity_acceptance_count: int = Field(ge=0, le=113)
    canonical_content_acceptance_count: int = Field(ge=0, le=113)
    rejected_count: int = Field(ge=0, le=113)
    approved_changed_artifact_count: Literal[47] = 47
    approved_changed_path_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_path_map_matches_approved_v1: bool
    semantic_guard_failure_count: int = Field(ge=0)
    canonical_mismatch_count: int = Field(ge=0)
    byte_checksum_gate_passed: Literal[False] = False
    canonical_content_gate_passed: bool
    projected_runtime_smoke_gate_passed: Literal[False] = False
    package_convergence_gate_passed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class CanonicalAcceptanceSnapshot(StrictModel):
    schema_version: Literal["r2.7.0"] = "r2.7.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "hybrid_byte_identity_and_versioned_field_level_canonical_content_v1"
    ] = "hybrid_byte_identity_and_versioned_field_level_canonical_content_v1"
    contract_version: Literal["canonical-content-v1"] = "canonical-content-v1"
    parent_replay_hardening_snapshot_id: StableId
    parent_replay_hardening_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staging_root_label: str = Field(min_length=1)
    rules: list[CanonicalFieldRule] = Field(min_length=1)
    acceptance_ledger_path: str = Field(min_length=1)
    acceptance_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: CanonicalAcceptanceQuality
    warning: str = Field(min_length=1)


class CanonicalAcceptanceManifest(StrictModel):
    schema_version: Literal["r2.7.0"] = "r2.7.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    parent_replay_hardening_snapshot_id: StableId
    parent_replay_hardening_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_ledger_path: str = Field(min_length=1)
    acceptance_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acceptance_record_count: Literal[113] = 113
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
