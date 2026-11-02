"""Build and validate the R2 code/data packaging split without authorizing upload."""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import MissingDataArtifactError, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.data_bundle_models import (
    DataBundleRecord,
    PackagingSplitManifest,
    PackagingSplitQuality,
    PackagingSplitSnapshot,
)

BUILDER_VERSION = "r2-code-data-packaging-split-v1"
SNAPSHOT_ID = "ti:packaging-split:r2-code-data-bundle-v1"
CREATED_AT = datetime(2026, 11, 3, 20, 0, tzinfo=timezone.utc)
SPLIT_THRESHOLD_BYTES = 1024 * 1024
CODE_PAYLOAD_BUDGET_BYTES = 50 * 1024 * 1024

# This is a frozen release contract, not a threshold applied dynamically at build time.
EXTERNALIZED_FILENAMES = (
    "aact_broad_interventions_test_raw.json.gz",
    "aact_broad_interventions_train_raw.json.gz",
    "aact_broad_interventions_validation_raw.json.gz",
    "aact_immune_outcomes_test_raw.json",
    "aact_immune_outcomes_train_raw.json",
    "aact_immune_outcomes_validation_raw.json",
    "chembl_25_03_broad_trial_mapping_raw.json.gz",
    "chembl_25_09_broad_trial_mapping_raw.json.gz",
    "claim_graph_snapshot.json",
    "drugcentral_2027_independent_assertions_raw.json.gz",
    "opentargets_26_09_raw.json",
    "opentargets_26_09_snapshot.json",
    "p5_2_broad_outcomes.jsonl.gz",
    "p5_2_broad_test_predictions.jsonl.gz",
    "p5_3_outcome_provenance.jsonl.gz",
    "p5_3_trial_drug_target_mappings.jsonl.gz",
    "p5_4_mapping_triage.jsonl.gz",
    "p5_5_drug_identity_resolutions.jsonl.gz",
    "p5_6_source_evidence_history.jsonl.gz",
    "p5_6_trial_drug_target_assertions.jsonl.gz",
    "p5_7_cross_source_corroborations.jsonl.gz",
    "p5_8_support_stratified_outcomes.jsonl.gz",
    "p5_9_selection_cohort.jsonl.gz",
    "p5_outcome_dataset.json",
)

METADATA_FILENAMES = (
    "r2_data_inventory.jsonl.gz",
    "r2_packaging_split_snapshot.json",
    "r2_packaging_split_manifest.json",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_packaging_split_snapshot_path() -> Path:
    return fixture_path("r2_packaging_split_snapshot.json")


def default_packaging_split_manifest_path() -> Path:
    return fixture_path("r2_packaging_split_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "pyproject.toml",
        "src/targetideator/data.py",
        "src/targetideator/release/data_bundle_store.py",
        "src/targetideator/release/data_bundle_models.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def _fixture_root(root: Path | None = None) -> Path:
    return (root or _project_root()) / "src" / "targetideator" / "fixtures"


def build_data_inventory(root: Path | None = None) -> list[DataBundleRecord]:
    fixture_root = _fixture_root(root)
    records = []
    for filename in EXTERNALIZED_FILENAMES:
        path = fixture_root / filename
        if not path.is_file():
            raise FileNotFoundError(f"R2 externalized fixture is missing: {path}")
        if path.stat().st_size <= SPLIT_THRESHOLD_BYTES:
            raise ValueError(f"R2 frozen bulk artifact no longer exceeds threshold: {filename}")
        records.append(
            DataBundleRecord(
                id=stable_id("data-bundle-file", filename),
                relative_path=f"data/{filename}",
                filename=filename,
                byte_count=path.stat().st_size,
                sha256=file_sha256(path),
                artifact_class=(
                    "source_capture" if "_raw." in filename else "derived_artifact"
                ),
            )
        )
    return records


def _retained_fixtures(root: Path | None = None) -> list[Path]:
    fixture_root = _fixture_root(root)
    excluded = set(EXTERNALIZED_FILENAMES) | set(METADATA_FILENAMES)
    return [
        path
        for path in sorted(fixture_root.iterdir())
        if path.is_file() and path.name not in excluded
    ]


def _projected_code_payload(root: Path | None = None) -> list[Path]:
    project_root = root or _project_root()
    package_root = project_root / "src" / "targetideator"
    excluded = set(EXTERNALIZED_FILENAMES)
    return [
        path
        for path in sorted(package_root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
        and not (path.parent == package_root / "fixtures" and path.name in excluded)
    ]


def build_packaging_split_quality(
    inventory: list[DataBundleRecord], root: Path | None = None
) -> PackagingSplitQuality:
    retained = _retained_fixtures(root)
    projected = _projected_code_payload(root)
    projected_bytes = sum(path.stat().st_size for path in projected)
    if projected_bytes > CODE_PAYLOAD_BUDGET_BYTES:
        raise ValueError(
            f"R2 projected code payload {projected_bytes} exceeds budget "
            f"{CODE_PAYLOAD_BUDGET_BYTES}"
        )
    return PackagingSplitQuality(
        externalized_byte_count=sum(row.byte_count for row in inventory),
        retained_fixture_file_count=len(retained),
        retained_fixture_byte_count=sum(path.stat().st_size for path in retained),
        projected_code_payload_file_count=len(projected),
        projected_code_payload_byte_count=projected_bytes,
        blocking_limitations=[
            "The source-by-source redistribution ledger is incomplete; the data bundle is local-only.",
            "R2 does not choose a project license or create author-approved citation metadata.",
            "An installed code package requires TARGETIDEATOR_DATA_ROOT for externalized workflows.",
            "This packaging change does not alter scientific claim status or unblock C1/C4.",
        ],
    )


def write_packaging_split_artifacts(
    output_dir: Path,
    root: Path | None = None,
    *,
    materialize_data: bool = True,
) -> tuple[PackagingSplitSnapshot, PackagingSplitManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    project_root = root or _project_root()
    inventory = build_data_inventory(project_root)
    inventory_path = output_dir / "r2_data_inventory.jsonl.gz"
    _write_jsonl_gzip(inventory_path, [row.model_dump(mode="json") for row in inventory])
    if materialize_data:
        data_dir = output_dir / "data"
        data_dir.mkdir(exist_ok=True)
        for row in inventory:
            shutil.copy2(_fixture_root(project_root) / row.filename, data_dir / row.filename)
    quality = build_packaging_split_quality(inventory, project_root)
    snapshot = PackagingSplitSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        data_inventory_path=inventory_path.name,
        data_inventory_sha256=file_sha256(inventory_path),
        quality=quality,
        warning=(
            "LOCAL REPRODUCIBILITY DATA BUNDLE ONLY. Checksums do not establish "
            "redistribution rights, and no public upload is authorized."
        ),
    )
    snapshot_path = output_dir / "r2_packaging_split_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = PackagingSplitManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(project_root),
        externalized_filenames=list(EXTERNALIZED_FILENAMES),
        data_inventory_path=inventory_path.name,
        data_inventory_sha256=file_sha256(inventory_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_packaging_split_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class PackagingSplitStore:
    def __init__(
        self,
        snapshot: PackagingSplitSnapshot,
        manifest: PackagingSplitManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "PackagingSplitStore":
        return cls(
            PackagingSplitSnapshot.model_validate(_load_json(snapshot_path)),
            PackagingSplitManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def inventory(self) -> list[dict]:
        rows = []
        with gzip.open(
            self.root / self.manifest.data_inventory_path, "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                rows.append(json.loads(line))
        return rows

    def materialized_data_checksums_match(self) -> bool:
        rows = self.inventory()
        return all(
            (self.root / row["relative_path"]).is_file()
            and file_sha256(self.root / row["relative_path"]) == row["sha256"]
            for row in rows
        )

    def source_data_checksums_match(self) -> bool:
        try:
            for row in self.inventory():
                path = fixture_path(row["filename"])
                if not path.is_file() or file_sha256(path) != row["sha256"]:
                    return False
        except MissingDataArtifactError:
            return False
        return True

    def source_checksums_match(self) -> bool | None:
        """Compare builder sources when a source checkout is available.

        A materialized bundle remains byte-verifiable from an installed wheel, where
        project-root source files are intentionally absent. ``None`` means not
        applicable in that environment, not a bundle-integrity failure.
        """

        try:
            return _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            return None

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.data_inventory_path)
                == self.manifest.data_inventory_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": self.source_checksums_match(),
            "historical_snapshot_superseded_by": "ti:hydration-contract:r2.1-external-payload-v1",
            "source_data_checksums_match": self.source_data_checksums_match(),
            "materialized_data_checksums_match": self.materialized_data_checksums_match(),
            "warning": self.snapshot.warning,
        }


def load_default_packaging_split_store() -> PackagingSplitStore:
    return PackagingSplitStore.load(
        default_packaging_split_snapshot_path(),
        default_packaging_split_manifest_path(),
    )
