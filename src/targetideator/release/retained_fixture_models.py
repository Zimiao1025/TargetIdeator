"""Contracts for the R2.2 retained-fixture governance inventory."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


ArtifactClass = Literal[
    "package_code",
    "source_capture",
    "curated_fixture",
    "derived_artifact",
    "release_metadata",
]
RecommendedAction = Literal[
    "retain_code_native",
    "externalize_pending_redistribution_decision",
    "retain_pending_owner_review",
    "regenerate_from_external_inputs_candidate",
    "retain_release_metadata_candidate",
]
OwnerRole = Literal["maintainer", "data_steward", "scientific_owner", "pipeline_owner"]


class RetainedFixtureRecord(StrictModel):
    id: StableId
    relative_path: str = Field(min_length=1)
    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_class: ArtifactClass
    classification_basis: str = Field(min_length=1)
    recommended_action: RecommendedAction
    owner_role: OwnerRole
    source_derived: bool
    redistribution_decision: Literal["unresolved"] = "unresolved"
    legal_conclusion_made: Literal[False] = False
    packaging_change_applied: Literal[False] = False


class RetainedFixtureQuality(StrictModel):
    retained_file_count: int = Field(gt=0)
    retained_byte_count: int = Field(gt=0)
    package_code_count: int = Field(ge=0)
    source_capture_count: int = Field(ge=0)
    curated_fixture_count: int = Field(ge=0)
    derived_artifact_count: int = Field(ge=0)
    release_metadata_count: int = Field(ge=0)
    classified_file_count: int = Field(gt=0)
    inventory_coverage: Literal[1.0] = 1.0
    unresolved_redistribution_count: int = Field(gt=0)
    legal_conclusion_count: Literal[0] = 0
    packaging_change_applied_count: Literal[0] = 0
    public_release_authorized: Literal[False] = False
    full_code_only_distribution_ready: Literal[False] = False
    governance_inventory_engineering_gate_passed: Literal[True] = True
    scientific_claim_status_changed: Literal[False] = False
    c1_unblocked: Literal[False] = False
    c4_unblocked: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class RetainedFixtureSnapshot(StrictModel):
    schema_version: Literal["r2.2.0"] = "r2.2.0"
    id: StableId
    created_at: datetime
    policy: Literal[
        "classify_retained_payload_without_legal_conclusion_or_packaging_mutation"
    ] = "classify_retained_payload_without_legal_conclusion_or_packaging_mutation"
    inventory_path: str = Field(min_length=1)
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: RetainedFixtureQuality
    warning: str = Field(min_length=1)


class RetainedFixtureManifest(StrictModel):
    schema_version: Literal["r2.2.0"] = "r2.2.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    inventory_path: str = Field(min_length=1)
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    inventory_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
