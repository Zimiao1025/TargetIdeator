"""Resolve packaged fixtures and the optional external TargetIdeator data root."""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

DATA_ROOT_ENV = "TARGETIDEATOR_DATA_ROOT"


class MissingDataArtifactError(FileNotFoundError):
    """Raised when a bulk fixture is absent from both wheel and external data root."""


def packaged_fixture_path(filename: str) -> Path:
    return Path(str(files("targetideator.fixtures").joinpath(filename)))


def external_data_root() -> Path | None:
    value = os.environ.get(DATA_ROOT_ENV)
    if not value:
        return None
    return Path(value).expanduser().resolve()


def fixture_path(filename: str) -> Path:
    """Return an external artifact when present, otherwise the packaged fixture.

    The external root may contain files directly or below a ``data`` directory, which
    is the layout emitted by the R2 bundle builder. Small contracts can therefore stay
    in the wheel while bulk files are resolved from the external bundle.
    """

    data_root = external_data_root()
    if data_root is not None:
        for candidate in (data_root / filename, data_root / "data" / filename):
            if candidate.is_file():
                return candidate

    packaged = packaged_fixture_path(filename)
    if packaged.is_file():
        return packaged

    location = str(data_root) if data_root is not None else "<not configured>"
    raise MissingDataArtifactError(
        f"Required TargetIdeator data artifact {filename!r} is not packaged. "
        f"Set {DATA_ROOT_ENV} to a validated R2 data-bundle root; current value: {location}."
    )


def artifact_path(root: Path, relative_path: str) -> Path:
    """Resolve a manifest-relative artifact across packaged and external roots."""

    relative = Path(relative_path)
    data_root = external_data_root()
    if data_root is not None:
        candidates = [data_root / relative, data_root / "data" / relative]
        if relative.parts and relative.parts[0] == "data":
            candidates.append(data_root / relative.relative_to("data"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate

    local = root / relative
    if local.is_file():
        return local

    packaged = packaged_fixture_path(relative.name)
    if packaged.is_file():
        return packaged

    location = str(data_root) if data_root is not None else "<not configured>"
    raise MissingDataArtifactError(
        f"Required manifest artifact {relative_path!r} is unavailable below "
        f"{root} or {DATA_ROOT_ENV}={location}."
    )
