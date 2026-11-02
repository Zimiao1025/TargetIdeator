"""Contracts for the R2 code/data packaging split."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class DataBundleRecord(StrictModel):
    id: StableId
    relative_path: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    byte_count: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_class: Literal["source_capture", "derived_artifact"]
    required_at_runtime: Literal[True] = True
    packaged_in_code_distribution: Literal[False] = False


class PackagingSplitQuality(StrictModel):
    split_threshold_bytes: Literal[1048576] = 1048576
    externalized_file_count: Literal[24] = 24
    externalized_byte_count: int = Field(gt=0)
    retained_fixture_file_count: int = Field(gt=0)
    retained_fixture_byte_count: int = Field(gt=0)
    projected_code_payload_file_count: int = Field(gt=0)
    projected_code_payload_byte_count: int = Field(gt=0)
    code_payload_budget_bytes: Literal[52428800] = 52428800
    code_payload_within_budget: Literal[True] = True
    external_data_root_contract_present: Literal[True] = True
    external_data_required: Literal[True] = True
    data_inventory_checksum_complete: Literal[True] = True
    redistribution_ledger_complete: Literal[False] = False
    data_bundle_publication_authorized: Literal[False] = False
    code_data_split_engineering_gate_passed: Literal[True] = True
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class PackagingSplitSnapshot(StrictModel):
    schema_version: Literal["r2.0.0"] = "r2.0.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "fixed_large_fixture_externalization_with_checksum_bound_local_data_bundle"
    ] = "fixed_large_fixture_externalization_with_checksum_bound_local_data_bundle"
    data_inventory_path: str = Field(min_length=1)
    data_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: PackagingSplitQuality
    warning: str = Field(min_length=1)


class PackagingSplitManifest(StrictModel):
    schema_version: Literal["r2.0.0"] = "r2.0.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    externalized_filenames: list[str] = Field(min_length=1)
    data_inventory_path: str = Field(min_length=1)
    data_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_inventory_record_count: Literal[24] = 24
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
