"""Evidence-string and trial-level historical store for P1.3."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.evidence.clinical_models import (
    AACTTrialRelease,
    ChEMBLDrugMetadata,
    ChEMBLEvidenceRelease,
    ClinicalEvidenceString,
    ClinicalHistoryDiff,
    ClinicalHistoryManifest,
    ClinicalHistoryQueryResult,
    ClinicalHistorySnapshot,
    ClinicalRawArtifact,
    CurrentTrialValidation,
    EvidenceStringChange,
    HistoricalTrialRecord,
    TrialStatusChange,
)
from targetideator.evidence.models import CanonicalEntity, EntityMapping
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ingestion.clinical_sources import CLINICAL_ADAPTER_VERSION
from targetideator.io import write_json
from targetideator.normalization.entities import default_resolver

SNAPSHOT_ID = "ti:snapshot:clinical-history-25.03-25.09-crohns-4-targets"


def default_clinical_raw_paths() -> list[Path]:
    names = (
        "chembl_25_03_evidence_raw.json",
        "chembl_25_09_evidence_raw.json",
        "aact_20250301_trials_raw.json",
        "aact_20250901_trials_raw.json",
        "chembl_molecules_current_raw.json",
        "ctgov_trials_current_raw.json",
    )
    return [fixture_path(name) for name in names]


def default_clinical_snapshot_path() -> Path:
    return fixture_path("clinical_history_snapshot.json")


def default_clinical_manifest_path() -> Path:
    return fixture_path("clinical_history_manifest.json")


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"unsupported source date: {value!r}") from exc


def _canonical_entity(value: str, entity_type: str) -> CanonicalEntity:
    result = default_resolver().resolve(value, entity_type, SNAPSHOT_ID)
    if not isinstance(result, EntityMapping):
        raise ValueError(f"unresolved {entity_type}: {value}")
    return result.canonical


def _drug_entity(
    identifier: str,
    molecule_by_id: dict[str, dict[str, Any]],
    *,
    current_label: bool = False,
) -> CanonicalEntity:
    payload = molecule_by_id[identifier]["payload"]
    return CanonicalEntity(
        entity_type="drug",
        namespace="ChEMBL",
        identifier=identifier,
        label=(payload.get("pref_name") or identifier) if current_label else identifier,
    )


def _trial_entity(identifier: str) -> CanonicalEntity:
    return CanonicalEntity(
        entity_type="trial",
        namespace="ClinicalTrials.gov",
        identifier=identifier,
        label=identifier,
    )


def _normalize_clinical_captures(
    chembl_captures: list[dict[str, Any]],
    aact_captures: list[dict[str, Any]],
    molecule_capture: dict[str, Any],
    ctgov_capture: dict[str, Any],
    raw_sha_by_key: dict[tuple[str, str], str],
) -> ClinicalHistorySnapshot:
    if len(chembl_captures) < 2 or len(aact_captures) < 2:
        raise ValueError("two ChEMBL evidence releases and two AACT snapshots are required")
    chembl_captures.sort(key=lambda item: item["release_date"])
    aact_captures.sort(key=lambda item: item["snapshot_date"])
    molecule_by_id = {
        item["payload"]["molecule_chembl_id"]: item
        for item in molecule_capture["molecules"]
    }

    first_evidence: dict[str, tuple[str, date]] = {}
    for capture in chembl_captures:
        observed_on = date.fromisoformat(capture["release_date"])
        for row in capture["rows"]:
            first_evidence.setdefault(row["id"], (capture["release_version"], observed_on))
    earliest_chembl = date.fromisoformat(chembl_captures[0]["release_date"])

    chembl_releases: list[ChEMBLEvidenceRelease] = []
    evidence_records: list[ClinicalEvidenceString] = []
    for capture in chembl_captures:
        version = capture["release_version"]
        release_date = date.fromisoformat(capture["release_date"])
        release_id = stable_id("release", f"opentargets-chembl-{version}")
        files_manifest = capture["archive_files"]
        chembl_releases.append(
            ChEMBLEvidenceRelease(
                id=release_id,
                version=version,
                release_date=release_date,
                archive_url=capture["archive_url"],
                captured_at=capture["captured_at"],
                raw_sha256=raw_sha_by_key[("chembl_evidence", version)],
                query_sha256=capture["query_sha256"],
                archive_files=files_manifest,
                dataset_row_count=capture["dataset_row_count"],
                subset_row_count=len(capture["rows"]),
                complete_for_query=capture["complete_for_query"],
            )
        )
        for row in capture["rows"]:
            source_id = row["id"]
            trial_id = row["studyId"]
            first_version, first_on = first_evidence[source_id]
            urls = [item["url"] for item in row.get("urls") or []]
            if not urls:
                urls = [f"https://clinicaltrials.gov/study/{trial_id}"]
            raw_hash = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            evidence_records.append(
                ClinicalEvidenceString(
                    id=stable_id("clinical-evidence", f"{version}-{source_id}"),
                    membership_key=stable_id("evidence-membership", source_id),
                    source_evidence_id=source_id,
                    release_id=release_id,
                    release_version=version,
                    release_date=release_date,
                    target=_canonical_entity(row["targetId"], "gene"),
                    disease=_canonical_entity(row["diseaseId"], "disease"),
                    drug=_drug_entity(row["drugId"], molecule_by_id),
                    trial=_trial_entity(trial_id),
                    datatype_id=row["datatypeId"],
                    datasource_id="chembl",
                    clinical_phase=row.get("clinicalPhase"),
                    clinical_status=row.get("clinicalStatus"),
                    study_start_date=_date(row.get("studyStartDate")),
                    study_stop_reason=row.get("studyStopReason"),
                    score=float(row["score"]),
                    source_urls=urls,
                    first_observed_release=first_version,
                    first_observed_on=first_on,
                    first_observation_left_censored=first_on == earliest_chembl,
                    source_parquet_url=row["sourceParquetUrl"],
                    raw_row_sha256=raw_hash,
                    transform_version=CLINICAL_ADAPTER_VERSION,
                    field_map={
                        "source_evidence_id": "$.id",
                        "target": "$.targetId",
                        "disease": "$.diseaseId",
                        "drug": "$.drugId",
                        "trial": "$.studyId",
                        "clinical_phase": "$.clinicalPhase",
                        "clinical_status": "$.clinicalStatus",
                        "study_start_date": "$.studyStartDate",
                        "study_stop_reason": "$.studyStopReason",
                        "score": "$.score",
                        "release_date": "capture.release_date",
                    },
                )
            )

    first_trial: dict[str, tuple[str, date]] = {}
    for capture in aact_captures:
        observed_on = date.fromisoformat(capture["snapshot_date"])
        for row in capture["rows"]:
            first_trial.setdefault(row["nct_id"], (capture["snapshot_version"], observed_on))
    earliest_aact = date.fromisoformat(aact_captures[0]["snapshot_date"])
    aact_releases: list[AACTTrialRelease] = []
    trial_records: list[HistoricalTrialRecord] = []
    for capture in aact_captures:
        version = capture["snapshot_version"]
        snapshot_date = date.fromisoformat(capture["snapshot_date"])
        release_id = stable_id("release", f"aact-{version}")
        entry = capture["entry"]
        aact_releases.append(
            AACTTrialRelease(
                id=release_id,
                version=version,
                snapshot_date=snapshot_date,
                archive_url=capture["archive_url"],
                captured_at=capture["captured_at"],
                raw_sha256=raw_sha_by_key[("aact", version)],
                archive_size_bytes=capture["archive_size_bytes"],
                archive_etag=capture.get("archive_etag"),
                archive_last_modified=capture.get("archive_last_modified"),
                entry_name=entry["name"],
                entry_crc32=entry["crc32"],
                entry_compressed_size_bytes=entry["compressed_size_bytes"],
                entry_uncompressed_size_bytes=entry["uncompressed_size_bytes"],
                dataset_row_count=capture["dataset_row_count"],
                subset_row_count=len(capture["rows"]),
                complete_for_query=capture["complete_for_query"],
            )
        )
        for row in capture["rows"]:
            nct_id = row["nct_id"]
            first_version, first_on = first_trial[nct_id]
            first_posted = _date(row.get("study_first_posted_date"))
            if first_posted is None:
                raise ValueError(f"AACT trial {nct_id} has no first-posted date")
            raw_hash = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
            trial_records.append(
                HistoricalTrialRecord(
                    id=stable_id("trial-observation", f"{version}-{nct_id}"),
                    membership_key=stable_id("trial", nct_id),
                    release_id=release_id,
                    snapshot_version=version,
                    snapshot_date=snapshot_date,
                    trial=_trial_entity(nct_id),
                    brief_title=row.get("brief_title") or nct_id,
                    official_title=row.get("official_title") or None,
                    study_type=row.get("study_type") or "UNKNOWN",
                    overall_status=row.get("overall_status") or "UNKNOWN",
                    last_known_status=row.get("last_known_status") or None,
                    phase=row.get("phase") or None,
                    enrollment=int(row["enrollment"]) if row.get("enrollment") else None,
                    enrollment_type=row.get("enrollment_type") or None,
                    sponsor=row.get("source") or None,
                    why_stopped=row.get("why_stopped") or None,
                    study_first_submitted_date=_date(row.get("study_first_submitted_date")),
                    study_first_posted_date=first_posted,
                    results_first_posted_date=_date(row.get("results_first_posted_date")),
                    last_update_submitted_date=_date(row.get("last_update_submitted_date")),
                    last_update_posted_date=_date(row.get("last_update_posted_date")),
                    start_date=_date(row.get("start_date")),
                    primary_completion_date=_date(row.get("primary_completion_date")),
                    completion_date=_date(row.get("completion_date")),
                    first_observed_snapshot=first_version,
                    first_observed_on=first_on,
                    first_observation_left_censored=first_on == earliest_aact,
                    source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                    raw_row_sha256=raw_hash,
                    transform_version=CLINICAL_ADAPTER_VERSION,
                    field_map={
                        "trial": "$.nct_id",
                        "brief_title": "$.brief_title",
                        "overall_status": "$.overall_status",
                        "phase": "$.phase",
                        "enrollment": "$.enrollment",
                        "study_first_posted_date": "$.study_first_posted_date",
                        "last_update_posted_date": "$.last_update_posted_date",
                        "snapshot_date": "capture.snapshot_date",
                    },
                )
            )

    drug_metadata: list[ChEMBLDrugMetadata] = []
    chembl_status = molecule_capture["database_status"]["payload"]
    for identifier in sorted(molecule_by_id):
        item = molecule_by_id[identifier]
        payload = item["payload"]
        drug_metadata.append(
            ChEMBLDrugMetadata(
                drug=_drug_entity(identifier, molecule_by_id, current_label=True),
                captured_at=molecule_capture["captured_at"],
                source_version=chembl_status["chembl_db_version"],
                source_release_date=chembl_status["chembl_release_date"],
                molecule_type=payload.get("molecule_type"),
                max_phase=float(payload["max_phase"]) if payload.get("max_phase") is not None else None,
                first_approval_year=payload.get("first_approval"),
                therapeutic_flag=payload.get("therapeutic_flag"),
                withdrawn_flag=payload.get("withdrawn_flag"),
                api_url=item["url"],
                raw_payload_sha256=item["payload_sha256"],
            )
        )

    current_trial_validations: list[CurrentTrialValidation] = []
    ctgov_status = ctgov_capture["api_status"]["payload"]
    for item in ctgov_capture["studies"]:
        payload = item["payload"]
        protocol = payload["protocolSection"]
        identification = protocol["identificationModule"]
        status = protocol.get("statusModule", {})
        nct_id = identification["nctId"]
        first_posted = _date((status.get("studyFirstPostDateStruct") or {}).get("date"))
        if first_posted is None:
            raise ValueError(f"ClinicalTrials.gov trial {nct_id} has no first-posted date")
        current_trial_validations.append(
            CurrentTrialValidation(
                trial=_trial_entity(nct_id),
                captured_at=ctgov_capture["captured_at"],
                api_version=ctgov_status["apiVersion"],
                data_timestamp=ctgov_status["dataTimestamp"],
                first_posted_date=first_posted,
                current_last_update_posted_date=_date(
                    (status.get("lastUpdatePostDateStruct") or {}).get("date")
                ),
                current_overall_status=status.get("overallStatus"),
                api_url=item["url"],
                raw_payload_sha256=item["payload_sha256"],
            )
        )

    return ClinicalHistorySnapshot(
        id=SNAPSHOT_ID,
        scope="Crohn disease × IL23A/JAK1/TNFSF15/NOD2; evidence strings and linked trials",
        adapter_version=CLINICAL_ADAPTER_VERSION,
        chembl_releases=chembl_releases,
        aact_releases=aact_releases,
        evidence_records=sorted(
            evidence_records, key=lambda item: (item.release_date, item.membership_key)
        ),
        trial_records=sorted(
            trial_records, key=lambda item: (item.snapshot_date, item.membership_key)
        ),
        drug_metadata=drug_metadata,
        current_trial_validations=sorted(
            current_trial_validations, key=lambda item: item.trial.identifier
        ),
    )


def build_clinical_history_snapshot(
    raw_paths: list[Path],
    snapshot_path: Path,
    manifest_path: Path,
) -> tuple[ClinicalHistorySnapshot, ClinicalHistoryManifest]:
    if len(raw_paths) != 6:
        raise ValueError("exactly six P1.3 raw artifacts are required")
    payloads = [_load_json(path) for path in raw_paths]
    chembl = [item for item in payloads if "release_version" in item]
    aact = [item for item in payloads if "snapshot_version" in item]
    molecule = next(item for item in payloads if "molecules" in item)
    ctgov = next(item for item in payloads if "studies" in item)
    sha_by_path = {path.name: file_sha256(path) for path in raw_paths}
    raw_sha_by_key = {
        **{
            ("chembl_evidence", item["release_version"]): sha_by_path[path.name]
            for path, item in zip(raw_paths, payloads, strict=True)
            if "release_version" in item
        },
        **{
            ("aact", item["snapshot_version"]): sha_by_path[path.name]
            for path, item in zip(raw_paths, payloads, strict=True)
            if "snapshot_version" in item
        },
    }
    snapshot = _normalize_clinical_captures(chembl, aact, molecule, ctgov, raw_sha_by_key)
    write_json(snapshot_path, snapshot.model_dump(mode="json"))

    artifacts: list[ClinicalRawArtifact] = []
    for path, item in zip(raw_paths, payloads, strict=True):
        if "release_version" in item:
            source, version = "chembl_evidence", item["release_version"]
        elif "snapshot_version" in item:
            source, version = "aact", item["snapshot_version"]
        elif "molecules" in item:
            source, version = "chembl_api", item["captured_at"]
        else:
            source, version = "ctgov_api", item["captured_at"]
        artifacts.append(
            ClinicalRawArtifact(
                source=source,
                version=version,
                path=path.name,
                sha256=sha_by_path[path.name],
            )
        )
    manifest = ClinicalHistoryManifest(
        snapshot_id=snapshot.id,
        raw_artifacts=sorted(artifacts, key=lambda item: (item.source, item.version)),
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        adapter_version=snapshot.adapter_version,
        chembl_release_count=len(snapshot.chembl_releases),
        aact_release_count=len(snapshot.aact_releases),
        evidence_observation_count=len(snapshot.evidence_records),
        trial_observation_count=len(snapshot.trial_records),
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    return snapshot, manifest


class ClinicalHistoryStore:
    def __init__(
        self,
        snapshot: ClinicalHistorySnapshot,
        raw_payloads: list[dict[str, Any]] | None = None,
        manifest: ClinicalHistoryManifest | None = None,
        raw_paths: list[Path] | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.raw_payloads = raw_payloads or []
        self.manifest = manifest
        self.raw_paths = raw_paths or []
        self.snapshot_path = snapshot_path
        self._resolver = default_resolver()
        self._raw_evidence: dict[tuple[str, str], dict[str, Any]] = {}
        self._raw_trials: dict[tuple[str, str], dict[str, Any]] = {}
        for payload in self.raw_payloads:
            if "release_version" in payload:
                for row in payload["rows"]:
                    self._raw_evidence[(payload["release_version"], row["id"])] = row
            elif "snapshot_version" in payload:
                for row in payload["rows"]:
                    self._raw_trials[(payload["snapshot_version"], row["nct_id"])] = row

    @classmethod
    def load(
        cls,
        snapshot_path: Path,
        raw_paths: list[Path] | None = None,
        manifest_path: Path | None = None,
    ) -> "ClinicalHistoryStore":
        try:
            snapshot = ClinicalHistorySnapshot.model_validate(_load_json(snapshot_path))
            payloads = [_load_json(path) for path in raw_paths or []]
            manifest = (
                ClinicalHistoryManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid clinical-history artifact: {exc}") from exc
        return cls(snapshot, payloads, manifest, raw_paths, snapshot_path)

    def _canonical_id(self, value: str, entity_type: str) -> str | None:
        result = self._resolver.resolve(value, entity_type, self.snapshot.id)
        return result.canonical.identifier if isinstance(result, EntityMapping) else None

    def query(self, disease_id: str, target_id: str, as_of_date: date) -> ClinicalHistoryQueryResult:
        disease = self._canonical_id(disease_id, "disease") or disease_id
        target = self._canonical_id(target_id, "gene") or target_id
        chembl_candidates = [
            release for release in self.snapshot.chembl_releases if release.release_date <= as_of_date
        ]
        aact_candidates = [
            release for release in self.snapshot.aact_releases if release.snapshot_date <= as_of_date
        ]
        chembl_release = chembl_candidates[-1] if chembl_candidates else None
        aact_release = aact_candidates[-1] if aact_candidates else None
        evidence = (
            [
                item
                for item in self.snapshot.evidence_records
                if item.release_id == chembl_release.id
                and item.disease.identifier == disease
                and item.target.identifier == target
            ]
            if chembl_release
            else []
        )
        linked_trials = {item.trial.identifier for item in evidence}
        trials = (
            [
                item
                for item in self.snapshot.trial_records
                if item.release_id == aact_release.id and item.trial.identifier in linked_trials
            ]
            if aact_release
            else []
        )
        leakage = sum(item.release_date > as_of_date for item in evidence) + sum(
            item.snapshot_date > as_of_date or item.study_first_posted_date > as_of_date
            for item in trials
        )
        complete = bool(
            chembl_release
            and aact_release
            and chembl_release.complete_for_query
            and aact_release.complete_for_query
        )
        if not chembl_release or not aact_release:
            warning = "No paired ChEMBL evidence release and AACT snapshot exist on or before cutoff."
        else:
            warning = (
                f"Evidence uses Open Targets {chembl_release.version} archived ChEMBL strings; "
                f"trial fields use AACT {aact_release.version}. Current API metadata is excluded."
            )
        return ClinicalHistoryQueryResult(
            snapshot_id=self.snapshot.id,
            disease_id=disease,
            target_id=target,
            as_of_date=as_of_date,
            selected_chembl_release=chembl_release.version if chembl_release else None,
            selected_chembl_release_date=chembl_release.release_date if chembl_release else None,
            selected_aact_snapshot=aact_release.version if aact_release else None,
            selected_aact_snapshot_date=aact_release.snapshot_date if aact_release else None,
            evidence_records=sorted(evidence, key=lambda item: item.membership_key),
            trial_records=sorted(trials, key=lambda item: item.membership_key),
            post_cutoff_leakage_count=leakage,
            retrospective_valid=complete and leakage == 0,
            warning=warning,
        )

    def diff(
        self,
        disease_id: str,
        target_id: str,
        earlier_date: date,
        later_date: date,
    ) -> ClinicalHistoryDiff:
        earlier_result = self.query(disease_id, target_id, earlier_date)
        later_result = self.query(disease_id, target_id, later_date)
        earlier_evidence = {item.membership_key: item for item in earlier_result.evidence_records}
        later_evidence = {item.membership_key: item for item in later_result.evidence_records}
        shared_evidence = sorted(earlier_evidence.keys() & later_evidence.keys())
        changed_evidence = [
            EvidenceStringChange(
                membership_key=key,
                earlier_status=earlier_evidence[key].clinical_status,
                later_status=later_evidence[key].clinical_status,
                earlier_phase=earlier_evidence[key].clinical_phase,
                later_phase=later_evidence[key].clinical_phase,
                earlier_score=earlier_evidence[key].score,
                later_score=later_evidence[key].score,
            )
            for key in shared_evidence
            if (
                earlier_evidence[key].clinical_status,
                earlier_evidence[key].clinical_phase,
                earlier_evidence[key].score,
            )
            != (
                later_evidence[key].clinical_status,
                later_evidence[key].clinical_phase,
                later_evidence[key].score,
            )
        ]
        earlier_trials = {item.membership_key: item for item in earlier_result.trial_records}
        later_trials = {item.membership_key: item for item in later_result.trial_records}
        shared_trials = sorted(earlier_trials.keys() & later_trials.keys())
        changed_trials = [
            TrialStatusChange(
                membership_key=key,
                nct_id=earlier_trials[key].trial.identifier,
                earlier_status=earlier_trials[key].overall_status,
                later_status=later_trials[key].overall_status,
                earlier_last_update_posted_date=earlier_trials[key].last_update_posted_date,
                later_last_update_posted_date=later_trials[key].last_update_posted_date,
            )
            for key in shared_trials
            if (
                earlier_trials[key].overall_status,
                earlier_trials[key].last_update_posted_date,
            )
            != (
                later_trials[key].overall_status,
                later_trials[key].last_update_posted_date,
            )
        ]
        return ClinicalHistoryDiff(
            earlier_date=earlier_date,
            later_date=later_date,
            earlier_chembl_release=earlier_result.selected_chembl_release,
            later_chembl_release=later_result.selected_chembl_release,
            earlier_aact_snapshot=earlier_result.selected_aact_snapshot,
            later_aact_snapshot=later_result.selected_aact_snapshot,
            added_evidence_keys=sorted(later_evidence.keys() - earlier_evidence.keys()),
            removed_evidence_keys=sorted(earlier_evidence.keys() - later_evidence.keys()),
            changed_evidence=changed_evidence,
            added_trial_keys=sorted(later_trials.keys() - earlier_trials.keys()),
            removed_trial_keys=sorted(earlier_trials.keys() - later_trials.keys()),
            changed_trials=changed_trials,
        )

    def raw_evidence(self, record_id: str) -> dict[str, Any] | None:
        record = next((item for item in self.snapshot.evidence_records if item.id == record_id), None)
        return (
            self._raw_evidence.get((record.release_version, record.source_evidence_id))
            if record
            else None
        )

    def raw_trial(self, record_id: str) -> dict[str, Any] | None:
        record = next((item for item in self.snapshot.trial_records if item.id == record_id), None)
        return (
            self._raw_trials.get((record.snapshot_version, record.trial.identifier))
            if record
            else None
        )

    def quality_report(self) -> dict[str, Any]:
        evidence_memberships = {item.membership_key for item in self.snapshot.evidence_records}
        trial_memberships = {item.membership_key for item in self.snapshot.trial_records}
        linked_trials = {item.trial.identifier for item in self.snapshot.evidence_records}
        historical_trials = {item.trial.identifier for item in self.snapshot.trial_records}
        current_trials = {
            item.trial.identifier for item in self.snapshot.current_trial_validations
        }
        evidence_drugs = {item.drug.identifier for item in self.snapshot.evidence_records}
        metadata_drugs = {item.drug.identifier for item in self.snapshot.drug_metadata}
        first_posted_current = {
            item.trial.identifier: item.first_posted_date
            for item in self.snapshot.current_trial_validations
        }
        first_posted_aact: dict[str, date] = {}
        for item in self.snapshot.trial_records:
            first_posted_aact.setdefault(item.trial.identifier, item.study_first_posted_date)
        first_posted_mismatches = sorted(
            identifier
            for identifier in linked_trials
            if first_posted_current.get(identifier) != first_posted_aact.get(identifier)
        )
        earliest = min(item.release_date for item in self.snapshot.chembl_releases)
        canaries = [
            self.query("MONDO:0005011", target, cutoff)
            for cutoff in (
                earliest - timedelta(days=1),
                *(item.release_date for item in self.snapshot.chembl_releases),
            )
            for target in ("IL23A", "JAK1", "TNFSF15", "NOD2")
        ]
        panel_diffs = [
            self.diff(
                "MONDO:0005011",
                target,
                date(2025, 3, 19),
                date(2025, 9, 17),
            )
            for target in ("IL23A", "JAK1", "TNFSF15", "NOD2")
        ]
        sources_complete = all(
            item.complete_for_query
            for item in [*self.snapshot.chembl_releases, *self.snapshot.aact_releases]
        )
        historical_trial_coverage = (
            len(linked_trials & historical_trials) / len(linked_trials) if linked_trials else 1.0
        )
        ctgov_coverage = (
            len(linked_trials & current_trials) / len(linked_trials) if linked_trials else 1.0
        )
        report: dict[str, Any] = {
            "snapshot_id": self.snapshot.id,
            "chembl_release_count": len(self.snapshot.chembl_releases),
            "aact_release_count": len(self.snapshot.aact_releases),
            "chembl_release_versions": [item.version for item in self.snapshot.chembl_releases],
            "aact_snapshot_versions": [item.version for item in self.snapshot.aact_releases],
            "evidence_observations": len(self.snapshot.evidence_records),
            "evidence_memberships": len(evidence_memberships),
            "trial_observations": len(self.snapshot.trial_records),
            "trial_memberships": len(trial_memberships),
            "all_release_queries_complete": sources_complete,
            "evidence_to_historical_trial_coverage": historical_trial_coverage,
            "ctgov_identifier_validation_coverage": ctgov_coverage,
            "chembl_drug_metadata_coverage": (
                len(evidence_drugs & metadata_drugs) / len(evidence_drugs)
                if evidence_drugs
                else 1.0
            ),
            "first_posted_mismatch_count": len(first_posted_mismatches),
            "first_posted_mismatch_ids": first_posted_mismatches,
            "post_cutoff_leakage_count": sum(
                item.post_cutoff_leakage_count for item in canaries
            ),
            "current_metadata_used_for_replay": False,
            "evidence_added_25_03_to_25_09": sum(
                len(item.added_evidence_keys) for item in panel_diffs
            ),
            "evidence_removed_25_03_to_25_09": sum(
                len(item.removed_evidence_keys) for item in panel_diffs
            ),
            "evidence_changed_25_03_to_25_09": sum(
                len(item.changed_evidence) for item in panel_diffs
            ),
            "linked_trial_changes_20250301_to_20250901": len(
                {
                    change.membership_key
                    for item in panel_diffs
                    for change in item.changed_trials
                }
            ),
            "retrospective_replay_enabled": (
                sources_complete
                and historical_trial_coverage == 1.0
                and ctgov_coverage == 1.0
                and not first_posted_mismatches
            ),
        }
        if self.manifest and self.raw_paths and self.snapshot_path:
            actual_by_name = {path.name: file_sha256(path) for path in self.raw_paths}
            raw_matches = all(
                actual_by_name.get(item.path) == item.sha256
                for item in self.manifest.raw_artifacts
            )
            normalized_matches = file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
            rebuilt, _ = _rebuild_in_memory(self.raw_paths)
            deterministic = canonical_json_bytes(rebuilt.model_dump(mode="json")) == canonical_json_bytes(
                self.snapshot.model_dump(mode="json")
            )
            report.update(
                {
                    "raw_checksums_match": raw_matches,
                    "normalized_checksum_matches": normalized_matches,
                    "deterministic_rebuild_matches": deterministic,
                }
            )
        return report


def _rebuild_in_memory(
    raw_paths: list[Path],
) -> tuple[ClinicalHistorySnapshot, dict[str, str]]:
    payloads = [_load_json(path) for path in raw_paths]
    chembl = [item for item in payloads if "release_version" in item]
    aact = [item for item in payloads if "snapshot_version" in item]
    molecule = next(item for item in payloads if "molecules" in item)
    ctgov = next(item for item in payloads if "studies" in item)
    sha_by_path = {path.name: file_sha256(path) for path in raw_paths}
    raw_sha_by_key: dict[tuple[str, str], str] = {}
    for path, item in zip(raw_paths, payloads, strict=True):
        if "release_version" in item:
            raw_sha_by_key[("chembl_evidence", item["release_version"])] = sha_by_path[path.name]
        elif "snapshot_version" in item:
            raw_sha_by_key[("aact", item["snapshot_version"])] = sha_by_path[path.name]
    return (
        _normalize_clinical_captures(chembl, aact, molecule, ctgov, raw_sha_by_key),
        sha_by_path,
    )


def load_default_clinical_store() -> ClinicalHistoryStore:
    return ClinicalHistoryStore.load(
        default_clinical_snapshot_path(),
        raw_paths=default_clinical_raw_paths(),
        manifest_path=default_clinical_manifest_path(),
    )
