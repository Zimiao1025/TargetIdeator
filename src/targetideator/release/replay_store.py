"""Execute R2.4 command groups in an isolated staging root and audit outputs."""

from __future__ import annotations

import gzip
import json
import os
import shlex
import subprocess
import sys
import time
from collections import defaultdict
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
from targetideator.release.execution_plan_store import (
    ExecutionPlanStore,
    load_default_execution_plan_store,
)
from targetideator.release.replay_models import (
    ArtifactReplayRecord,
    ExecutionReplayManifest,
    ExecutionReplayQuality,
    ExecutionReplaySnapshot,
    ReplayGroupRecord,
)

BUILDER_VERSION = "r2.5-isolated-command-replay-v1"
SNAPSHOT_ID = "ti:execution-replay:r2.5-isolated-staging-v1"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_execution_replay_snapshot_path() -> Path:
    return fixture_path("r2_5_execution_replay_snapshot.json")


def default_execution_replay_manifest_path() -> Path:
    return fixture_path("r2_5_execution_replay_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    paths = (
        "src/targetideator/release/replay_models.py",
        "src/targetideator/release/replay_store.py",
    )
    return {path: file_sha256(project_root / path) for path in paths}


def _artifact_status(path: Path, expected_sha256: str) -> tuple[str, str | None, int | None]:
    if not path.is_file():
        return "missing", None, None
    observed = file_sha256(path)
    return (
        "exact_match" if observed == expected_sha256 else "checksum_mismatch",
        observed,
        path.stat().st_size,
    )


def _prepare_staging(staging_root: Path, bundle_root: Path) -> int:
    if staging_root.exists():
        raise FileExistsError(f"R2.5 staging root already exists: {staging_root}")
    data_dir = staging_root / "data"
    logs_dir = staging_root / "logs"
    data_dir.mkdir(parents=True)
    logs_dir.mkdir()
    bundle_store = load_default_packaging_split_store()
    linked = 0
    for row in bundle_store.inventory():
        source = bundle_root / row["relative_path"]
        if not source.is_file() or file_sha256(source) != row["sha256"]:
            raise ValueError(f"Bulk bundle artifact is absent or mismatched: {source}")
        (data_dir / row["filename"]).symlink_to(source.resolve())
        linked += 1
    if linked != len(EXTERNALIZED_FILENAMES):
        raise ValueError(f"Expected 24 bulk links, created {linked}")
    return linked


def _command_argv(template: str, staging_root: Path) -> tuple[list[str], dict[str, str]]:
    resolved = template.replace("{data_root}", str(staging_root.resolve()))
    tokens = shlex.split(resolved)
    env = os.environ.copy()
    env["TARGETIDEATOR_DATA_ROOT"] = str(staging_root.resolve())
    if tokens and tokens[0].startswith("TARGETIDEATOR_DATA_ROOT="):
        tokens = tokens[1:]
    if not tokens or tokens[0] != "targetideator":
        raise ValueError(f"Unsupported R2.5 command template: {template}")
    return [sys.executable, "-m", "targetideator.cli", *tokens[1:]], env


def run_execution_replay(
    staging_root: Path,
    bundle_root: Path,
    *,
    command_timeout_seconds: int = 7200,
    plan_store: ExecutionPlanStore | None = None,
) -> tuple[ExecutionReplaySnapshot, ExecutionReplayManifest]:
    plan = plan_store or load_default_execution_plan_store()
    _prepare_staging(staging_root, bundle_root)
    recipes = plan.recipe()
    grouped = defaultdict(list)
    for row in recipes:
        grouped[row.command_group_id].append(row)
    ordered = sorted(
        grouped.items(),
        key=lambda item: (item[1][0].command_stage, item[0]),
    )
    if len(ordered) != 31:
        raise ValueError(f"Expected 31 command groups, found {len(ordered)}")

    group_rows = []
    artifact_rows = []
    for group_index, (group_id, outputs) in enumerate(ordered, start=1):
        template = outputs[0].operator_command
        if any(row.operator_command != template for row in outputs):
            raise ValueError(f"Command group {group_id} has inconsistent templates")
        argv, env = _command_argv(template, staging_root)
        started = datetime.now(timezone.utc)
        before = time.monotonic()
        try:
            result = subprocess.run(
                argv,
                cwd=_project_root(),
                env=env,
                capture_output=True,
                text=True,
                timeout=command_timeout_seconds,
                check=False,
            )
            exit_code = result.returncode
            stdout = result.stdout
            stderr = result.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + "\nR2.5 command timeout"
        completed = datetime.now(timezone.utc)
        duration = time.monotonic() - before
        log_stem = f"{group_index:02d}_stage_{outputs[0].command_stage}_{group_id.rsplit(':', 1)[-1]}"
        stdout_path = staging_root / "logs" / f"{log_stem}.stdout.log"
        stderr_path = staging_root / "logs" / f"{log_stem}.stderr.log"
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")

        counts = {"exact_match": 0, "checksum_mismatch": 0, "missing": 0}
        for recipe in outputs:
            output_path = staging_root / recipe.projected_output_path
            status, observed_sha, observed_bytes = _artifact_status(
                output_path, recipe.artifact_sha256
            )
            counts[status] += 1
            artifact_rows.append(
                ArtifactReplayRecord(
                    id=stable_id("artifact-replay", recipe.relative_path),
                    execution_recipe_id=recipe.id,
                    command_group_id=group_id,
                    relative_path=recipe.relative_path,
                    disposition=recipe.disposition,
                    expected_sha256=recipe.artifact_sha256,
                    observed_sha256=observed_sha,
                    observed_byte_count=observed_bytes,
                    status=status,
                )
            )
        group_rows.append(
            ReplayGroupRecord(
                id=stable_id("replay-group", group_id.rsplit(":", 1)[-1]),
                command_group_id=group_id,
                command_stage=outputs[0].command_stage,
                command_template=template,
                network_required=outputs[0].network_required,
                expected_output_paths=[row.relative_path for row in outputs],
                started_at=started,
                completed_at=completed,
                duration_seconds=duration,
                exit_code=exit_code,
                status="completed" if exit_code == 0 else "failed",
                exact_match_count=counts["exact_match"],
                checksum_mismatch_count=counts["checksum_mismatch"],
                missing_count=counts["missing"],
                stdout_log_path=stdout_path.relative_to(staging_root).as_posix(),
                stderr_log_path=stderr_path.relative_to(staging_root).as_posix(),
            )
        )

    group_path = staging_root / "r2_5_group_replay.jsonl.gz"
    artifact_path = staging_root / "r2_5_artifact_replay.jsonl.gz"
    _write_jsonl_gzip(group_path, [row.model_dump(mode="json") for row in group_rows])
    _write_jsonl_gzip(artifact_path, [row.model_dump(mode="json") for row in artifact_rows])
    exact = sum(row.status == "exact_match" for row in artifact_rows)
    mismatch = sum(row.status == "checksum_mismatch" for row in artifact_rows)
    missing = sum(row.status == "missing" for row in artifact_rows)
    successful = sum(row.status == "completed" for row in group_rows)
    quality = ExecutionReplayQuality(
        executed_command_group_count=len(group_rows),
        successful_command_group_count=successful,
        failed_command_group_count=len(group_rows) - successful,
        exact_match_count=exact,
        checksum_mismatch_count=mismatch,
        missing_count=missing,
        externalize_exact_match_count=sum(
            row.disposition == "externalize" and row.status == "exact_match"
            for row in artifact_rows
        ),
        regenerate_exact_match_count=sum(
            row.disposition == "regenerate" and row.status == "exact_match"
            for row in artifact_rows
        ),
        replay_execution_complete=len(group_rows) == 31,
        checksum_replay_gate_passed=exact == 113,
        blocking_limitations=[
            "Live source captures may differ from frozen bytes because of timestamps or upstream drift.",
            "A completed command is not an exact replay unless every expected output checksum matches.",
            "No mismatch is automatically accepted as a new release artifact.",
            "Runtime smoke and package configuration mutation remain separate closed gates.",
            "Replay does not authorize redistribution or alter scientific claim status or C1/C4.",
        ],
    )
    snapshot = ExecutionReplaySnapshot(
        id=SNAPSHOT_ID,
        created_at=datetime.now(timezone.utc),
        parent_execution_plan_snapshot_id=plan.snapshot.id,
        parent_execution_recipe_sha256=plan.manifest.execution_recipe_sha256,
        staging_root_label=staging_root.name,
        group_replay_path=group_path.name,
        group_replay_sha256=file_sha256(group_path),
        artifact_replay_path=artifact_path.name,
        artifact_replay_sha256=file_sha256(artifact_path),
        quality=quality,
        warning=(
            "ISOLATED REPLAY RESULT. Existing fixtures, package configuration, and source files "
            "were not deleted or rewritten; checksum drift remains unresolved."
        ),
    )
    snapshot_path = staging_root / "r2_5_execution_replay_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = ExecutionReplayManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        parent_execution_plan_snapshot_id=plan.snapshot.id,
        parent_execution_recipe_sha256=plan.manifest.execution_recipe_sha256,
        group_replay_path=group_path.name,
        group_replay_sha256=file_sha256(group_path),
        artifact_replay_path=artifact_path.name,
        artifact_replay_sha256=file_sha256(artifact_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        staging_root / "r2_5_execution_replay_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class ExecutionReplayStore:
    def __init__(self, snapshot: ExecutionReplaySnapshot, manifest: ExecutionReplayManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "ExecutionReplayStore":
        return cls(
            ExecutionReplaySnapshot.model_validate(_load_json(snapshot_path)),
            ExecutionReplayManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _records(self, filename: str, model):
        with gzip.open(self.root / filename, "rt", encoding="utf-8") as stream:
            return [model.model_validate(json.loads(line)) for line in stream]

    def groups(self) -> list[ReplayGroupRecord]:
        return self._records(self.manifest.group_replay_path, ReplayGroupRecord)

    def artifacts(self) -> list[ArtifactReplayRecord]:
        return self._records(self.manifest.artifact_replay_path, ArtifactReplayRecord)

    def quality_report(self) -> dict:
        plan = load_default_execution_plan_store()
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "parent_execution_plan_link_matches": (
                self.manifest.parent_execution_plan_snapshot_id == plan.snapshot.id
                and self.manifest.parent_execution_recipe_sha256
                == plan.manifest.execution_recipe_sha256
            ),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.group_replay_path)
                == self.manifest.group_replay_sha256
                and file_sha256(self.root / self.manifest.artifact_replay_path)
                == self.manifest.artifact_replay_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }
