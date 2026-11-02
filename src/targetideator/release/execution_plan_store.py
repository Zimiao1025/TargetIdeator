"""Build R2.4 command recipes and a non-destructive package mutation preview."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import content_digest, stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.data_bundle_store import EXTERNALIZED_FILENAMES
from targetideator.release.disposition_store import (
    FixtureDispositionStore,
    load_default_fixture_disposition_store,
)
from targetideator.release.execution_plan_models import (
    ExecutionPlanManifest,
    ExecutionPlanQuality,
    ExecutionPlanSnapshot,
    ExecutionRecipeRecord,
    MutationPreviewRecord,
)
from targetideator.release.retained_fixture_store import (
    RetainedFixtureStore,
    load_default_retained_fixture_store,
)

BUILDER_VERSION = "r2.4-execution-plan-preview-v1"
SNAPSHOT_ID = "ti:execution-plan:r2.4-non-destructive-preview-v1"
CREATED_AT = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)

CLINICAL_RAW = (
    "aact_20250301_trials_raw.json",
    "aact_20250901_trials_raw.json",
    "chembl_25_03_evidence_raw.json",
    "chembl_25_09_evidence_raw.json",
    "chembl_molecules_current_raw.json",
    "ctgov_trials_current_raw.json",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_execution_plan_snapshot_path() -> Path:
    return fixture_path("r2_4_execution_plan_snapshot.json")


def default_execution_plan_manifest_path() -> Path:
    return fixture_path("r2_4_execution_plan_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "src/targetideator/release/execution_plan_models.py",
        "src/targetideator/release/execution_plan_store.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def _portable_source_checksums(root: Path | None = None) -> dict[str, str]:
    try:
        return _source_checksums(root)
    except FileNotFoundError:
        frozen = _load_json(default_execution_plan_manifest_path())
        return dict(frozen["source_checksums"])


def _capture_recipe(path: str) -> tuple[int, list[str], str]:
    data = "{data_root}/data"
    root = "TARGETIDEATOR_DATA_ROOT={data_root}"
    if path.startswith("opentargets_25_") and "associations_raw" in path:
        return 0, [], f"{root} targetideator capture-opentargets-archives --output-dir {data}"
    if path in CLINICAL_RAW:
        return 0, [], f"{root} targetideator capture-clinical-history --output-dir {data}"
    if path.startswith("aact_broad_outcomes_"):
        return 0, [], f"{root} targetideator capture-p5-broad-outcome-landmarks --output-dir {data}"
    if path == "europepmc_literature_raw.json":
        return 0, [], f"{root} targetideator capture-literature --output-dir {data}"
    if path == "opentargets_25_09_drug_dictionary_raw.json.gz":
        return (
            0,
            ["chembl_25_09_broad_trial_mapping_raw.json.gz"],
            f"{root} targetideator capture-p5-identity-drug-dictionary "
            f"--output-path {data}/{path}",
        )
    if path == "opentargets_25_09_full_drug_dictionary_raw.json.gz":
        return 0, [], f"{root} targetideator capture-p5-drug-dictionary --output-path {data}/{path}"
    raise ValueError(f"No R2.4 capture recipe for {path}")


def _rebuild_recipe(path: str) -> tuple[int, list[str], str]:
    data = "{data_root}/data"
    root = "TARGETIDEATOR_DATA_ROOT={data_root}"
    if path.startswith("opentargets_25_03_25_09_historical_"):
        return (
            1,
            ["opentargets_25_03_associations_raw.json", "opentargets_25_09_associations_raw.json"],
            f"{root} targetideator build-history {data}/opentargets_25_03_associations_raw.json "
            f"{data}/opentargets_25_09_associations_raw.json --output-dir {data} "
            "--snapshot-name opentargets_25_03_25_09_historical_snapshot.json "
            "--manifest-name opentargets_25_03_25_09_historical_manifest.json",
        )
    if path.startswith("clinical_history_"):
        sources = " ".join(f"{data}/{name}" for name in CLINICAL_RAW)
        return 1, list(CLINICAL_RAW), f"{root} targetideator build-clinical-history {sources} --output-dir {data}"
    if path == "opentargets_26_09_manifest.json":
        return 1, ["opentargets_26_09_raw.json"], f"{root} targetideator build-evidence {data}/opentargets_26_09_raw.json --output-dir {data}"
    if path == "literature_manifest.json":
        return 1, ["europepmc_literature_raw.json"], f"{root} targetideator build-literature {data}/europepmc_literature_raw.json --output-dir {data}"
    if path == "claim_graph_manifest.json":
        return 2, ["clinical_history_snapshot.json"], f"{root} targetideator build-claim-graph {data}/clinical_history_snapshot.json --output-dir {data}"

    groups = (
        ("p3_", 3, "build-p3-ideation", ["claim_graph_manifest.json", "literature_manifest.json"]),
        ("p4_falsification_", 4, "build-p4-falsification", ["p3_ideation_manifest.json"]),
        ("p4_revision_", 5, "build-p4-revisions", ["p4_falsification_manifest.json"]),
        ("p5_decision_", 6, "build-p5-decision-engine", ["p4_revision_manifest.json"]),
        ("p5_outcome_", 6, "build-p5-outcomes", ["aact_immune_outcomes_train_raw.json"]),
        ("p5_2_", 7, "build-p5-broad-outcomes", ["aact_broad_outcomes_train_raw.json.gz"]),
        ("p5_3_", 8, "build-p5-identity-ledger", ["p5_2_broad_outcome_manifest.json"]),
        ("p5_4_", 9, "build-p5-mapping-audit", ["p5_3_identity_manifest.json"]),
        ("p5_5_", 10, "build-p5-drug-identity", ["p5_4_mapping_audit_manifest.json"]),
        ("p5_6_", 11, "build-p5-assertion-history", ["p5_5_drug_identity_manifest.json"]),
        ("p5_7_", 12, "build-p5-independent-assertions", ["p5_6_assertion_history_manifest.json"]),
        ("p5_8_", 13, "build-p5-support-audit", ["p5_7_independent_assertion_manifest.json"]),
        ("p5_9_", 14, "build-p5-selection-audit", ["p5_8_support_audit_manifest.json"]),
        ("p6_0_", 15, "build-p6-evaluation", ["p5_9_selection_audit_manifest.json"]),
        ("p6_1_", 16, "build-p6-robustness", ["p6_0_evaluation_manifest.json"]),
        ("p6_2_", 17, "build-p6-cohort-stress", ["p6_1_robustness_manifest.json"]),
        ("p6_3_", 18, "build-p6-paired-control", ["p6_2_cohort_stress_manifest.json"]),
        ("p6_4_", 19, "build-p6-counterevidence-ablation", ["p6_3_paired_control_manifest.json"]),
        ("p6_5_", 20, "build-p6-claim-synthesis", ["p6_4_counterevidence_ablation_manifest.json"]),
        ("p6_6_", 21, "build-p6-paper-bundle", ["p6_5_claim_synthesis_manifest.json"]),
        ("paper/", 21, "build-p6-paper-bundle", ["p6_5_claim_synthesis_manifest.json"]),
    )
    for prefix, stage, command, dependencies in groups:
        if path.startswith(prefix):
            return stage, dependencies, f"{root} targetideator {command} --output-dir {data}"
    raise ValueError(f"No R2.4 rebuild recipe for {path}")


def build_execution_recipe(
    disposition_store: FixtureDispositionStore | None = None,
) -> list[ExecutionRecipeRecord]:
    store = disposition_store or load_default_fixture_disposition_store()
    records = []
    for item in store.ledger():
        if item.decision == "retain":
            continue
        if item.decision == "externalize":
            stage, dependencies, command = _capture_recipe(item.relative_path)
            kind = "operator_capture"
            network_required = True
        else:
            stage, dependencies, command = _rebuild_recipe(item.relative_path)
            kind = "deterministic_rebuild"
            network_required = False
        records.append(
            ExecutionRecipeRecord(
                id=stable_id("execution-recipe", item.relative_path),
                fixture_disposition_id=item.id,
                relative_path=item.relative_path,
                artifact_sha256=item.artifact_sha256,
                artifact_class=item.artifact_class,
                disposition=item.decision,
                recipe_kind=kind,
                command_group_id=stable_id(
                    "execution-command",
                    f"stage-{stage}-{content_digest(command)[:12]}",
                ),
                command_stage=stage,
                dependencies=dependencies,
                operator_command=command,
                projected_output_path=f"data/{item.relative_path}",
                network_required=network_required,
            )
        )
    return records


def build_mutation_preview(
    disposition_store: FixtureDispositionStore | None = None,
) -> list[MutationPreviewRecord]:
    store = disposition_store or load_default_fixture_disposition_store()
    records = []
    for item in store.ledger():
        retain = item.decision == "retain"
        natural_key = (
            "package-init.py" if item.relative_path == "__init__.py" else item.relative_path
        )
        records.append(
            MutationPreviewRecord(
                id=stable_id("mutation-preview", natural_key),
                relative_path=item.relative_path,
                artifact_sha256=item.artifact_sha256,
                artifact_class=item.artifact_class,
                disposition=item.decision,
                projected_packaged=retain,
                preview_action="retain_in_package" if retain else "add_build_exclusion",
                pyproject_exclude_entry=(
                    None
                    if retain
                    else f"src/targetideator/fixtures/{item.relative_path}"
                ),
            )
        )
    return records


def execution_plan_quality(
    recipe: list[ExecutionRecipeRecord],
    preview: list[MutationPreviewRecord],
    inventory_store: RetainedFixtureStore | None = None,
) -> ExecutionPlanQuality:
    inventory = (inventory_store or load_default_retained_fixture_store()).inventory()
    sizes = {row.relative_path: row.byte_count for row in inventory}
    retained_bytes = sum(
        sizes[row.relative_path] for row in preview if row.projected_packaged
    )
    current_bytes = sum(sizes.values())
    return ExecutionPlanQuality(
        unique_operator_command_count=len({row.operator_command for row in recipe}),
        current_retained_byte_count=current_bytes,
        projected_retained_byte_count=retained_bytes,
        projected_excluded_byte_count=current_bytes - retained_bytes,
        blocking_limitations=[
            "Recipes are command-bound but have not been executed or checksum replayed.",
            "The preview does not edit pyproject.toml and does not delete or move source files.",
            "Network captures may not reproduce mutable upstream bytes without archived access.",
            "A projected code-only package is not runtime-ready until all 113 outputs replay.",
            "Package convergence does not authorize redistribution or public release.",
            "R2.4 does not alter scientific claim status or unblock C1/C4.",
        ],
    )


def write_execution_plan_artifacts(
    output_dir: Path, root: Path | None = None
) -> tuple[ExecutionPlanSnapshot, ExecutionPlanManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parent = load_default_fixture_disposition_store()
    recipe = build_execution_recipe(parent)
    preview = build_mutation_preview(parent)
    recipe_path = output_dir / "r2_4_execution_recipe.jsonl.gz"
    preview_path = output_dir / "r2_4_mutation_preview.jsonl.gz"
    _write_jsonl_gzip(recipe_path, [row.model_dump(mode="json") for row in recipe])
    _write_jsonl_gzip(preview_path, [row.model_dump(mode="json") for row in preview])
    quality = execution_plan_quality(recipe, preview)
    snapshot = ExecutionPlanSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        parent_disposition_snapshot_id=parent.snapshot.id,
        parent_disposition_ledger_sha256=parent.manifest.ledger_sha256,
        execution_recipe_path=recipe_path.name,
        execution_recipe_sha256=file_sha256(recipe_path),
        mutation_preview_path=preview_path.name,
        mutation_preview_sha256=file_sha256(preview_path),
        quality=quality,
        warning=(
            "PREVIEW ONLY. Commands are not executed, package configuration is not edited, "
            "and no fixture is deleted, moved, or newly authorized."
        ),
    )
    snapshot_path = output_dir / "r2_4_execution_plan_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = ExecutionPlanManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_portable_source_checksums(root),
        parent_disposition_snapshot_id=parent.snapshot.id,
        parent_disposition_ledger_sha256=parent.manifest.ledger_sha256,
        execution_recipe_path=recipe_path.name,
        execution_recipe_sha256=file_sha256(recipe_path),
        mutation_preview_path=preview_path.name,
        mutation_preview_sha256=file_sha256(preview_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_4_execution_plan_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class ExecutionPlanStore:
    def __init__(self, snapshot: ExecutionPlanSnapshot, manifest: ExecutionPlanManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "ExecutionPlanStore":
        return cls(
            ExecutionPlanSnapshot.model_validate(_load_json(snapshot_path)),
            ExecutionPlanManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _records(self, filename: str, model):
        with gzip.open(self.root / filename, "rt", encoding="utf-8") as stream:
            return [model.model_validate(json.loads(line)) for line in stream]

    def recipe(self) -> list[ExecutionRecipeRecord]:
        return self._records(self.manifest.execution_recipe_path, ExecutionRecipeRecord)

    def preview(self) -> list[MutationPreviewRecord]:
        return self._records(self.manifest.mutation_preview_path, MutationPreviewRecord)

    def quality_report(self) -> dict:
        parent = load_default_fixture_disposition_store()
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "parent_disposition_link_matches": (
                self.manifest.parent_disposition_snapshot_id == parent.snapshot.id
                and self.manifest.parent_disposition_ledger_sha256
                == parent.manifest.ledger_sha256
            ),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.execution_recipe_path)
                == self.manifest.execution_recipe_sha256
                and file_sha256(self.root / self.manifest.mutation_preview_path)
                == self.manifest.mutation_preview_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }


def load_default_execution_plan_store() -> ExecutionPlanStore:
    return ExecutionPlanStore.load(
        default_execution_plan_snapshot_path(), default_execution_plan_manifest_path()
    )
