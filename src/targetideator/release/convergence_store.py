"""R2.8 applied package exclusions, offline wheel smoke, and convergence audit."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.canonical_store import CanonicalAcceptanceStore
from targetideator.release.convergence_models import (
    PackageConvergenceManifest,
    PackageConvergenceQuality,
    PackageConvergenceSnapshot,
    PackageFileAuditRecord,
    RuntimeSmokeRecord,
)
from targetideator.release.data_bundle_store import EXTERNALIZED_FILENAMES
from targetideator.release.execution_plan_store import load_default_execution_plan_store

BUILDER_VERSION = "r2.8-package-convergence-v1"
SELF_ATTESTATION_PATHS = {
    "src/targetideator/fixtures/r2_8_convergence/r2_8_package_convergence_manifest.json",
    "src/targetideator/fixtures/r2_8_convergence/r2_8_package_convergence_snapshot.json",
    "src/targetideator/fixtures/r2_8_convergence/r2_8_package_file_audit.jsonl.gz",
    "src/targetideator/fixtures/r2_8_convergence/r2_8_runtime_smoke.jsonl.gz",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_checksums() -> dict[str, str]:
    root = _project_root()
    paths = (
        "pyproject.toml",
        "src/targetideator/cli.py",
        "src/targetideator/data.py",
        "src/targetideator/demo.py",
        "src/targetideator/package_convergence_demo.py",
        "src/targetideator/release/convergence_models.py",
        "src/targetideator/release/convergence_store.py",
        "src/targetideator/release/retained_fixture_store.py",
    )
    return {path: file_sha256(root / path) for path in paths}


def default_canonical_acceptance_root() -> Path:
    return fixture_path("r2_7_canonical/r2_7_canonical_acceptance_snapshot.json").parent


def load_default_canonical_acceptance_store() -> CanonicalAcceptanceStore:
    root = default_canonical_acceptance_root()
    return CanonicalAcceptanceStore.load(
        root / "r2_7_canonical_acceptance_snapshot.json",
        root / "r2_7_canonical_acceptance_manifest.json",
    )


def _configured_exclusions() -> tuple[set[str], set[str]]:
    with (_project_root() / "pyproject.toml").open("rb") as stream:
        config = tomllib.load(stream)
    targets = config["tool"]["hatch"]["build"]["targets"]
    return set(targets["wheel"]["exclude"]), set(targets["sdist"]["exclude"])


def _expected_exclusions() -> tuple[set[str], set[str], set[str], set[str]]:
    existing = {
        f"src/targetideator/fixtures/{filename}"
        for filename in EXTERNALIZED_FILENAMES
    }
    owner = {
        f"src/targetideator/fixtures/{row.relative_path}"
        for row in load_default_execution_plan_store().preview()
        if not row.projected_packaged
    }
    return existing, owner, SELF_ATTESTATION_PATHS, existing | owner | SELF_ATTESTATION_PATHS


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_smoke(
    check_name: str,
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> tuple[RuntimeSmokeRecord, subprocess.CompletedProcess[str]]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = time.monotonic() - started
    record = RuntimeSmokeRecord(
        id=stable_id("runtime-smoke", check_name),
        check_name=check_name,
        command=command,
        exit_code=result.returncode,
        status="passed" if result.returncode == 0 else "failed",
        duration_seconds=duration,
        stdout_sha256=_sha_text(result.stdout),
        stderr_sha256=_sha_text(result.stderr),
    )
    return record, result


def _require_passed(record: RuntimeSmokeRecord, result: subprocess.CompletedProcess[str]) -> None:
    if record.status != "passed":
        raise RuntimeError(
            f"R2.8 smoke check {record.check_name} failed with {record.exit_code}: "
            f"{result.stderr[-2000:]}"
        )


def run_package_convergence(
    output_dir: Path,
    external_data_root: Path,
    canonical_root: Path | None = None,
) -> tuple[PackageConvergenceSnapshot, PackageConvergenceManifest]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"R2.8 output directory must be new or empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir = output_dir.resolve()
    external_data_root = external_data_root.resolve()
    if not external_data_root.is_dir():
        raise FileNotFoundError(f"External smoke data root is absent: {external_data_root}")

    canonical_root = (canonical_root or default_canonical_acceptance_root()).resolve()
    canonical = CanonicalAcceptanceStore.load(
        canonical_root / "r2_7_canonical_acceptance_snapshot.json",
        canonical_root / "r2_7_canonical_acceptance_manifest.json",
    )
    canonical_report = canonical.quality_report()
    if not canonical_report["canonical_content_gate_passed"]:
        raise ValueError("R2.7 canonical-content gate is not passed")
    parent_manifest_source = canonical_root / "r2_7_canonical_acceptance_manifest.json"
    parent_manifest_path = output_dir / parent_manifest_source.name
    shutil.copy2(parent_manifest_source, parent_manifest_path)

    existing, owner, self_attestation, expected = _expected_exclusions()
    wheel_config, sdist_config = _configured_exclusions()
    if (
        len(existing) != 24
        or len(owner) != 113
        or len(self_attestation) != 4
        or len(expected) != 141
    ):
        raise ValueError("Expected the frozen 24 + 113 + 4 = 141 exclusion partition")
    if wheel_config != expected or sdist_config != expected:
        raise ValueError("pyproject exclusions do not exactly match the frozen 137-file ledger")
    missing_source = [path for path in expected if not (_project_root() / path).is_file()]
    if missing_source:
        raise FileNotFoundError(f"Excluded source files were deleted: {missing_source[:5]}")

    offline_env = os.environ.copy()
    offline_env["UV_OFFLINE"] = "1"
    offline_env.pop("TARGETIDEATOR_DATA_ROOT", None)
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv is required for the R2.8 offline package smoke")
    smoke_records: list[RuntimeSmokeRecord] = []

    dist_dir = output_dir / "dist"
    build_command = [
        uv,
        "build",
        "--wheel",
        "--offline",
        "--no-progress",
        "--no-create-gitignore",
        "--out-dir",
        str(dist_dir),
        str(_project_root()),
    ]
    record, result = _run_smoke(
        "offline_wheel_build", build_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)
    wheels = list(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"Expected exactly one wheel, found {len(wheels)}")
    wheel_path = wheels[0].resolve()
    with ZipFile(wheel_path) as archive:
        wheel_files = archive.namelist()
    packaged = set(wheel_files)
    expected_wheel_absent = {path.removeprefix("src/") for path in expected}
    unexpectedly_packaged = expected_wheel_absent & packaged

    smoke_env = output_dir / "smoke-env"
    venv_command = [
        uv,
        "venv",
        "--offline",
        "--no-project",
        "--no-config",
        "--python",
        sys.executable,
        str(smoke_env),
    ]
    record, result = _run_smoke(
        "isolated_venv_creation", venv_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)
    smoke_python = smoke_env / "bin" / "python"

    install_command = [
        uv,
        "pip",
        "install",
        "--offline",
        "--python",
        str(smoke_python),
        str(wheel_path),
    ]
    record, result = _run_smoke(
        "offline_wheel_install", install_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)

    import_script = (
        "from pathlib import Path; import targetideator, targetideator.cli; "
        f"root=Path({str(smoke_env)!r}).resolve(); "
        "location=Path(targetideator.__file__).resolve(); "
        "assert location.is_relative_to(root), location; print(location)"
    )
    import_command = [str(smoke_python), "-I", "-c", import_script]
    record, result = _run_smoke(
        "installed_import", import_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)

    cli_command = [str(smoke_python), "-I", "-m", "targetideator.cli", "--help"]
    record, result = _run_smoke(
        "cli_help", cli_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)

    missing_script = (
        "from targetideator.data import MissingDataArtifactError, fixture_path\n"
        "try:\n"
        "    fixture_path('claim_graph_manifest.json')\n"
        "except MissingDataArtifactError as exc:\n"
        "    assert 'TARGETIDEATOR_DATA_ROOT' in str(exc)\n"
        "else:\n"
        "    raise SystemExit('excluded artifact unexpectedly packaged')\n"
    )
    missing_command = [str(smoke_python), "-I", "-c", missing_script]
    record, result = _run_smoke(
        "missing_data_error_contract", missing_command, cwd=output_dir, env=offline_env
    )
    smoke_records.append(record)
    _require_passed(record, result)

    external_script = (
        "from targetideator.data import fixture_path\n"
        "from targetideator.release.data_bundle_store import EXTERNALIZED_FILENAMES\n"
        "from targetideator.release.execution_plan_store import load_default_execution_plan_store\n"
        "owner=[r.relative_path for r in load_default_execution_plan_store().preview() if not r.projected_packaged]\n"
        "targets=sorted(set(owner)|set(EXTERNALIZED_FILENAMES))\n"
        "resolved=[fixture_path(path) for path in targets]\n"
        "assert len(targets)==137 and all(path.is_file() for path in resolved)\n"
        "import targetideator.demo as demo\n"
        "assert any(route.path == '/health' for route in demo.app.routes)\n"
        "health=next(route.endpoint for route in demo.app.routes if route.path == '/health')()\n"
        "assert health['status']=='ok'\n"
        "assert health['package_convergence_snapshot_id']=='external-self-attestation-not-configured'\n"
        "print(f'external-resolution={len(resolved)} app-routes={len(demo.app.routes)} health=ok')\n"
    )
    external_command = [str(smoke_python), "-I", "-c", external_script]
    external_env = offline_env.copy()
    external_env["TARGETIDEATOR_DATA_ROOT"] = str(external_data_root)
    record, result = _run_smoke(
        "external_data_and_app_factory",
        external_command,
        cwd=output_dir,
        env=external_env,
    )
    smoke_records.append(record)
    _require_passed(record, result)

    all_smoke_passed = len(smoke_records) == 7 and all(
        row.status == "passed" for row in smoke_records
    )
    file_rows = []
    for source_path in sorted(expected):
        relative_path = source_path.removeprefix("src/targetideator/fixtures/")
        external_required = source_path not in self_attestation
        file_rows.append(
            PackageFileAuditRecord(
                id=stable_id("package-file-audit", relative_path),
                relative_path=relative_path,
                exclusion_origin=(
                    "existing_bulk_split"
                    if source_path in existing
                    else (
                        "r2_4_owner_disposition"
                        if source_path in owner
                        else "r2_8_external_self_attestation"
                    )
                ),
                source_file_present=(_project_root() / source_path).is_file(),
                wheel_exclusion_configured=source_path in wheel_config,
                sdist_exclusion_configured=source_path in sdist_config,
                absent_from_built_wheel=source_path.removeprefix("src/") not in packaged,
                external_resolution_required=external_required,
                external_resolution_smoke_passed=(
                    all_smoke_passed if external_required else False
                ),
            )
        )

    file_audit_path = output_dir / "r2_8_package_file_audit.jsonl.gz"
    smoke_path = output_dir / "r2_8_runtime_smoke.jsonl.gz"
    _write_jsonl_gzip(file_audit_path, [row.model_dump(mode="json") for row in file_rows])
    _write_jsonl_gzip(smoke_path, [row.model_dump(mode="json") for row in smoke_records])
    runtime_gate = all_smoke_passed and not unexpectedly_packaged
    convergence_gate = (
        canonical_report["canonical_content_gate_passed"]
        and runtime_gate
        and len(file_rows) == 141
        and all(
            row.source_file_present
            and row.wheel_exclusion_configured
            and row.sdist_exclusion_configured
            and row.absent_from_built_wheel
            and (
                not row.external_resolution_required
                or row.external_resolution_smoke_passed
            )
            for row in file_rows
        )
    )
    fixture_count = sum(
        path.startswith("targetideator/fixtures/") for path in wheel_files
    )
    quality = PackageConvergenceQuality(
        source_file_present_count=sum(row.source_file_present for row in file_rows),
        external_self_attestation_exclusion_count=len(self_attestation),
        governed_data_exclusion_count=len(existing | owner),
        wheel_config_exclusion_count=len(wheel_config),
        sdist_config_exclusion_count=len(sdist_config),
        configuration_mutation_applied=(wheel_config == expected and sdist_config == expected),
        built_wheel_byte_count=wheel_path.stat().st_size,
        built_wheel_file_count=len(wheel_files),
        built_wheel_fixture_count=fixture_count,
        unexpectedly_packaged_excluded_count=len(unexpectedly_packaged),
        external_resolution_smoke_count=(137 if all_smoke_passed else 0),
        runtime_smoke_passed_count=sum(row.status == "passed" for row in smoke_records),
        projected_runtime_smoke_gate_passed=runtime_gate,
        package_convergence_gate_passed=convergence_gate,
        blocking_limitations=[
            "Package convergence covers code/data separation and installed runtime behavior, not public data redistribution rights.",
            "The external data bundle remains local-only until the source-by-source redistribution ledger is complete.",
            "The installed package requires TARGETIDEATOR_DATA_ROOT for workflows that use the 137 excluded artifacts.",
            "Four R2.8 self-attestation files stay outside the attested wheel to avoid a recursive wheel-checksum cycle.",
            "R2.8 does not select a project license, publish a wheel, or alter scientific claim status or C1/C4.",
        ],
    )
    snapshot = PackageConvergenceSnapshot(
        id=stable_id("package-convergence", wheel_path.name),
        created_at=datetime.now(timezone.utc),
        parent_canonical_acceptance_snapshot_id=canonical.snapshot.id,
        parent_canonical_acceptance_manifest_sha256=file_sha256(parent_manifest_path),
        pyproject_sha256=file_sha256(_project_root() / "pyproject.toml"),
        wheel_path=wheel_path.relative_to(output_dir).as_posix(),
        wheel_sha256=file_sha256(wheel_path),
        file_audit_path=file_audit_path.name,
        file_audit_sha256=file_sha256(file_audit_path),
        runtime_smoke_path=smoke_path.name,
        runtime_smoke_sha256=file_sha256(smoke_path),
        quality=quality,
        warning=(
            "ENGINEERING PACKAGE CONVERGENCE ONLY. The wheel passed offline runtime smoke, "
            "but neither the wheel nor the external data bundle is authorized for publication."
        ),
    )
    snapshot_path = output_dir / "r2_8_package_convergence_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = PackageConvergenceManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        parent_canonical_acceptance_snapshot_id=canonical.snapshot.id,
        parent_canonical_acceptance_manifest_sha256=file_sha256(parent_manifest_path),
        pyproject_sha256=file_sha256(_project_root() / "pyproject.toml"),
        wheel_path=snapshot.wheel_path,
        wheel_sha256=snapshot.wheel_sha256,
        file_audit_path=file_audit_path.name,
        file_audit_sha256=file_sha256(file_audit_path),
        runtime_smoke_path=smoke_path.name,
        runtime_smoke_sha256=file_sha256(smoke_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_8_package_convergence_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class PackageConvergenceStore:
    def __init__(
        self,
        snapshot: PackageConvergenceSnapshot,
        manifest: PackageConvergenceManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "PackageConvergenceStore":
        return cls(
            PackageConvergenceSnapshot.model_validate(_load_json(snapshot_path)),
            PackageConvergenceManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _records(self, filename: str, model):
        with gzip.open(self.root / filename, "rt", encoding="utf-8") as stream:
            return [model.model_validate(json.loads(line)) for line in stream]

    def file_audit(self) -> list[PackageFileAuditRecord]:
        return self._records(self.manifest.file_audit_path, PackageFileAuditRecord)

    def runtime_smoke(self) -> list[RuntimeSmokeRecord]:
        return self._records(self.manifest.runtime_smoke_path, RuntimeSmokeRecord)

    def quality_report(self) -> dict:
        parent_manifest = self.root / "r2_7_canonical_acceptance_manifest.json"
        wheel = self.root / self.manifest.wheel_path
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "parent_canonical_acceptance_link_matches": (
                parent_manifest.is_file()
                and file_sha256(parent_manifest)
                == self.manifest.parent_canonical_acceptance_manifest_sha256
            ),
            "metadata_artifact_checksums_match": (
                file_sha256(self.root / self.manifest.file_audit_path)
                == self.manifest.file_audit_sha256
                and file_sha256(self.root / self.manifest.runtime_smoke_path)
                == self.manifest.runtime_smoke_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "wheel_artifact_available": wheel.is_file(),
            "wheel_checksum_matches": (
                file_sha256(wheel) == self.manifest.wheel_sha256
                if wheel.is_file()
                else None
            ),
            "pyproject_checksum_matches": (
                file_sha256(_project_root() / "pyproject.toml")
                == self.manifest.pyproject_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }
