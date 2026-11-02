"""Load and save TargetIdeator bundles."""

from __future__ import annotations

import json
from pathlib import Path

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.contracts import ProjectBundle, validate_bundle_integrity


def default_seed_path() -> Path:
    return fixture_path("crohns_seed.json")


def load_bundle(path: str | Path | None = None) -> ProjectBundle:
    source = Path(path) if path else default_seed_path()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        bundle = ProjectBundle.model_validate(payload)
        return validate_bundle_integrity(bundle)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Unable to load bundle from {source}: {exc}") from exc


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
