"""Contracts for the R2.3 owner/data-steward packaging dispositions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel
from targetideator.release.retained_fixture_models import ArtifactClass, RecommendedAction


class FixtureDispositionRecord(StrictModel):
    id: StableId
    retained_fixture_id: StableId
    relative_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_class: ArtifactClass
    prior_recommendation: RecommendedAction
    decision: Literal["retain", "externalize", "regenerate"]
    decision_authority: Literal["project_owner", "data_steward"]
    decision_basis: str = Field(min_length=1)
    execution_status: Literal[
        "recorded_no_payload_change_required",
        "blocked_pending_hydration_recipe",
        "blocked_pending_rebuild_recipe",
    ]
    decision_recorded: Literal[True] = True
    redistribution_authorized: Literal[False] = False
    execution_applied: Literal[False] = False


class FixtureDispositionQuality(StrictModel):
    inventory_record_count: Literal[129] = 129
    decision_record_count: Literal[129] = 129
    decision_coverage: Literal[1.0] = 1.0
    retain_count: Literal[16] = 16
    externalize_count: Literal[14] = 14
    regenerate_count: Literal[99] = 99
    project_owner_decision_count: Literal[115] = 115
    data_steward_decision_count: Literal[14] = 14
    conflicting_decision_count: Literal[0] = 0
    unresolved_packaging_disposition_count: Literal[0] = 0
    execution_applied_count: Literal[0] = 0
    externalize_execution_ready_count: Literal[0] = 0
    regenerate_execution_ready_count: Literal[0] = 0
    redistribution_authorized_count: Literal[0] = 0
    decision_ledger_engineering_gate_passed: Literal[True] = True
    package_convergence_gate_passed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class FixtureDispositionSnapshot(StrictModel):
    schema_version: Literal["r2.3.0"] = "r2.3.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "record_owner_dispositions_without_redistribution_authorization_or_execution"
    ] = "record_owner_dispositions_without_redistribution_authorization_or_execution"
    parent_inventory_snapshot_id: StableId
    parent_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: FixtureDispositionQuality
    warning: str = Field(min_length=1)


class FixtureDispositionManifest(StrictModel):
    schema_version: Literal["r2.3.0"] = "r2.3.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    parent_inventory_snapshot_id: StableId
    parent_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_record_count: Literal[129] = 129
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
