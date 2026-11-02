"""Contracts for the R2.1 operator-driven external-payload hydration plan."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class HydrationRecipeRecord(StrictModel):
    id: StableId
    filename: str = Field(min_length=1)
    artifact_role: Literal["user_acquired_source_input", "deterministic_derived_output"]
    expected_byte_count: int = Field(gt=0)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependencies: list[str]
    operator_command: str = Field(min_length=1)
    command_stage: int = Field(ge=0)
    network_required: bool
    produced_during_plan: Literal[False] = False
    redistribution_authorized: Literal[False] = False


class HydrationRootRecord(StrictModel):
    id: StableId
    filename: str = Field(min_length=1)
    artifact_role: Literal["user_acquired_source_input", "deterministic_derived_output"]
    status: Literal["ready", "missing", "checksum_mismatch"]
    expected_byte_count: int = Field(gt=0)
    observed_byte_count: int | None = Field(default=None, ge=0)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    resolved_path: str | None = None


class HydrationQuality(StrictModel):
    artifact_count: Literal[24] = 24
    user_acquired_source_input_count: Literal[10] = 10
    deterministic_derived_output_count: Literal[14] = 14
    deterministic_rebuild_stage_count: Literal[11] = 11
    acquisition_command_coverage: Literal[1.0] = 1.0
    rebuild_command_coverage: Literal[1.0] = 1.0
    planning_network_request_count: Literal[0] = 0
    planning_file_copy_count: Literal[0] = 0
    redistribution_performed: Literal[False] = False
    small_packaged_fixture_redistribution_resolved: Literal[False] = False
    full_code_only_distribution_ready: Literal[False] = False
    hydration_contract_engineering_gate_passed: Literal[True] = True
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class HydrationSnapshot(StrictModel):
    schema_version: Literal["r2.1.0"] = "r2.1.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "operator_driven_capture_and_deterministic_rebuild_plan_no_automatic_data_transfer"
    ] = "operator_driven_capture_and_deterministic_rebuild_plan_no_automatic_data_transfer"
    recipe_path: str = Field(min_length=1)
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: HydrationQuality
    warning: str = Field(min_length=1)


class HydrationManifest(StrictModel):
    schema_version: Literal["r2.1.0"] = "r2.1.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=3)
    recipe_path: str = Field(min_length=1)
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_record_count: Literal[24] = 24
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
