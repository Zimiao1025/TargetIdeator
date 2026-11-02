"""Offline, replayable access to the frozen P1 evidence snapshot."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.evidence.models import (
    BuildManifest,
    EntityMapping,
    EvidenceDiff,
    EvidenceSnapshot,
    SnapshotMode,
    TemporalEvidence,
    TemporalQueryResult,
)
from targetideator.ids import canonical_json_bytes
from targetideator.ingestion.opentargets import normalize_capture
from targetideator.io import write_json
from targetideator.normalization.entities import default_resolver


def default_raw_path() -> Path:
    return fixture_path("opentargets_26_09_raw.json")


def default_snapshot_path() -> Path:
    return fixture_path("opentargets_26_09_snapshot.json")


def default_manifest_path() -> Path:
    return fixture_path("opentargets_26_09_manifest.json")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load P1 artifact {path}: {exc}") from exc


def build_snapshot(
    raw_path: Path,
    snapshot_path: Path,
    manifest_path: Path,
) -> tuple[EvidenceSnapshot, BuildManifest]:
    """Rebuild normalized output and its checksum manifest from saved raw data."""

    raw_sha = file_sha256(raw_path)
    capture = _load_json(raw_path)
    snapshot = normalize_capture(capture, raw_sha)
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = BuildManifest(
        snapshot_id=snapshot.source.id,
        raw_path=raw_path.name,
        normalized_path=snapshot_path.name,
        raw_sha256=raw_sha,
        normalized_sha256=file_sha256(snapshot_path),
        query_sha256=snapshot.source.query_sha256,
        adapter_version=snapshot.source.adapter_version,
        normalized_record_count=len(snapshot.records),
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    return snapshot, manifest


class EvidenceStore:
    def __init__(
        self,
        snapshot: EvidenceSnapshot,
        raw_capture: dict[str, Any] | None = None,
        manifest: BuildManifest | None = None,
        raw_path: Path | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.raw_capture = raw_capture
        self.manifest = manifest
        self.raw_path = raw_path
        self.snapshot_path = snapshot_path
        self._resolver = default_resolver()
        self._raw_by_id: dict[str, dict[str, Any]] = {}
        if raw_capture:
            disease = raw_capture.get("response", {}).get("data", {}).get("disease") or {}
            evidence = disease.get("evidences") or {}
            self._raw_by_id = {row["id"]: row for row in evidence.get("rows") or []}

    @classmethod
    def load(
        cls,
        snapshot_path: Path,
        raw_path: Path | None = None,
        manifest_path: Path | None = None,
    ) -> "EvidenceStore":
        try:
            snapshot = EvidenceSnapshot.model_validate(_load_json(snapshot_path))
            raw = _load_json(raw_path) if raw_path else None
            manifest = (
                BuildManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P1 evidence artifact: {exc}") from exc
        return cls(snapshot, raw, manifest, raw_path, snapshot_path)

    def _canonical_id(self, value: str, entity_type: str) -> str | None:
        result = self._resolver.resolve(value, entity_type, self.snapshot.source.id)
        if isinstance(result, EntityMapping):
            return result.canonical.identifier
        return None

    def query(
        self,
        disease_id: str,
        target_id: str,
        as_of_date: date,
    ) -> TemporalQueryResult:
        disease = self._canonical_id(disease_id, "disease") or disease_id
        target = self._canonical_id(target_id, "gene") or target_id
        candidates = [
            record
            for record in self.snapshot.records
            if record.disease.identifier == disease and record.target.identifier == target
        ]
        included = [record for record in candidates if record.available_on <= as_of_date]
        excluded = len(candidates) - len(included)
        leakage = sum(record.available_on > as_of_date for record in included)
        retrospective_valid = (
            self.snapshot.source.mode == SnapshotMode.HISTORICAL_RELEASE
            and self.snapshot.source.retrospective_claims_allowed
        )
        if retrospective_valid:
            warning = "Historical release boundary is valid for retrospective analysis."
            policy = "retrospective_analysis_allowed"
        else:
            warning = (
                "Engineering-only frozen current snapshot: event dates describe source records, "
                "but do not prove that those records were available before release 26.09."
            )
            policy = "engineering_demo_only"
        return TemporalQueryResult(
            snapshot_id=self.snapshot.source.id,
            disease_id=disease,
            target_id=target,
            as_of_date=as_of_date,
            records=included,
            excluded_post_cutoff_count=excluded,
            post_cutoff_leakage_count=leakage,
            retrospective_valid=retrospective_valid,
            use_policy=policy,
            warning=warning,
        )

    def diff(
        self,
        disease_id: str,
        target_id: str,
        earlier_date: date,
        later_date: date,
    ) -> EvidenceDiff:
        earlier = {r.id for r in self.query(disease_id, target_id, earlier_date).records}
        later = {r.id for r in self.query(disease_id, target_id, later_date).records}
        return EvidenceDiff(
            earlier_date=earlier_date,
            later_date=later_date,
            added_ids=sorted(later - earlier),
            removed_ids=sorted(earlier - later),
        )

    def raw_record(self, evidence_id: str) -> dict[str, Any] | None:
        record = next((item for item in self.snapshot.records if item.id == evidence_id), None)
        return self._raw_by_id.get(record.lineage.raw_record_id) if record else None

    def timeline(self, records: list[TemporalEvidence]) -> list[dict[str, Any]]:
        counts: dict[tuple[int | None, str], int] = defaultdict(int)
        for record in records:
            year = record.event_date.year if record.event_date else None
            counts[(year, record.datatype_id)] += 1
        return [
            {"year": year, "datatype_id": datatype, "count": count}
            for (year, datatype), count in sorted(
                counts.items(), key=lambda item: (item[0][0] is None, item[0][0] or 0, item[0][1])
            )
        ]

    def quality_report(self) -> dict[str, Any]:
        total = len(self.snapshot.records)
        lineage_count = sum(bool(record.lineage.field_map) for record in self.snapshot.records)
        url_count = sum(bool(record.source_urls) for record in self.snapshot.records)
        seed_metrics = self._resolver.seed_panel_metrics()
        release_eve = self.snapshot.source.release_date - timedelta(days=1)
        canary_results = [
            self.query("MONDO:0005011", target.identifier, release_eve)
            for target in {record.target.identifier: record.target for record in self.snapshot.records}.values()
        ]
        report: dict[str, Any] = {
            "snapshot_id": self.snapshot.source.id,
            "source_release": self.snapshot.source.release_version,
            "snapshot_mode": self.snapshot.source.mode.value,
            "retrospective_claims_allowed": self.snapshot.source.retrospective_claims_allowed,
            "record_count": total,
            "source_total_count": self.snapshot.source.source_total_count,
            "complete_for_query": self.snapshot.source.complete_for_query,
            "seed_panel_mapping_precision": seed_metrics["precision"],
            "seed_panel_mapping_correct": seed_metrics["correct"],
            "seed_panel_mapping_total": seed_metrics["total"],
            "lineage_coverage": lineage_count / total if total else 1.0,
            "source_url_coverage": url_count / total if total else 1.0,
            "unresolved_entity_count": len(self.snapshot.unresolved_entities),
            "post_cutoff_leakage_count": sum(
                result.post_cutoff_leakage_count for result in canary_results
            ),
        }
        if self.manifest and self.raw_path and self.snapshot_path:
            raw_matches = file_sha256(self.raw_path) == self.manifest.raw_sha256
            normalized_matches = (
                file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
            )
            rebuilt = normalize_capture(_load_json(self.raw_path), file_sha256(self.raw_path))
            deterministic = canonical_json_bytes(rebuilt.model_dump(mode="json")) == canonical_json_bytes(
                self.snapshot.model_dump(mode="json")
            )
            report.update(
                {
                    "raw_checksum_matches": raw_matches,
                    "normalized_checksum_matches": normalized_matches,
                    "deterministic_rebuild_matches": deterministic,
                }
            )
        return report

    def family_counts(self, records: list[TemporalEvidence]) -> dict[str, int]:
        return dict(sorted(Counter(record.datatype_id for record in records).items()))


def load_default_store() -> EvidenceStore:
    return EvidenceStore.load(
        default_snapshot_path(),
        raw_path=default_raw_path(),
        manifest_path=default_manifest_path(),
    )
