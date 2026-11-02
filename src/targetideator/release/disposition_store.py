"""Record R2.3 packaging decisions without applying payload mutations."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.disposition_models import (
    FixtureDispositionManifest,
    FixtureDispositionQuality,
    FixtureDispositionRecord,
    FixtureDispositionSnapshot,
)
from targetideator.release.retained_fixture_store import (
    RetainedFixtureStore,
    load_default_retained_fixture_store,
)

BUILDER_VERSION = "r2.3-owner-disposition-ledger-v1"
SNAPSHOT_ID = "ti:fixture-disposition:r2.3-owner-decisions-v1"
CREATED_AT = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_fixture_disposition_snapshot_path() -> Path:
    return fixture_path("r2_3_fixture_disposition_snapshot.json")


def default_fixture_disposition_manifest_path() -> Path:
    return fixture_path("r2_3_fixture_disposition_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "src/targetideator/release/disposition_models.py",
        "src/targetideator/release/disposition_store.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def _portable_source_checksums(root: Path | None = None) -> dict[str, str]:
    """Use frozen builder hashes when an installed wheel has no source checkout."""

    try:
        return _source_checksums(root)
    except FileNotFoundError:
        frozen = _load_json(default_fixture_disposition_manifest_path())
        return dict(frozen["source_checksums"])


def _decision_for(artifact_class: str) -> tuple[str, str, str, str]:
    if artifact_class in {"package_code", "release_metadata"}:
        return (
            "retain",
            "project_owner",
            "Owner accepted the R2.2 retain recommendation for code-native or release metadata.",
            "recorded_no_payload_change_required",
        )
    if artifact_class == "source_capture":
        return (
            "externalize",
            "data_steward",
            "Data-steward disposition follows the R2.2 conservative source-capture boundary.",
            "blocked_pending_hydration_recipe",
        )
    if artifact_class == "curated_fixture":
        return (
            "retain",
            "project_owner",
            "Owner retained the curated fixture for local engineering use; redistribution remains unauthorized.",
            "recorded_no_payload_change_required",
        )
    return (
        "regenerate",
        "project_owner",
        "Owner accepted deterministic regeneration as the target packaging disposition.",
        "blocked_pending_rebuild_recipe",
    )


def build_fixture_disposition_ledger(
    inventory_store: RetainedFixtureStore | None = None,
) -> list[FixtureDispositionRecord]:
    store = inventory_store or load_default_retained_fixture_store()
    records = []
    for item in store.inventory():
        decision, authority, basis, execution_status = _decision_for(item.artifact_class)
        natural_key = (
            "package-init.py" if item.relative_path == "__init__.py" else item.relative_path
        )
        records.append(
            FixtureDispositionRecord(
                id=stable_id("fixture-disposition", natural_key),
                retained_fixture_id=item.id,
                relative_path=item.relative_path,
                artifact_sha256=item.sha256,
                artifact_class=item.artifact_class,
                prior_recommendation=item.recommended_action,
                decision=decision,
                decision_authority=authority,
                decision_basis=basis,
                execution_status=execution_status,
            )
        )
    return records


def fixture_disposition_quality(
    ledger: list[FixtureDispositionRecord],
) -> FixtureDispositionQuality:
    decision_counts = Counter(row.decision for row in ledger)
    authority_counts = Counter(row.decision_authority for row in ledger)
    return FixtureDispositionQuality(
        inventory_record_count=len(ledger),
        decision_record_count=len(ledger),
        retain_count=decision_counts["retain"],
        externalize_count=decision_counts["externalize"],
        regenerate_count=decision_counts["regenerate"],
        project_owner_decision_count=authority_counts["project_owner"],
        data_steward_decision_count=authority_counts["data_steward"],
        blocking_limitations=[
            "Packaging dispositions do not establish licenses or redistribution rights.",
            "Four curated fixtures are retained for local engineering use only.",
            "Fourteen externalize decisions lack artifact-specific hydration recipes.",
            "Ninety-nine regenerate decisions lack verified artifact-specific rebuild recipes.",
            "No payload mutation is applied until a separate execution plan passes checksum replay.",
            "Decision recording does not alter scientific claim status or unblock C1/C4.",
        ],
    )


def write_fixture_disposition_artifacts(
    output_dir: Path, root: Path | None = None
) -> tuple[FixtureDispositionSnapshot, FixtureDispositionManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parent = load_default_retained_fixture_store()
    ledger = build_fixture_disposition_ledger(parent)
    ledger_path = output_dir / "r2_3_fixture_disposition_ledger.jsonl.gz"
    _write_jsonl_gzip(ledger_path, [row.model_dump(mode="json") for row in ledger])
    quality = fixture_disposition_quality(ledger)
    snapshot = FixtureDispositionSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        parent_inventory_snapshot_id=parent.snapshot.id,
        parent_inventory_sha256=parent.manifest.inventory_sha256,
        ledger_path=ledger_path.name,
        ledger_sha256=file_sha256(ledger_path),
        quality=quality,
        warning=(
            "DECISIONS RECORDED, NOT EXECUTED. Retain/externalize/regenerate dispositions "
            "do not authorize redistribution or mutate the package."
        ),
    )
    snapshot_path = output_dir / "r2_3_fixture_disposition_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = FixtureDispositionManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_portable_source_checksums(root),
        parent_inventory_snapshot_id=parent.snapshot.id,
        parent_inventory_sha256=parent.manifest.inventory_sha256,
        ledger_path=ledger_path.name,
        ledger_sha256=file_sha256(ledger_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_3_fixture_disposition_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class FixtureDispositionStore:
    def __init__(
        self,
        snapshot: FixtureDispositionSnapshot,
        manifest: FixtureDispositionManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "FixtureDispositionStore":
        return cls(
            FixtureDispositionSnapshot.model_validate(_load_json(snapshot_path)),
            FixtureDispositionManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def ledger(self) -> list[FixtureDispositionRecord]:
        with gzip.open(
            self.root / self.manifest.ledger_path, "rt", encoding="utf-8"
        ) as stream:
            return [
                FixtureDispositionRecord.model_validate(json.loads(line))
                for line in stream
            ]

    def quality_report(self) -> dict:
        parent = load_default_retained_fixture_store()
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "parent_inventory_link_matches": (
                self.manifest.parent_inventory_snapshot_id == parent.snapshot.id
                and self.manifest.parent_inventory_sha256
                == parent.manifest.inventory_sha256
            ),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.ledger_path)
                == self.manifest.ledger_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }


def load_default_fixture_disposition_store() -> FixtureDispositionStore:
    return FixtureDispositionStore.load(
        default_fixture_disposition_snapshot_path(),
        default_fixture_disposition_manifest_path(),
    )
