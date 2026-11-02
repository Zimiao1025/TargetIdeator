"""Reproducibility manifest for a dossier export."""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from targetideator import __version__
from targetideator.contracts import ProjectBundle
from targetideator.ids import content_digest
from targetideator.io import write_json


def _git_commit() -> str:
    override = os.getenv("TARGETIDEATOR_GIT_COMMIT")
    if override:
        return override
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unversioned"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    bundle: ProjectBundle,
    artifacts: list[Path],
    *,
    created_at: datetime | None = None,
) -> dict[str, object]:
    payload = bundle.model_dump(mode="json")
    input_hash = content_digest(payload)
    timestamp = created_at or datetime.now(timezone.utc)
    return {
        "run_id": f"ti:run:{input_hash[:16]}",
        "created_at": timestamp.astimezone(timezone.utc).isoformat(),
        "targetideator_version": __version__,
        "git_commit": _git_commit(),
        "schema_version": bundle.schema_version,
        "snapshot_id": bundle.snapshot_id,
        "evidence_cutoff": bundle.disease_brief.as_of_date.isoformat(),
        "input_sha256": input_hash,
        "model_ids": [],
        "configuration": {
            "mode": "p0_fixture_export",
            "scientific_scoring_enabled": False,
        },
        "artifacts": [
            {"path": path.name, "sha256": _file_sha256(path), "bytes": path.stat().st_size}
            for path in sorted(artifacts)
        ],
    }


def write_manifest(
    bundle: ProjectBundle,
    artifacts: list[Path],
    output_dir: Path,
    *,
    created_at: datetime | None = None,
) -> Path:
    path = output_dir / "run_manifest.json"
    write_json(path, build_manifest(bundle, artifacts, created_at=created_at))
    return path
