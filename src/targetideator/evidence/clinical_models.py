"""Strict contracts for evidence-string and trial-level historical replay."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from targetideator.contracts.models import StableId
from targetideator.evidence.models import ArchiveFile, CanonicalEntity, StrictModel


class ChEMBLEvidenceRelease(StrictModel):
    id: StableId
    version: str = Field(min_length=1)
    release_date: date
    archive_url: HttpUrl
    captured_at: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_files: list[ArchiveFile] = Field(min_length=1)
    dataset_row_count: int = Field(gt=0)
    subset_row_count: int = Field(ge=0)
    complete_for_query: bool


class AACTTrialRelease(StrictModel):
    id: StableId
    version: str = Field(pattern=r"^\d{8}$")
    snapshot_date: date
    archive_url: HttpUrl
    captured_at: datetime
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_size_bytes: int = Field(gt=0)
    archive_etag: str | None = None
    archive_last_modified: str | None = None
    entry_name: Literal["studies.txt"]
    entry_crc32: str = Field(pattern=r"^[0-9a-f]{8}$")
    entry_compressed_size_bytes: int = Field(gt=0)
    entry_uncompressed_size_bytes: int = Field(gt=0)
    dataset_row_count: int = Field(gt=0)
    subset_row_count: int = Field(ge=0)
    complete_for_query: bool


class ClinicalEvidenceString(StrictModel):
    id: StableId
    membership_key: StableId
    source_evidence_id: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: StableId
    release_version: str = Field(min_length=1)
    release_date: date
    target: CanonicalEntity
    disease: CanonicalEntity
    drug: CanonicalEntity
    trial: CanonicalEntity
    datatype_id: str = Field(min_length=1)
    datasource_id: Literal["chembl"]
    clinical_phase: float | None = Field(default=None, ge=0, le=4)
    clinical_status: str | None = None
    study_start_date: date | None = None
    study_stop_reason: str | None = None
    score: float = Field(ge=0, le=1)
    source_urls: list[HttpUrl] = Field(min_length=1)
    first_observed_release: str = Field(min_length=1)
    first_observed_on: date
    first_observation_left_censored: bool
    source_parquet_url: HttpUrl
    raw_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1)
    field_map: dict[str, str] = Field(min_length=1)


class HistoricalTrialRecord(StrictModel):
    id: StableId
    membership_key: StableId
    release_id: StableId
    snapshot_version: str = Field(pattern=r"^\d{8}$")
    snapshot_date: date
    trial: CanonicalEntity
    brief_title: str = Field(min_length=1)
    official_title: str | None = None
    study_type: str = Field(min_length=1)
    overall_status: str = Field(min_length=1)
    last_known_status: str | None = None
    phase: str | None = None
    enrollment: int | None = Field(default=None, ge=0)
    enrollment_type: str | None = None
    sponsor: str | None = None
    why_stopped: str | None = None
    study_first_submitted_date: date | None = None
    study_first_posted_date: date
    results_first_posted_date: date | None = None
    last_update_submitted_date: date | None = None
    last_update_posted_date: date | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    completion_date: date | None = None
    first_observed_snapshot: str = Field(pattern=r"^\d{8}$")
    first_observed_on: date
    first_observation_left_censored: bool
    source_url: HttpUrl
    raw_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1)
    field_map: dict[str, str] = Field(min_length=1)


class ChEMBLDrugMetadata(StrictModel):
    drug: CanonicalEntity
    captured_at: datetime
    source_version: str = Field(min_length=1)
    source_release_date: date
    molecule_type: str | None = None
    max_phase: float | None = Field(default=None, ge=0, le=4)
    first_approval_year: int | None = Field(default=None, ge=1900, le=2200)
    therapeutic_flag: bool | None = None
    withdrawn_flag: bool | None = None
    api_url: HttpUrl
    raw_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_use_allowed: Literal[False] = False


class CurrentTrialValidation(StrictModel):
    trial: CanonicalEntity
    captured_at: datetime
    api_version: str = Field(min_length=1)
    data_timestamp: datetime
    first_posted_date: date
    current_last_update_posted_date: date | None = None
    current_overall_status: str | None = None
    api_url: HttpUrl
    raw_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    historical_use_allowed: Literal[False] = False


class ClinicalHistorySnapshot(StrictModel):
    schema_version: Literal["3.0.0"] = "3.0.0"
    id: StableId
    scope: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    chembl_releases: list[ChEMBLEvidenceRelease] = Field(min_length=2)
    aact_releases: list[AACTTrialRelease] = Field(min_length=2)
    evidence_records: list[ClinicalEvidenceString]
    trial_records: list[HistoricalTrialRecord]
    drug_metadata: list[ChEMBLDrugMetadata]
    current_trial_validations: list[CurrentTrialValidation]

    @model_validator(mode="after")
    def validate_history(self) -> "ClinicalHistorySnapshot":
        chembl_dates = [item.release_date for item in self.chembl_releases]
        aact_dates = [item.snapshot_date for item in self.aact_releases]
        if chembl_dates != sorted(set(chembl_dates)):
            raise ValueError("ChEMBL evidence releases must have unique ascending dates")
        if aact_dates != sorted(set(aact_dates)):
            raise ValueError("AACT snapshots must have unique ascending dates")
        evidence_ids = [item.id for item in self.evidence_records]
        trial_ids = [item.id for item in self.trial_records]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("clinical evidence observation IDs must be unique")
        if len(trial_ids) != len(set(trial_ids)):
            raise ValueError("trial observation IDs must be unique")
        chembl_by_id = {item.id: item for item in self.chembl_releases}
        aact_by_id = {item.id: item for item in self.aact_releases}
        for item in self.evidence_records:
            release = chembl_by_id.get(item.release_id)
            if release is None or (item.release_version, item.release_date) != (
                release.version,
                release.release_date,
            ):
                raise ValueError(f"evidence {item.id} has inconsistent release metadata")
            if item.first_observed_on > item.release_date:
                raise ValueError(f"evidence {item.id} predates its first observation")
            manifested = {str(file.url) for file in release.archive_files}
            if str(item.source_parquet_url) not in manifested:
                raise ValueError(f"evidence {item.id} references an unmanifested Parquet file")
        for item in self.trial_records:
            release = aact_by_id.get(item.release_id)
            if release is None or (item.snapshot_version, item.snapshot_date) != (
                release.version,
                release.snapshot_date,
            ):
                raise ValueError(f"trial {item.id} has inconsistent snapshot metadata")
            if item.study_first_posted_date > item.snapshot_date:
                raise ValueError(f"trial {item.id} was not public at its AACT snapshot")
            availability_dates = (
                item.study_first_submitted_date,
                item.results_first_posted_date,
                item.last_update_submitted_date,
                item.last_update_posted_date,
            )
            if any(value and value > item.snapshot_date for value in availability_dates):
                raise ValueError(f"trial {item.id} contains a post-snapshot registry date")
        evidence_counts = Counter(item.release_id for item in self.evidence_records)
        trial_counts = Counter(item.release_id for item in self.trial_records)
        if any(evidence_counts[item.id] != item.subset_row_count for item in self.chembl_releases):
            raise ValueError("ChEMBL release subset counts are inconsistent")
        if any(trial_counts[item.id] != item.subset_row_count for item in self.aact_releases):
            raise ValueError("AACT release subset counts are inconsistent")
        evidence_trials = {item.trial.identifier for item in self.evidence_records}
        trial_memberships = {item.trial.identifier for item in self.trial_records}
        if not evidence_trials <= trial_memberships:
            raise ValueError("one or more evidence strings have no historical AACT trial row")
        return self


class ClinicalRawArtifact(StrictModel):
    source: Literal["chembl_evidence", "aact", "chembl_api", "ctgov_api"]
    version: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClinicalHistoryManifest(StrictModel):
    schema_version: Literal["3.0.0"] = "3.0.0"
    snapshot_id: StableId
    raw_artifacts: list[ClinicalRawArtifact] = Field(min_length=6)
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: str = Field(min_length=1)
    chembl_release_count: int = Field(ge=2)
    aact_release_count: int = Field(ge=2)
    evidence_observation_count: int = Field(ge=0)
    trial_observation_count: int = Field(ge=0)


class ClinicalHistoryQueryResult(StrictModel):
    snapshot_id: StableId
    disease_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    as_of_date: date
    selected_chembl_release: str | None
    selected_chembl_release_date: date | None
    selected_aact_snapshot: str | None
    selected_aact_snapshot_date: date | None
    evidence_records: list[ClinicalEvidenceString]
    trial_records: list[HistoricalTrialRecord]
    post_cutoff_leakage_count: int = Field(ge=0)
    retrospective_valid: bool
    warning: str = Field(min_length=1)


class EvidenceStringChange(StrictModel):
    membership_key: StableId
    earlier_status: str | None
    later_status: str | None
    earlier_phase: float | None
    later_phase: float | None
    earlier_score: float
    later_score: float


class TrialStatusChange(StrictModel):
    membership_key: StableId
    nct_id: str = Field(pattern=r"^NCT\d{8}$")
    earlier_status: str
    later_status: str
    earlier_last_update_posted_date: date | None
    later_last_update_posted_date: date | None


class ClinicalHistoryDiff(StrictModel):
    earlier_date: date
    later_date: date
    earlier_chembl_release: str | None
    later_chembl_release: str | None
    earlier_aact_snapshot: str | None
    later_aact_snapshot: str | None
    added_evidence_keys: list[StableId]
    removed_evidence_keys: list[StableId]
    changed_evidence: list[EvidenceStringChange]
    added_trial_keys: list[StableId]
    removed_trial_keys: list[StableId]
    changed_trials: list[TrialStatusChange]
