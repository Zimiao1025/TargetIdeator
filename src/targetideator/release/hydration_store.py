"""Plan and audit R2 external-payload hydration without transferring data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.data_bundle_store import (
    EXTERNALIZED_FILENAMES,
    load_default_packaging_split_store,
)
from targetideator.release.hydration_models import (
    HydrationManifest,
    HydrationQuality,
    HydrationRecipeRecord,
    HydrationRootRecord,
    HydrationSnapshot,
)

BUILDER_VERSION = "r2.1-operator-hydration-contract-v1"
SNAPSHOT_ID = "ti:hydration-contract:r2.1-external-payload-v1"
CREATED_AT = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)

SOURCE_INPUTS = {
    "aact_broad_interventions_test_raw.json.gz": (
        5,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator capture-p5-interventions --output-dir {data_root}/data",
    ),
    "aact_broad_interventions_train_raw.json.gz": (
        5,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator capture-p5-interventions --output-dir {data_root}/data",
    ),
    "aact_broad_interventions_validation_raw.json.gz": (
        5,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator capture-p5-interventions --output-dir {data_root}/data",
    ),
    "aact_immune_outcomes_test_raw.json": (
        0,
        [],
        "targetideator capture-p5-outcome-landmarks --output-dir {data_root}/data",
    ),
    "aact_immune_outcomes_train_raw.json": (
        0,
        [],
        "targetideator capture-p5-outcome-landmarks --output-dir {data_root}/data",
    ),
    "aact_immune_outcomes_validation_raw.json": (
        0,
        [],
        "targetideator capture-p5-outcome-landmarks --output-dir {data_root}/data",
    ),
    "chembl_25_03_broad_trial_mapping_raw.json.gz": (
        5,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator capture-p5-assertion-history --output-dir {data_root}/data",
    ),
    "chembl_25_09_broad_trial_mapping_raw.json.gz": (
        5,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator capture-p5-assertion-history --output-dir {data_root}/data",
    ),
    "drugcentral_2027_independent_assertions_raw.json.gz": (
        0,
        [],
        "targetideator capture-p5-independent-assertions --output-path "
        "{data_root}/data/drugcentral_2027_independent_assertions_raw.json.gz",
    ),
    "opentargets_26_09_raw.json": (
        0,
        [],
        "targetideator capture-opentargets --output-dir {data_root}/data",
    ),
}

DERIVED_OUTPUTS = {
    "opentargets_26_09_snapshot.json": (
        1,
        ["opentargets_26_09_raw.json"],
        "targetideator build-evidence {data_root}/data/opentargets_26_09_raw.json "
        "--output-dir {data_root}/data",
    ),
    "claim_graph_snapshot.json": (
        2,
        ["clinical_history_snapshot.json"],
        "targetideator build-claim-graph --output-dir {data_root}/data",
    ),
    "p5_outcome_dataset.json": (
        3,
        [
            "aact_immune_outcomes_train_raw.json",
            "aact_immune_outcomes_validation_raw.json",
            "aact_immune_outcomes_test_raw.json",
        ],
        "targetideator build-p5-outcomes --output-dir {data_root}/data",
    ),
    "p5_2_broad_outcomes.jsonl.gz": (
        4,
        [
            "aact_broad_outcomes_train_raw.json.gz",
            "aact_broad_outcomes_validation_raw.json.gz",
            "aact_broad_outcomes_test_raw.json.gz",
        ],
        "targetideator build-p5-broad-outcomes --output-dir {data_root}/data",
    ),
    "p5_2_broad_test_predictions.jsonl.gz": (
        4,
        ["p5_2_broad_outcomes.jsonl.gz"],
        "targetideator build-p5-broad-outcomes --output-dir {data_root}/data",
    ),
    "p5_3_trial_drug_target_mappings.jsonl.gz": (
        6,
        [
            "chembl_25_09_broad_trial_mapping_raw.json.gz",
            "aact_broad_interventions_train_raw.json.gz",
            "p5_2_broad_outcomes.jsonl.gz",
            "opentargets_25_09_drug_dictionary_raw.json.gz",
        ],
        "targetideator build-p5-identity-ledger --output-dir {data_root}/data",
    ),
    "p5_3_outcome_provenance.jsonl.gz": (
        6,
        ["p5_3_trial_drug_target_mappings.jsonl.gz", "p5_2_broad_outcomes.jsonl.gz"],
        "targetideator build-p5-identity-ledger --output-dir {data_root}/data",
    ),
    "p5_4_mapping_triage.jsonl.gz": (
        7,
        [
            "aact_broad_interventions_train_raw.json.gz",
            "aact_broad_interventions_validation_raw.json.gz",
            "aact_broad_interventions_test_raw.json.gz",
            "p5_3_trial_drug_target_mappings.jsonl.gz",
            "p5_2_broad_outcomes.jsonl.gz",
        ],
        "targetideator build-p5-mapping-audit --output-dir {data_root}/data",
    ),
    "p5_5_drug_identity_resolutions.jsonl.gz": (
        8,
        ["p5_4_mapping_triage.jsonl.gz", "opentargets_25_09_full_drug_dictionary_raw.json.gz"],
        "targetideator build-p5-drug-identity --output-dir {data_root}/data",
    ),
    "p5_6_source_evidence_history.jsonl.gz": (
        9,
        [
            "chembl_25_03_broad_trial_mapping_raw.json.gz",
            "chembl_25_09_broad_trial_mapping_raw.json.gz",
            "p5_5_drug_identity_resolutions.jsonl.gz",
        ],
        "targetideator build-p5-assertion-history --output-dir {data_root}/data",
    ),
    "p5_6_trial_drug_target_assertions.jsonl.gz": (
        9,
        ["p5_6_source_evidence_history.jsonl.gz"],
        "targetideator build-p5-assertion-history --output-dir {data_root}/data",
    ),
    "p5_7_cross_source_corroborations.jsonl.gz": (
        10,
        [
            "drugcentral_2027_independent_assertions_raw.json.gz",
            "p5_6_trial_drug_target_assertions.jsonl.gz",
        ],
        "targetideator build-p5-independent-assertions --output-dir {data_root}/data",
    ),
    "p5_8_support_stratified_outcomes.jsonl.gz": (
        11,
        [
            "p5_3_outcome_provenance.jsonl.gz",
            "p5_7_cross_source_corroborations.jsonl.gz",
            "p5_2_broad_outcomes.jsonl.gz",
        ],
        "targetideator build-p5-support-audit --output-dir {data_root}/data",
    ),
    "p5_9_selection_cohort.jsonl.gz": (
        12,
        ["p5_8_support_stratified_outcomes.jsonl.gz", "p5_2_broad_outcomes.jsonl.gz"],
        "targetideator build-p5-selection-audit --output-dir {data_root}/data",
    ),
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_hydration_snapshot_path() -> Path:
    return fixture_path("r2_1_hydration_snapshot.json")


def default_hydration_manifest_path() -> Path:
    return fixture_path("r2_1_hydration_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "src/targetideator/release/hydration_models.py",
        "src/targetideator/release/hydration_store.py",
        "src/targetideator/release/data_bundle_store.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def build_hydration_recipe() -> list[HydrationRecipeRecord]:
    inventory = {
        row["filename"]: row for row in load_default_packaging_split_store().inventory()
    }
    records = []
    for filename in EXTERNALIZED_FILENAMES:
        row = inventory[filename]
        if filename in SOURCE_INPUTS:
            stage, dependencies, command = SOURCE_INPUTS[filename]
            role = "user_acquired_source_input"
            network_required = True
        else:
            stage, dependencies, command = DERIVED_OUTPUTS[filename]
            role = "deterministic_derived_output"
            network_required = False
        records.append(
            HydrationRecipeRecord(
                id=stable_id("hydration-recipe", filename),
                filename=filename,
                artifact_role=role,
                expected_byte_count=row["byte_count"],
                expected_sha256=row["sha256"],
                dependencies=dependencies,
                operator_command=(
                    f"TARGETIDEATOR_DATA_ROOT={{data_root}} {command}"
                ),
                command_stage=stage,
                network_required=network_required,
            )
        )
    return records


def hydration_quality() -> HydrationQuality:
    return HydrationQuality(
        blocking_limitations=[
            "The plan describes operator commands but performs no network request or data copy.",
            "Upstream source terms and access remain the operator's responsibility.",
            "Small packaged source-derived fixtures remain subject to the redistribution ledger.",
            "Exact historical checksums may be unavailable if mutable upstream sources change.",
            "Hydration readiness does not alter scientific claim status or unblock C1/C4.",
        ]
    )


def write_hydration_artifacts(
    output_dir: Path, root: Path | None = None
) -> tuple[HydrationSnapshot, HydrationManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    recipe = build_hydration_recipe()
    recipe_path = output_dir / "r2_1_hydration_recipe.jsonl.gz"
    _write_jsonl_gzip(recipe_path, [row.model_dump(mode="json") for row in recipe])
    snapshot = HydrationSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        recipe_path=recipe_path.name,
        recipe_sha256=file_sha256(recipe_path),
        quality=hydration_quality(),
        warning=(
            "OPERATOR PLAN ONLY. No source access, download, copy, redistribution, "
            "or scientific gate promotion is performed."
        ),
    )
    snapshot_path = output_dir / "r2_1_hydration_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = HydrationManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(root),
        recipe_path=recipe_path.name,
        recipe_sha256=file_sha256(recipe_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "r2_1_hydration_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


def inspect_hydration_root(
    data_root: Path, recipe: list[HydrationRecipeRecord] | None = None
) -> list[HydrationRootRecord]:
    records = []
    for item in recipe or build_hydration_recipe():
        candidates = (data_root / item.filename, data_root / "data" / item.filename)
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            status = "missing"
            observed_bytes = None
            observed_sha = None
            resolved = None
        else:
            observed_bytes = path.stat().st_size
            observed_sha = file_sha256(path)
            status = "ready" if observed_sha == item.expected_sha256 else "checksum_mismatch"
            resolved = str(path.resolve())
        records.append(
            HydrationRootRecord(
                id=stable_id("hydration-root-status", f"{item.filename}-{status}"),
                filename=item.filename,
                artifact_role=item.artifact_role,
                status=status,
                expected_byte_count=item.expected_byte_count,
                observed_byte_count=observed_bytes,
                expected_sha256=item.expected_sha256,
                observed_sha256=observed_sha,
                resolved_path=resolved,
            )
        )
    return records


class HydrationStore:
    def __init__(self, snapshot: HydrationSnapshot, manifest: HydrationManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "HydrationStore":
        return cls(
            HydrationSnapshot.model_validate(_load_json(snapshot_path)),
            HydrationManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def recipe(self) -> list[HydrationRecipeRecord]:
        import gzip

        with gzip.open(self.root / self.manifest.recipe_path, "rt", encoding="utf-8") as stream:
            return [HydrationRecipeRecord.model_validate(json.loads(line)) for line in stream]

    def inspect(self, data_root: Path) -> list[HydrationRootRecord]:
        return inspect_hydration_root(data_root, self.recipe())

    def root_report(self, data_root: Path) -> dict:
        rows = self.inspect(data_root)
        counts = {status: sum(row.status == status for row in rows) for status in ("ready", "missing", "checksum_mismatch")}
        return {
            "data_root": str(data_root.resolve()),
            "artifact_count": len(rows),
            "ready_count": counts["ready"],
            "missing_count": counts["missing"],
            "checksum_mismatch_count": counts["checksum_mismatch"],
            "source_input_ready_count": sum(
                row.status == "ready" and row.artifact_role == "user_acquired_source_input"
                for row in rows
            ),
            "derived_output_ready_count": sum(
                row.status == "ready" and row.artifact_role == "deterministic_derived_output"
                for row in rows
            ),
            "hydration_complete": all(row.status == "ready" for row in rows),
            "redistribution_performed": False,
            "rows": [row.model_dump(mode="json") for row in rows],
        }

    def quality_report(self) -> dict:
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.recipe_path)
                == self.manifest.recipe_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }


def load_default_hydration_store() -> HydrationStore:
    return HydrationStore.load(
        default_hydration_snapshot_path(), default_hydration_manifest_path()
    )
