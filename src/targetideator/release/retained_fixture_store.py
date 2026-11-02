"""Inventory retained package fixtures without making redistribution decisions."""

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
from targetideator.release.data_bundle_store import EXTERNALIZED_FILENAMES
from targetideator.release.retained_fixture_models import (
    RetainedFixtureManifest,
    RetainedFixtureQuality,
    RetainedFixtureRecord,
    RetainedFixtureSnapshot,
)

BUILDER_VERSION = "r2.2-retained-fixture-governance-v1"
SNAPSHOT_ID = "ti:retained-fixture-governance:r2.2-inventory-v1"
CREATED_AT = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
SELF_METADATA = {
    "r2_2_retained_fixture_inventory.jsonl.gz",
    "r2_2_retained_fixture_snapshot.json",
    "r2_2_retained_fixture_manifest.json",
    "r2_3_fixture_disposition_ledger.jsonl.gz",
    "r2_3_fixture_disposition_snapshot.json",
    "r2_3_fixture_disposition_manifest.json",
    "r2_4_execution_recipe.jsonl.gz",
    "r2_4_mutation_preview.jsonl.gz",
    "r2_4_execution_plan_snapshot.json",
    "r2_4_execution_plan_manifest.json",
    "r2_5_group_replay.jsonl.gz",
    "r2_5_artifact_replay.jsonl.gz",
    "r2_5_execution_replay_snapshot.json",
    "r2_5_execution_replay_manifest.json",
    "r2_6_artifact_diagnosis.jsonl.gz",
    "r2_6_replay_hardening_snapshot.json",
    "r2_6_replay_hardening_manifest.json",
    "r2_7_canonical_acceptance_ledger.jsonl.gz",
    "r2_7_canonical_acceptance_snapshot.json",
    "r2_7_canonical_acceptance_manifest.json",
    "r2_8_package_file_audit.jsonl.gz",
    "r2_8_runtime_smoke.jsonl.gz",
    "r2_8_package_convergence_snapshot.json",
    "r2_8_package_convergence_manifest.json",
}
CURATED_FIXTURES = {
    "crohns_seed.json",
    "literature_benchmark.json",
    "literature_review_batch.json",
    "literature_comment_resolution.json",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _fixture_root(root: Path | None = None) -> Path:
    return (root or _project_root()) / "src" / "targetideator" / "fixtures"


def default_retained_fixture_snapshot_path() -> Path:
    return fixture_path("r2_2_retained_fixture_snapshot.json")


def default_retained_fixture_manifest_path() -> Path:
    return fixture_path("r2_2_retained_fixture_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "src/targetideator/release/retained_fixture_models.py",
        "src/targetideator/release/retained_fixture_store.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def _retained_paths(root: Path | None = None) -> list[Path]:
    fixture_root = _fixture_root(root)
    excluded = set(EXTERNALIZED_FILENAMES) | SELF_METADATA
    return [
        path
        for path in sorted(fixture_root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
        and path.name not in excluded
    ]


def _classification(relative_path: str) -> tuple[str, str, str, str, bool]:
    name = Path(relative_path).name
    if relative_path == "__init__.py":
        return (
            "package_code",
            "exact package-marker rule",
            "retain_code_native",
            "maintainer",
            False,
        )
    if name.startswith(("r1_", "r2_")):
        return (
            "release_metadata",
            "exact frozen release-metadata prefix rule",
            "retain_release_metadata_candidate",
            "maintainer",
            False,
        )
    if "_raw." in name:
        return (
            "source_capture",
            "exact source-capture filename marker rule",
            "externalize_pending_redistribution_decision",
            "data_steward",
            True,
        )
    if name in CURATED_FIXTURES:
        return (
            "curated_fixture",
            "exact curated-fixture allowlist rule",
            "retain_pending_owner_review",
            "scientific_owner",
            True,
        )
    return (
        "derived_artifact",
        "conservative default for non-source pipeline or paper artifact",
        "regenerate_from_external_inputs_candidate",
        "pipeline_owner",
        True,
    )


def build_retained_fixture_inventory(
    root: Path | None = None,
) -> list[RetainedFixtureRecord]:
    fixture_root = _fixture_root(root)
    records = []
    for path in _retained_paths(root):
        relative_path = path.relative_to(fixture_root).as_posix()
        artifact_class, basis, action, owner, source_derived = _classification(relative_path)
        natural_key = "package-init.py" if relative_path == "__init__.py" else relative_path
        records.append(
            RetainedFixtureRecord(
                id=stable_id("retained-fixture", natural_key),
                relative_path=relative_path,
                byte_count=path.stat().st_size,
                sha256=file_sha256(path),
                artifact_class=artifact_class,
                classification_basis=basis,
                recommended_action=action,
                owner_role=owner,
                source_derived=source_derived,
            )
        )
    return records


def retained_fixture_quality(
    inventory: list[RetainedFixtureRecord],
) -> RetainedFixtureQuality:
    counts = Counter(row.artifact_class for row in inventory)
    return RetainedFixtureQuality(
        retained_file_count=len(inventory),
        retained_byte_count=sum(row.byte_count for row in inventory),
        package_code_count=counts["package_code"],
        source_capture_count=counts["source_capture"],
        curated_fixture_count=counts["curated_fixture"],
        derived_artifact_count=counts["derived_artifact"],
        release_metadata_count=counts["release_metadata"],
        classified_file_count=len(inventory),
        unresolved_redistribution_count=len(inventory),
        blocking_limitations=[
            "Classification is an engineering inventory, not a license or redistribution ruling.",
            "Every retained file remains unresolved until its named owner records a decision.",
            "Derived and curated artifacts may still contain source-derived content.",
            "No file is moved, deleted, uploaded, or newly authorized by this stage.",
            "Governance readiness does not alter scientific claim status or unblock C1/C4.",
        ],
    )


def write_retained_fixture_artifacts(
    output_dir: Path, root: Path | None = None
) -> tuple[RetainedFixtureSnapshot, RetainedFixtureManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = build_retained_fixture_inventory(root)
    inventory_path = output_dir / "r2_2_retained_fixture_inventory.jsonl.gz"
    _write_jsonl_gzip(
        inventory_path, [row.model_dump(mode="json") for row in inventory]
    )
    quality = retained_fixture_quality(inventory)
    snapshot = RetainedFixtureSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        inventory_path=inventory_path.name,
        inventory_sha256=file_sha256(inventory_path),
        quality=quality,
        warning=(
            "GOVERNANCE TRIAGE ONLY. Recommendations do not establish rights, authorize "
            "distribution, or mutate the package payload."
        ),
    )
    snapshot_path = output_dir / "r2_2_retained_fixture_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = RetainedFixtureManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(root),
        inventory_path=inventory_path.name,
        inventory_sha256=file_sha256(inventory_path),
        inventory_record_count=len(inventory),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_2_retained_fixture_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class RetainedFixtureStore:
    def __init__(
        self,
        snapshot: RetainedFixtureSnapshot,
        manifest: RetainedFixtureManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "RetainedFixtureStore":
        return cls(
            RetainedFixtureSnapshot.model_validate(_load_json(snapshot_path)),
            RetainedFixtureManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def inventory(self) -> list[RetainedFixtureRecord]:
        with gzip.open(
            self.root / self.manifest.inventory_path, "rt", encoding="utf-8"
        ) as stream:
            return [
                RetainedFixtureRecord.model_validate(json.loads(line)) for line in stream
            ]

    def action_counts(self) -> dict[str, int]:
        return dict(Counter(row.recommended_action for row in self.inventory()))

    def quality_report(self) -> dict:
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "action_counts": self.action_counts(),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.inventory_path)
                == self.manifest.inventory_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }


def load_default_retained_fixture_store() -> RetainedFixtureStore:
    return RetainedFixtureStore.load(
        default_retained_fixture_snapshot_path(),
        default_retained_fixture_manifest_path(),
    )
