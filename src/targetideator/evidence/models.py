"""Strict contracts for the P1 temporal evidence substrate.

These contracts intentionally live beside, rather than inside, the frozen P0.2
schema.  P1 evidence ingestion can therefore evolve without reopening the
expert-reviewed hypothesis-card contract.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from targetideator.contracts.models import StableId


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SnapshotMode(StrEnum):
    HISTORICAL_RELEASE = "historical_release"
    FROZEN_CURRENT_SUBSET = "frozen_current_subset"


class MappingStatus(StrEnum):
    EXACT = "exact"
    CURATED_ALIAS = "curated_alias"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class AvailabilityBasis(StrEnum):
    SOURCE_RELEASE = "source_release"
    SOURCE_RECORD = "source_record"


class DatePrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class CanonicalEntity(StrictModel):
    entity_type: Literal["disease", "gene", "drug", "trial"]
    namespace: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    label: str = Field(min_length=1)


class EntityMapping(StrictModel):
    id: StableId
    input_value: str = Field(min_length=1)
    entity_type: Literal["disease", "gene", "drug", "trial"]
    canonical: CanonicalEntity
    status: Literal[MappingStatus.EXACT, MappingStatus.CURATED_ALIAS]
    confidence: float = Field(ge=0, le=1)
    mapping_method: str = Field(min_length=1)
    snapshot_id: StableId


class UnresolvedEntity(StrictModel):
    id: StableId
    input_value: str = Field(min_length=1)
    entity_type: Literal["disease", "gene", "drug", "trial"]
    status: Literal[MappingStatus.AMBIGUOUS, MappingStatus.UNRESOLVED]
    reason: str = Field(min_length=1)
    candidate_ids: list[str] = Field(default_factory=list)
    review_status: Literal["open", "resolved"] = "open"


class SourceSnapshot(StrictModel):
    id: StableId
    source_name: Literal["Open Targets Platform"]
    release_version: str = Field(min_length=1)
    release_date: date
    captured_at: datetime
    mode: SnapshotMode
    retrospective_claims_allowed: bool
    api_endpoint: HttpUrl
    release_url: HttpUrl
    adapter_version: str = Field(min_length=1)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=0)
    source_total_count: int = Field(ge=0)
    complete_for_query: bool

    @model_validator(mode="after")
    def current_subset_cannot_support_retrospective_claims(self) -> "SourceSnapshot":
        if self.mode == SnapshotMode.FROZEN_CURRENT_SUBSET and self.retrospective_claims_allowed:
            raise ValueError("a frozen current subset cannot support retrospective claims")
        if self.complete_for_query and self.record_count != self.source_total_count:
            raise ValueError("a complete query must contain every reported source record")
        return self


class SourceLineage(StrictModel):
    snapshot_id: StableId
    raw_record_id: str = Field(min_length=1)
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1)
    field_map: dict[str, str] = Field(min_length=1)


class TemporalEvidence(StrictModel):
    id: StableId
    target: CanonicalEntity
    disease: CanonicalEntity
    datasource_id: str = Field(min_length=1)
    datatype_id: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=1)
    evidence_date_raw: str | None = None
    event_date: date | None = None
    event_date_precision: DatePrecision = DatePrecision.UNKNOWN
    publication_date: date | None = None
    study_start_date: date | None = None
    available_on: date
    availability_basis: AvailabilityBasis
    direction_on_target: str | None = None
    direction_on_trait: str | None = None
    study_id: str | None = None
    literature_ids: list[str] = Field(default_factory=list)
    source_urls: list[HttpUrl] = Field(min_length=1)
    lineage: SourceLineage


class EvidenceSnapshot(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    source: SourceSnapshot
    mappings: list[EntityMapping]
    unresolved_entities: list[UnresolvedEntity]
    records: list[TemporalEvidence]

    @model_validator(mode="after")
    def validate_cross_record_integrity(self) -> "EvidenceSnapshot":
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("temporal evidence IDs must be unique")
        if len(self.records) != self.source.record_count:
            raise ValueError("source record_count does not match normalized records")
        wrong_snapshot = [
            record.id
            for record in self.records
            if record.lineage.snapshot_id != self.source.id
        ]
        if wrong_snapshot:
            raise ValueError(f"records reference another snapshot: {wrong_snapshot[:3]}")
        return self


class BuildManifest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: StableId
    raw_path: str = Field(min_length=1)
    normalized_path: str = Field(min_length=1)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: str = Field(min_length=1)
    normalized_record_count: int = Field(ge=0)


class TemporalQueryResult(StrictModel):
    snapshot_id: StableId
    disease_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    as_of_date: date
    records: list[TemporalEvidence]
    excluded_post_cutoff_count: int = Field(ge=0)
    post_cutoff_leakage_count: int = Field(ge=0)
    retrospective_valid: bool
    use_policy: Literal["engineering_demo_only", "retrospective_analysis_allowed"]
    warning: str = Field(min_length=1)


class EvidenceDiff(StrictModel):
    earlier_date: date
    later_date: date
    added_ids: list[StableId]
    removed_ids: list[StableId]


class ArchiveFile(StrictModel):
    url: HttpUrl
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_modified: str | None = None
    attempt_count: int = Field(default=1, ge=1, le=3, exclude=True)
    retry_count: int = Field(default=0, ge=0, le=2, exclude=True)

    @model_validator(mode="after")
    def validate_retry_accounting(self) -> "ArchiveFile":
        if self.retry_count != self.attempt_count - 1:
            raise ValueError("retry_count must equal attempt_count - 1")
        return self


class ArchiveRelease(StrictModel):
    id: StableId
    version: str = Field(min_length=1)
    release_date: date
    archive_url: HttpUrl
    dataset: Literal["association_by_datasource_direct"]
    captured_at: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_files: list[ArchiveFile] = Field(min_length=1)
    dataset_row_count: int = Field(gt=0)
    subset_row_count: int = Field(ge=0)
    complete_for_query: bool


class ReleaseAssociation(StrictModel):
    id: StableId
    membership_key: StableId
    release_id: StableId
    release_version: str = Field(min_length=1)
    release_date: date
    target: CanonicalEntity
    disease: CanonicalEntity
    datatype_id: str = Field(min_length=1)
    datasource_id: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=1)
    first_observed_release: str = Field(min_length=1)
    first_observed_on: date
    first_observation_left_censored: bool
    source_parquet_url: HttpUrl
    association_url: HttpUrl
    raw_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1)
    field_map: dict[str, str] = Field(min_length=1)


class HistoricalEvidenceSnapshot(StrictModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    id: StableId
    scope: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    releases: list[ArchiveRelease] = Field(min_length=2)
    mappings: list[EntityMapping]
    unresolved_entities: list[UnresolvedEntity]
    records: list[ReleaseAssociation]

    @model_validator(mode="after")
    def validate_release_membership(self) -> "HistoricalEvidenceSnapshot":
        release_dates = [release.release_date for release in self.releases]
        if release_dates != sorted(release_dates) or len(release_dates) != len(set(release_dates)):
            raise ValueError("historical releases must have unique, ascending dates")
        release_by_id = {release.id: release for release in self.releases}
        if len(release_by_id) != len(self.releases):
            raise ValueError("historical release IDs must be unique")
        ids = [record.id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("release association IDs must be unique")
        membership_observations = [
            (record.release_id, record.membership_key) for record in self.records
        ]
        if len(membership_observations) != len(set(membership_observations)):
            raise ValueError("membership may occur only once in a release")
        for record in self.records:
            release = release_by_id.get(record.release_id)
            if release is None:
                raise ValueError(f"record {record.id} references an unknown release")
            if (record.release_version, record.release_date) != (
                release.version,
                release.release_date,
            ):
                raise ValueError(f"record {record.id} release metadata is inconsistent")
            if record.first_observed_on > record.release_date:
                raise ValueError(f"record {record.id} is observed before its first observation")
            source_urls = {str(item.url) for item in release.archive_files}
            if str(record.source_parquet_url) not in source_urls:
                raise ValueError(f"record {record.id} references an unmanifested Parquet file")
        if any(mapping.snapshot_id != self.id for mapping in self.mappings):
            raise ValueError("entity mappings must reference the historical snapshot")
        counts = Counter(record.release_id for record in self.records)
        for release in self.releases:
            if counts[release.id] != release.subset_row_count:
                raise ValueError(f"release {release.version} subset count is inconsistent")
        return self


class HistoricalRawArtifact(StrictModel):
    release_version: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HistoricalBuildManifest(StrictModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    snapshot_id: StableId
    raw_artifacts: list[HistoricalRawArtifact] = Field(min_length=2)
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: str = Field(min_length=1)
    release_count: int = Field(ge=2)
    normalized_record_count: int = Field(ge=0)


class AssociationChange(StrictModel):
    membership_key: StableId
    earlier_score: float
    later_score: float
    earlier_evidence_count: int
    later_evidence_count: int


class HistoricalAssociationDiff(StrictModel):
    earlier_date: date
    later_date: date
    earlier_release: str | None
    later_release: str | None
    added_membership_keys: list[StableId]
    removed_membership_keys: list[StableId]
    changed: list[AssociationChange]


class HistoricalQueryResult(StrictModel):
    snapshot_id: StableId
    disease_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    as_of_date: date
    selected_release: str | None
    selected_release_date: date | None
    records: list[ReleaseAssociation]
    post_cutoff_leakage_count: int = Field(ge=0)
    retrospective_valid: bool
    warning: str = Field(min_length=1)
