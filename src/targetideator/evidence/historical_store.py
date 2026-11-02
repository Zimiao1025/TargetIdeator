"""Release-membership store for archived Open Targets association snapshots."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.evidence.models import (
    AssociationChange,
    EntityMapping,
    HistoricalAssociationDiff,
    HistoricalBuildManifest,
    HistoricalEvidenceSnapshot,
    HistoricalQueryResult,
    HistoricalRawArtifact,
    ReleaseAssociation,
)
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes
from targetideator.ingestion.opentargets_archive import normalize_archived_captures
from targetideator.io import write_json
from targetideator.normalization.entities import default_resolver


def default_historical_raw_paths() -> list[Path]:
    return [
        fixture_path("opentargets_25_03_associations_raw.json"),
        fixture_path("opentargets_25_09_associations_raw.json"),
    ]


def default_historical_snapshot_path() -> Path:
    return fixture_path("opentargets_25_03_25_09_historical_snapshot.json")


def default_historical_manifest_path() -> Path:
    return fixture_path("opentargets_25_03_25_09_historical_manifest.json")


def build_historical_snapshot(
    raw_paths: list[Path],
    snapshot_path: Path,
    manifest_path: Path,
) -> tuple[HistoricalEvidenceSnapshot, HistoricalBuildManifest]:
    if len(raw_paths) < 2:
        raise ValueError("at least two raw archived releases are required")
    captures = [_load_json(path) for path in raw_paths]
    sha_by_release = {
        capture["release_version"]: file_sha256(path)
        for path, capture in zip(raw_paths, captures, strict=True)
    }
    snapshot = normalize_archived_captures(captures, sha_by_release)
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    artifacts = sorted(
        (
            HistoricalRawArtifact(
                release_version=capture["release_version"],
                path=path.name,
                sha256=sha_by_release[capture["release_version"]],
            )
            for path, capture in zip(raw_paths, captures, strict=True)
        ),
        key=lambda item: item.release_version,
    )
    manifest = HistoricalBuildManifest(
        snapshot_id=snapshot.id,
        raw_artifacts=artifacts,
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        query_sha256=snapshot.query_sha256,
        adapter_version=snapshot.adapter_version,
        release_count=len(snapshot.releases),
        normalized_record_count=len(snapshot.records),
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    return snapshot, manifest


class HistoricalEvidenceStore:
    def __init__(
        self,
        snapshot: HistoricalEvidenceSnapshot,
        raw_captures: list[dict[str, Any]] | None = None,
        manifest: HistoricalBuildManifest | None = None,
        raw_paths: list[Path] | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.raw_captures = raw_captures or []
        self.manifest = manifest
        self.raw_paths = raw_paths or []
        self.snapshot_path = snapshot_path
        self._resolver = default_resolver()
        self._raw_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for capture in self.raw_captures:
            version = capture["release_version"]
            for row in capture["rows"]:
                self._raw_by_key[(version, row["targetId"], row["datasourceId"])] = row

    @classmethod
    def load(
        cls,
        snapshot_path: Path,
        raw_paths: list[Path] | None = None,
        manifest_path: Path | None = None,
    ) -> "HistoricalEvidenceStore":
        try:
            snapshot = HistoricalEvidenceSnapshot.model_validate(_load_json(snapshot_path))
            raw_captures = [_load_json(path) for path in raw_paths or []]
            manifest = (
                HistoricalBuildManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid historical P1 artifact: {exc}") from exc
        return cls(snapshot, raw_captures, manifest, raw_paths, snapshot_path)

    def _canonical_id(self, value: str, entity_type: str) -> str | None:
        result = self._resolver.resolve(value, entity_type, self.snapshot.id)
        if isinstance(result, EntityMapping):
            return result.canonical.identifier
        return None

    def _release_as_of(self, as_of_date: date):
        eligible = [
            release for release in self.snapshot.releases if release.release_date <= as_of_date
        ]
        return eligible[-1] if eligible else None

    def query(
        self,
        disease_id: str,
        target_id: str,
        as_of_date: date,
    ) -> HistoricalQueryResult:
        disease = self._canonical_id(disease_id, "disease") or disease_id
        target = self._canonical_id(target_id, "gene") or target_id
        release = self._release_as_of(as_of_date)
        if release is None:
            records: list[ReleaseAssociation] = []
            warning = "No archived release exists on or before the requested cutoff."
            valid = False
        else:
            records = [
                record
                for record in self.snapshot.records
                if record.release_id == release.id
                and record.disease.identifier == disease
                and record.target.identifier == target
            ]
            warning = (
                f"Replay uses complete Open Targets {release.version} datasource-level direct "
                "association membership; rows are aggregated associations, not evidence strings."
            )
            valid = release.complete_for_query
        leakage = sum(record.release_date > as_of_date for record in records)
        return HistoricalQueryResult(
            snapshot_id=self.snapshot.id,
            disease_id=disease,
            target_id=target,
            as_of_date=as_of_date,
            selected_release=release.version if release else None,
            selected_release_date=release.release_date if release else None,
            records=sorted(records, key=lambda item: item.membership_key),
            post_cutoff_leakage_count=leakage,
            retrospective_valid=valid and leakage == 0,
            warning=warning,
        )

    def diff(
        self,
        disease_id: str,
        target_id: str,
        earlier_date: date,
        later_date: date,
    ) -> HistoricalAssociationDiff:
        earlier_result = self.query(disease_id, target_id, earlier_date)
        later_result = self.query(disease_id, target_id, later_date)
        earlier = {record.membership_key: record for record in earlier_result.records}
        later = {record.membership_key: record for record in later_result.records}
        shared = sorted(earlier.keys() & later.keys())
        changed = [
            AssociationChange(
                membership_key=key,
                earlier_score=earlier[key].score,
                later_score=later[key].score,
                earlier_evidence_count=earlier[key].evidence_count,
                later_evidence_count=later[key].evidence_count,
            )
            for key in shared
            if (
                earlier[key].score != later[key].score
                or earlier[key].evidence_count != later[key].evidence_count
            )
        ]
        return HistoricalAssociationDiff(
            earlier_date=earlier_date,
            later_date=later_date,
            earlier_release=earlier_result.selected_release,
            later_release=later_result.selected_release,
            added_membership_keys=sorted(later.keys() - earlier.keys()),
            removed_membership_keys=sorted(earlier.keys() - later.keys()),
            changed=changed,
        )

    def raw_record(self, record_id: str) -> dict[str, Any] | None:
        record = next((item for item in self.snapshot.records if item.id == record_id), None)
        if record is None:
            return None
        return self._raw_by_key.get(
            (record.release_version, record.target.identifier, record.datasource_id)
        )

    def release_summary(self) -> list[dict[str, Any]]:
        result = []
        for release in self.snapshot.releases:
            records = [r for r in self.snapshot.records if r.release_id == release.id]
            result.append(
                {
                    "version": release.version,
                    "release_date": release.release_date.isoformat(),
                    "dataset_row_count": release.dataset_row_count,
                    "subset_row_count": release.subset_row_count,
                    "archive_file_count": len(release.archive_files),
                    "evidence_count_sum": sum(record.evidence_count for record in records),
                    "complete_for_query": release.complete_for_query,
                }
            )
        return result

    def quality_report(self) -> dict[str, Any]:
        releases_complete = all(release.complete_for_query for release in self.snapshot.releases)
        total_files = sum(len(release.archive_files) for release in self.snapshot.releases)
        manifest_files = sum(
            bool(file.sha256 and file.size_bytes > 0)
            for release in self.snapshot.releases
            for file in release.archive_files
        )
        earliest = self.snapshot.releases[0].release_date
        canary_queries = [
            self.query("MONDO:0005011", target, earliest - timedelta(days=1))
            for target in ("IL23A", "JAK1", "TNFSF15", "NOD2")
        ]
        report: dict[str, Any] = {
            "snapshot_id": self.snapshot.id,
            "release_count": len(self.snapshot.releases),
            "release_versions": [release.version for release in self.snapshot.releases],
            "records": len(self.snapshot.records),
            "all_release_queries_complete": releases_complete,
            "archive_file_manifest_coverage": manifest_files / total_files if total_files else 1.0,
            "unresolved_entity_count": len(self.snapshot.unresolved_entities),
            "seed_panel_mapping_precision": self._resolver.seed_panel_metrics()["precision"],
            "post_cutoff_leakage_count": sum(
                query.post_cutoff_leakage_count for query in canary_queries
            ),
            "retrospective_replay_enabled": releases_complete,
        }
        if self.manifest and self.raw_paths and self.snapshot_path:
            actual_by_name = {path.name: file_sha256(path) for path in self.raw_paths}
            raw_matches = all(
                actual_by_name.get(artifact.path) == artifact.sha256
                for artifact in self.manifest.raw_artifacts
            )
            normalized_matches = (
                file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
            )
            captures = [_load_json(path) for path in self.raw_paths]
            sha_by_release = {
                capture["release_version"]: file_sha256(path)
                for path, capture in zip(self.raw_paths, captures, strict=True)
            }
            rebuilt = normalize_archived_captures(captures, sha_by_release)
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


def load_default_historical_store() -> HistoricalEvidenceStore:
    return HistoricalEvidenceStore.load(
        default_historical_snapshot_path(),
        raw_paths=default_historical_raw_paths(),
        manifest_path=default_historical_manifest_path(),
    )
