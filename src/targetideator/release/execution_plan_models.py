"""Contracts for the R2.4 execution plan and package-mutation preview."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel
from targetideator.release.retained_fixture_models import ArtifactClass


class ExecutionRecipeRecord(StrictModel):
    id: StableId
    fixture_disposition_id: StableId
    relative_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_class: ArtifactClass
    disposition: Literal["externalize", "regenerate"]
    recipe_kind: Literal["operator_capture", "deterministic_rebuild"]
    command_group_id: StableId
    command_stage: int = Field(ge=0)
    dependencies: list[str]
    operator_command: str = Field(min_length=1)
    projected_output_path: str = Field(min_length=1)
    network_required: bool
    recipe_status: Literal["command_bound_unreplayed"] = "command_bound_unreplayed"
    command_executed: Literal[False] = False
    checksum_replayed: Literal[False] = False
    destructive_operation: Literal[False] = False


class MutationPreviewRecord(StrictModel):
    id: StableId
    relative_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_class: ArtifactClass
    disposition: Literal["retain", "externalize", "regenerate"]
    current_packaged: Literal[True] = True
    projected_packaged: bool
    preview_action: Literal["retain_in_package", "add_build_exclusion"]
    pyproject_exclude_entry: str | None = None
    source_file_deleted: Literal[False] = False
    configuration_mutation_applied: Literal[False] = False


class ExecutionPlanQuality(StrictModel):
    disposition_record_count: Literal[129] = 129
    execution_target_count: Literal[113] = 113
    execution_recipe_count: Literal[113] = 113
    unique_operator_command_count: Literal[31] = 31
    recipe_coverage: Literal[1.0] = 1.0
    externalize_recipe_count: Literal[14] = 14
    regenerate_recipe_count: Literal[99] = 99
    projected_retain_count: Literal[16] = 16
    projected_exclude_count: Literal[113] = 113
    existing_bulk_exclude_count: Literal[24] = 24
    projected_combined_exclude_count: Literal[137] = 137
    current_retained_byte_count: int = Field(gt=0)
    projected_retained_byte_count: int = Field(gt=0)
    projected_excluded_byte_count: int = Field(gt=0)
    planning_network_request_count: Literal[0] = 0
    planning_command_execution_count: Literal[0] = 0
    source_file_delete_count: Literal[0] = 0
    configuration_write_count: Literal[0] = 0
    checksum_replay_count: Literal[0] = 0
    execution_plan_engineering_gate_passed: Literal[True] = True
    mutation_preview_engineering_gate_passed: Literal[True] = True
    checksum_replay_gate_passed: Literal[False] = False
    projected_runtime_smoke_gate_passed: Literal[False] = False
    package_convergence_gate_passed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class ExecutionPlanSnapshot(StrictModel):
    schema_version: Literal["r2.4.0"] = "r2.4.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "command_bound_execution_plan_and_non_destructive_package_mutation_preview"
    ] = "command_bound_execution_plan_and_non_destructive_package_mutation_preview"
    parent_disposition_snapshot_id: StableId
    parent_disposition_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_recipe_path: str = Field(min_length=1)
    execution_recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutation_preview_path: str = Field(min_length=1)
    mutation_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: ExecutionPlanQuality
    warning: str = Field(min_length=1)


class ExecutionPlanManifest(StrictModel):
    schema_version: Literal["r2.4.0"] = "r2.4.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    parent_disposition_snapshot_id: StableId
    parent_disposition_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_recipe_path: str = Field(min_length=1)
    execution_recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_recipe_record_count: Literal[113] = 113
    mutation_preview_path: str = Field(min_length=1)
    mutation_preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutation_preview_record_count: Literal[129] = 129
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
