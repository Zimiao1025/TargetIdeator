"""Build P5.6 release-aware source-asserted trial→drug→target evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.outcomes.assertion_history_models import (
    AssertionHistoryManifest,
    AssertionHistoryQuality,
    AssertionHistorySnapshot,
)
from targetideator.outcomes.drug_identity_store import (
    default_drug_identity_manifest_path,
    load_default_drug_identity_store,
)
from targetideator.outcomes.identity_store import _read_gzip_json, _write_jsonl_gzip

BUILDER_VERSION = "p5.6-versioned-source-assertion-history-v1"
SNAPSHOT_ID = "ti:source-assertion-history:chembl-25-03-25-09-v1"
CREATED_AT = datetime(2026, 11, 2, 18, 30, tzinfo=timezone.utc)
RELEASES = ("25.03", "25.09")
RELEASE_DATES = {"25.03": "2025-03-19", "25.09": "2025-09-17"}
IDENTITY_FIELDS = {
    "evidence_id": "$.id",
    "trial_id": "$.studyId",
    "drug_id": "$.drugId",
    "target_id": "$.targetId",
    "disease_id": "$.diseaseId",
}


def default_assertion_raw_paths() -> list[Path]:
    return [
        fixture_path(
            f"chembl_{release.replace('.', '_')}_broad_trial_mapping_raw.json.gz"
        )
        for release in RELEASES
    ]


def default_assertion_history_snapshot_path() -> Path:
    return fixture_path("p5_6_assertion_history_snapshot.json")


def default_assertion_history_manifest_path() -> Path:
    return fixture_path("p5_6_assertion_history_manifest.json")


def _valid_source_identity(row: dict) -> bool:
    return bool(
        re.fullmatch(r"[0-9a-f]{40}", row.get("id") or "")
        and re.fullmatch(r"NCT\d{8}", row.get("studyId") or "")
        and re.fullmatch(r"CHEMBL\d+", row.get("drugId") or "")
        and re.fullmatch(r"ENSG\d{11}", row.get("targetId") or "")
    )


def _content_row(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "sourceParquetUrl"}


def _lifecycle(memberships: set[str]) -> str:
    if memberships == set(RELEASES):
        return "persistent_across_releases"
    if memberships == {RELEASES[0]}:
        return "removed_after_25_03"
    if memberships == {RELEASES[-1]}:
        return "added_in_25_09"
    return "release_limited"


def build_assertion_history_records(
    raw_paths: list[Path] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    paths = raw_paths or default_assertion_raw_paths()
    captures = [_read_gzip_json(path) for path in paths]
    by_release = {capture["release_version"]: capture for capture in captures}
    if set(by_release) != set(RELEASES):
        raise ValueError(f"expected releases {RELEASES}, got {sorted(by_release)}")

    evidence_observations: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    assertion_rows: dict[tuple[str, str, str], dict[str, list[dict]]] = defaultdict(
        lambda: defaultdict(list)
    )
    invalid_rows = []
    release_assertions = {}
    release_ncts = {}
    for release in RELEASES:
        capture = by_release[release]
        if not capture["complete_for_query"]:
            raise ValueError(f"incomplete source capture for {release}")
        triples = set()
        ncts = set()
        for row in capture["rows"]:
            if not _valid_source_identity(row):
                invalid_rows.append({"release": release, "row": row})
                continue
            evidence_observations[row["id"]].append((release, row))
            key = (row["studyId"], row["drugId"], row["targetId"])
            assertion_rows[key][release].append(row)
            triples.add(key)
            ncts.add(row["studyId"])
        release_assertions[release] = triples
        release_ncts[release] = ncts

    evidence_history = []
    content_changed_count = 0
    for evidence_id, values in sorted(evidence_observations.items()):
        memberships = {release for release, _ in values}
        content_hashes = {
            hashlib.sha256(canonical_json_bytes(_content_row(row))).hexdigest()
            for _, row in values
        }
        content_changed = len(content_hashes) > 1
        content_changed_count += content_changed
        observations = []
        for release, row in sorted(values):
            observations.append(
                {
                    "release": release,
                    "release_date": RELEASE_DATES[release],
                    "raw_row_sha256": hashlib.sha256(
                        canonical_json_bytes(row)
                    ).hexdigest(),
                    "content_sha256": hashlib.sha256(
                        canonical_json_bytes(_content_row(row))
                    ).hexdigest(),
                    "source_parquet_url": row["sourceParquetUrl"],
                    "source_urls": row.get("urls") or [],
                    "source_values_override": (
                        _content_row(row) if content_changed else None
                    ),
                }
            )
        exemplar = values[-1][1]
        evidence_history.append(
            {
                "id": stable_id("source-assertion-evidence", evidence_id),
                "source_evidence_id": evidence_id,
                "datasource_id": exemplar["datasourceId"],
                "datatype_id": exemplar["datatypeId"],
                "nct_id": exemplar["studyId"],
                "drug_chembl_id": exemplar["drugId"],
                "target_ensembl_id": exemplar["targetId"],
                "disease_id": exemplar.get("diseaseId"),
                "source_values": _content_row(exemplar),
                "source_identity_field_paths": IDENTITY_FIELDS,
                "release_memberships": sorted(memberships),
                "first_observed_release": min(memberships),
                "last_observed_release": max(memberships),
                "lifecycle_status": _lifecycle(memberships),
                "content_changed_across_releases": content_changed,
                "observations": observations,
                "source_asserted_trial_drug_target": True,
                "name_resolution_used": False,
                "fuzzy_matching_used": False,
                "temporal_model_feature_use_allowed": False,
            }
        )

    assertions = []
    for (nct_id, drug_id, target_id), release_rows in sorted(assertion_rows.items()):
        memberships = set(release_rows)
        release_evidence = {
            release: sorted(row["id"] for row in release_rows[release])
            for release in sorted(release_rows)
        }
        rows = [row for values in release_rows.values() for row in values]
        assertions.append(
            {
                "id": stable_id(
                    "versioned-trial-drug-target",
                    f"{nct_id}-{drug_id}-{target_id}",
                ),
                "nct_id": nct_id,
                "drug_chembl_id": drug_id,
                "target_ensembl_id": target_id,
                "assertion_type": "source_asserted_open_targets_chembl_evidence",
                "source_identity_field_paths": IDENTITY_FIELDS,
                "release_memberships": sorted(memberships),
                "lifecycle_status": _lifecycle(memberships),
                "evidence_ids_by_release": release_evidence,
                "evidence_row_count_by_release": {
                    release: len(ids) for release, ids in release_evidence.items()
                },
                "disease_ids": sorted(
                    {row["diseaseId"] for row in rows if row.get("diseaseId")}
                ),
                "source_asserted": True,
                "name_resolution_used": False,
                "fuzzy_matching_used": False,
                "temporal_model_feature_use_allowed": False,
            }
        )

    p55_store = load_default_drug_identity_store()
    p55_rows = p55_store.sample(p55_store.manifest.resolution_record_count)
    exact_candidate_ncts = {
        row["nct_id"] for row in p55_rows if row["candidate_chembl_ids"]
    }
    union_ncts = {row["nct_id"] for row in assertions}
    recovered_candidate_ncts = exact_candidate_ncts & union_ncts
    newest_ncts = release_ncts[RELEASES[-1]]
    metadata = {
        "captures": by_release,
        "release_assertions": release_assertions,
        "release_ncts": release_ncts,
        "invalid_rows": invalid_rows,
        "content_changed_count": content_changed_count,
        "exact_candidate_ncts": exact_candidate_ncts,
        "recovered_candidate_ncts": recovered_candidate_ncts,
        "newly_recovered_ncts": union_ncts - newest_ncts,
        "union_ncts": union_ncts,
    }
    return evidence_history, assertions, metadata


def _quality(
    evidence_history: list[dict], assertions: list[dict], metadata: dict
) -> AssertionHistoryQuality:
    evidence_lifecycle = Counter(row["lifecycle_status"] for row in evidence_history)
    assertion_lifecycle = Counter(row["lifecycle_status"] for row in assertions)
    exact_count = len(metadata["exact_candidate_ncts"])
    recovered_count = len(metadata["recovered_candidate_ncts"])
    captures = metadata["captures"]
    return AssertionHistoryQuality(
        release_count=len(RELEASES),
        release_evidence_row_counts={
            release: len(captures[release]["rows"]) for release in RELEASES
        },
        release_assertion_counts={
            release: len(metadata["release_assertions"][release])
            for release in RELEASES
        },
        release_mapped_nct_counts={
            release: len(metadata["release_ncts"][release]) for release in RELEASES
        },
        union_evidence_row_count=len(evidence_history),
        persistent_evidence_row_count=evidence_lifecycle[
            "persistent_across_releases"
        ],
        removed_evidence_row_count=evidence_lifecycle["removed_after_25_03"],
        added_evidence_row_count=evidence_lifecycle["added_in_25_09"],
        content_changed_evidence_row_count=metadata["content_changed_count"],
        union_assertion_count=len(assertions),
        persistent_assertion_count=assertion_lifecycle[
            "persistent_across_releases"
        ],
        removed_assertion_count=assertion_lifecycle["removed_after_25_03"],
        added_assertion_count=assertion_lifecycle["added_in_25_09"],
        union_mapped_nct_count=len(metadata["union_ncts"]),
        newly_recovered_nct_count=len(metadata["newly_recovered_ncts"]),
        p5_5_exact_identity_candidate_nct_count=exact_count,
        p5_5_candidate_target_assertion_recovery_count=recovered_count,
        p5_5_candidate_target_assertion_recovery_coverage=(
            recovered_count / exact_count if exact_count else 0.0
        ),
        remaining_unresolved_nct_count=21694 - len(metadata["newly_recovered_ncts"]),
        invalid_source_identity_row_count=len(metadata["invalid_rows"]),
        source_field_provenance_coverage=(
            sum(bool(row["source_identity_field_paths"]) for row in evidence_history)
            / len(evidence_history)
        ),
        engineering_gate_passed=(
            all(captures[release]["complete_for_query"] for release in RELEASES)
            and not metadata["invalid_rows"]
            and len(evidence_history) == 97074
            and len(assertions) == 86157
        ),
        blocking_limitations=[
            "The two archived releases recover no additional NCT-level target assertion beyond 25.09.",
            "A removed assertion is release-membership history, not evidence that the mechanism is false.",
            "Open Targets ChEMBL evidence is a source assertion and does not independently establish target causality.",
            "Only 25.03 and 25.09 are frozen; assertions outside these releases are not observed.",
            "Both releases are enrichment-only and remain forbidden as temporal outcome-model features.",
        ],
    )


def render_assertion_history_report(snapshot: AssertionHistorySnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P5.6 versioned source-assertion history",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Releases: {', '.join(snapshot.releases)}",
            f"- Union evidence rows: {q.union_evidence_row_count}",
            f"- Persistent / removed / added evidence: {q.persistent_evidence_row_count} / {q.removed_evidence_row_count} / {q.added_evidence_row_count}",
            f"- Union trial-drug-target assertions: {q.union_assertion_count}",
            f"- Persistent / removed / added assertions: {q.persistent_assertion_count} / {q.removed_assertion_count} / {q.added_assertion_count}",
            f"- Newly recovered NCT: {q.newly_recovered_nct_count}",
            f"- P5.5 identity-candidate target recovery: {q.p5_5_candidate_target_assertion_recovery_count}/{q.p5_5_exact_identity_candidate_nct_count}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def write_assertion_history_artifacts(
    output_dir: Path, raw_paths: list[Path] | None = None
) -> tuple[AssertionHistorySnapshot, AssertionHistoryManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = raw_paths or default_assertion_raw_paths()
    evidence, assertions, metadata = build_assertion_history_records(sources)
    evidence_path = output_dir / "p5_6_source_evidence_history.jsonl.gz"
    assertion_path = output_dir / "p5_6_trial_drug_target_assertions.jsonl.gz"
    _write_jsonl_gzip(evidence_path, evidence)
    _write_jsonl_gzip(assertion_path, assertions)
    snapshot = AssertionHistorySnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        evidence_history_path=evidence_path.name,
        evidence_history_sha256=file_sha256(evidence_path),
        assertion_path=assertion_path.name,
        assertion_sha256=file_sha256(assertion_path),
        quality=_quality(evidence, assertions, metadata),
        warning=(
            "SOURCE-ASSERTION HISTORY ONLY. Release membership never authorizes "
            "name-based target inference or temporal feature backfill."
        ),
    )
    snapshot_path = output_dir / "p5_6_assertion_history_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_6_assertion_history_report.md").write_text(
        render_assertion_history_report(snapshot), encoding="utf-8"
    )
    p55_store = load_default_drug_identity_store()
    p55_resolution_path = artifact_path(
        p55_store.root, p55_store.manifest.resolution_path
    )
    source_checksums = {path.name: file_sha256(path) for path in sources}
    source_checksums.update(
        {
            p55_resolution_path.name: file_sha256(p55_resolution_path),
            default_drug_identity_manifest_path().name: file_sha256(
                default_drug_identity_manifest_path()
            ),
        }
    )
    manifest = AssertionHistoryManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=source_checksums,
        evidence_history_path=evidence_path.name,
        evidence_history_sha256=file_sha256(evidence_path),
        evidence_history_record_count=len(evidence),
        assertion_path=assertion_path.name,
        assertion_sha256=file_sha256(assertion_path),
        assertion_record_count=len(assertions),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "p5_6_assertion_history_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class AssertionHistoryStore:
    def __init__(
        self,
        snapshot: AssertionHistorySnapshot,
        manifest: AssertionHistoryManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "AssertionHistoryStore":
        return cls(
            AssertionHistorySnapshot.model_validate(_load_json(snapshot_path)),
            AssertionHistoryManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, path: str, limit: int, lifecycle: str | None) -> list[dict]:
        result = []
        with gzip.open(artifact_path(self.root, path), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if lifecycle is None or row["lifecycle_status"] == lifecycle:
                    result.append(row)
                    if len(result) >= limit:
                        break
        return result

    def sample_evidence(
        self, limit: int = 20, lifecycle: str | None = None
    ) -> list[dict]:
        return self._sample(self.manifest.evidence_history_path, limit, lifecycle)

    def sample_assertions(
        self, limit: int = 20, lifecycle: str | None = None
    ) -> list[dict]:
        return self._sample(self.manifest.assertion_path, limit, lifecycle)

    def trial(self, nct_id: str) -> dict:
        assertions = []
        with gzip.open(
            artifact_path(self.root, self.manifest.assertion_path), "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if row["nct_id"] == nct_id:
                    assertions.append(row)
        return {"nct_id": nct_id, "assertions": assertions}

    def quality_report(self) -> dict:
        sources = default_assertion_raw_paths()
        p55_store = load_default_drug_identity_store()
        p55_path = artifact_path(p55_store.root, p55_store.manifest.resolution_path)
        expected = {path.name: file_sha256(path) for path in sources}
        expected.update(
            {
                p55_path.name: file_sha256(p55_path),
                default_drug_identity_manifest_path().name: file_sha256(
                    default_drug_identity_manifest_path()
                ),
            }
        )
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.evidence_history_path))
                == self.manifest.evidence_history_sha256
                and file_sha256(artifact_path(self.root, self.manifest.assertion_path))
                == self.manifest.assertion_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_assertion_history_store() -> AssertionHistoryStore:
    return AssertionHistoryStore.load(
        default_assertion_history_snapshot_path(),
        default_assertion_history_manifest_path(),
    )
