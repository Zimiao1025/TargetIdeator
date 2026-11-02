"""Contracts for the R2.5 isolated execution replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class ReplayGroupRecord(StrictModel):
    id: StableId
    command_group_id: StableId
    command_stage: int = Field(ge=0)
    command_template: str = Field(min_length=1)
    network_required: bool
    expected_output_paths: list[str] = Field(min_length=1)
    started_at: datetime
    completed_at: datetime
    duration_seconds: float = Field(ge=0)
    exit_code: int
    status: Literal["completed", "failed"]
    exact_match_count: int = Field(ge=0)
    checksum_mismatch_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    stdout_log_path: str = Field(min_length=1)
    stderr_log_path: str = Field(min_length=1)
    command_executed: Literal[True] = True
    source_file_deleted: Literal[False] = False
    configuration_mutation_applied: Literal[False] = False


class ArtifactReplayRecord(StrictModel):
    id: StableId
    execution_recipe_id: StableId
    command_group_id: StableId
    relative_path: str = Field(min_length=1)
    disposition: Literal["externalize", "regenerate"]
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_byte_count: int | None = Field(default=None, ge=0)
    status: Literal["exact_match", "checksum_mismatch", "missing"]


class ExecutionReplayQuality(StrictModel):
    command_group_count: Literal[31] = 31
    executed_command_group_count: int = Field(ge=0, le=31)
    successful_command_group_count: int = Field(ge=0, le=31)
    failed_command_group_count: int = Field(ge=0, le=31)
    network_command_group_count: Literal[6] = 6
    rebuild_command_group_count: Literal[25] = 25
    artifact_count: Literal[113] = 113
    exact_match_count: int = Field(ge=0, le=113)
    checksum_mismatch_count: int = Field(ge=0, le=113)
    missing_count: int = Field(ge=0, le=113)
    externalize_exact_match_count: int = Field(ge=0, le=14)
    regenerate_exact_match_count: int = Field(ge=0, le=99)
    bulk_symlink_count: Literal[24] = 24
    data_file_copy_count: Literal[0] = 0
    source_file_delete_count: Literal[0] = 0
    configuration_write_count: Literal[0] = 0
    replay_execution_complete: bool
    checksum_replay_gate_passed: bool
    projected_runtime_smoke_gate_passed: Literal[False] = False
    package_convergence_gate_passed: Literal[False] = False
    public_release_authorized: Literal[False] = False
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class ExecutionReplaySnapshot(StrictModel):
    schema_version: Literal["r2.5.0"] = "r2.5.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "execute_grouped_recipes_in_isolated_staging_without_source_or_config_mutation"
    ] = "execute_grouped_recipes_in_isolated_staging_without_source_or_config_mutation"
    parent_execution_plan_snapshot_id: StableId
    parent_execution_recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staging_root_label: str = Field(min_length=1)
    group_replay_path: str = Field(min_length=1)
    group_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_replay_path: str = Field(min_length=1)
    artifact_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: ExecutionReplayQuality
    warning: str = Field(min_length=1)


class ExecutionReplayManifest(StrictModel):
    schema_version: Literal["r2.5.0"] = "r2.5.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    parent_execution_plan_snapshot_id: StableId
    parent_execution_recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    group_replay_path: str = Field(min_length=1)
    group_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    group_replay_record_count: Literal[31] = 31
    artifact_replay_path: str = Field(min_length=1)
    artifact_replay_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_replay_record_count: Literal[113] = 113
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
