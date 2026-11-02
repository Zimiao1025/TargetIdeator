"""Build a static R1 release-candidate audit without publishing artifacts."""

from __future__ import annotations

import gzip
import json
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from targetideator import __version__
from targetideator.data import fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.models import (
    PackagePayloadRecord,
    ReleaseAuditManifest,
    ReleaseAuditQuality,
    ReleaseAuditSnapshot,
    ReleaseGateOwner,
    ReleaseGateRecord,
    ReleaseGateStatus,
)

BUILDER_VERSION = "r1-static-release-candidate-audit-v1"
SNAPSHOT_ID = "ti:release-audit:r1-artifact-candidate-v1"
CREATED_AT = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)
PAYLOAD_BUDGET_BYTES = 50 * 1024 * 1024
OVERSIZED_FILE_BYTES = 5 * 1024 * 1024
SOURCE_FILES = (
    "pyproject.toml",
    "uv.lock",
    "README.md",
    ".gitignore",
    "src/targetideator/fixtures/paper/REPRODUCE.md",
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _fixture_path(filename: str) -> Path:
    return fixture_path(filename)


def default_release_audit_snapshot_path() -> Path:
    return _fixture_path("r1_release_audit_snapshot.json")


def default_release_audit_manifest_path() -> Path:
    return _fixture_path("r1_release_audit_manifest.json")


def _source_checksums(root: Path | None = None) -> dict[str, str]:
    project_root = root or _project_root()
    return {
        relative_path: file_sha256(project_root / relative_path)
        for relative_path in SOURCE_FILES
    }


def _package_payload(root: Path | None = None) -> list[PackagePayloadRecord]:
    project_root = root or _project_root()
    package_root = project_root / "src" / "targetideator"
    rows = []
    for path in sorted(package_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root).as_posix()
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if "fixtures" in path.parts and path.name.startswith("r1_"):
            continue
        if "fixtures" in path.parts:
            payload_class = "fixture_or_artifact"
            redistribution_review_required = True
        elif path.suffix == ".py":
            payload_class = "code"
            redistribution_review_required = False
        else:
            payload_class = "other"
            redistribution_review_required = False
        rows.append(
            PackagePayloadRecord(
                id=stable_id("release-payload", relative),
                relative_path=relative,
                byte_count=path.stat().st_size,
                payload_class=payload_class,
                redistribution_review_required=redistribution_review_required,
            )
        )
    return rows


def _local_path_findings(root: Path) -> list[str]:
    candidates = [root / "README.md", root / "pyproject.toml"]
    candidates.extend((root / "src" / "targetideator").rglob("*.py"))
    candidates.extend((root / "src" / "targetideator" / "fixtures" / "paper").rglob("*.md"))
    patterns = (
        re.compile(r"/storage\d*/"),
        re.compile(r"/(?:home|Users)/[^/\s]+/"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    findings = []
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in patterns):
            findings.append(path.relative_to(root).as_posix())
    return findings


def _gate(
    gate_id: str,
    passed: bool,
    owner: ReleaseGateOwner,
    evidence: str,
    remediation: str | None = None,
) -> ReleaseGateRecord:
    return ReleaseGateRecord(
        id=stable_id("release-gate", gate_id),
        gate_id=gate_id,
        status=ReleaseGateStatus.PASSED if passed else ReleaseGateStatus.BLOCKED,
        owner=owner,
        evidence=evidence,
        remediation=None if passed else remediation,
    )


def build_release_audit_records(
    root: Path | None = None,
) -> tuple[list[ReleaseGateRecord], list[PackagePayloadRecord], ReleaseAuditQuality]:
    project_root = root or _project_root()
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = str(pyproject["project"]["version"])
    python_bounds = str(pyproject["project"].get("requires-python", ""))
    payload = _package_payload(project_root)
    payload_bytes = sum(row.byte_count for row in payload)
    over_budget = max(0, payload_bytes - PAYLOAD_BUDGET_BYTES)
    oversized_count = sum(row.byte_count > OVERSIZED_FILE_BYTES for row in payload)
    redistribution_count = sum(row.redistribution_review_required for row in payload)
    local_path_findings = _local_path_findings(project_root)
    git_marker_present = (project_root / ".git").exists()
    license_files = [
        path
        for pattern in ("LICENSE", "LICENSE.*", "COPYING", "COPYING.*")
        for path in project_root.glob(pattern)
        if path.is_file()
    ]
    citation_path = project_root / "CITATION.cff"
    ledger_path = project_root / "DATA_REDISTRIBUTION_LEDGER.md"
    ignore_text = (project_root / ".gitignore").read_text(encoding="utf-8")
    required_ignores = {".venv/", "__pycache__/", ".pytest_cache/", "outputs/", "*.pyc"}

    gates = [
        _gate(
            "dependency_lock_present",
            (project_root / "uv.lock").is_file(),
            ReleaseGateOwner.AUTOMATION,
            "uv.lock is present and checksum-bound by the R1 manifest.",
            "Generate and commit uv.lock.",
        ),
        _gate(
            "python_bounds_declared",
            python_bounds == ">=3.11",
            ReleaseGateOwner.AUTOMATION,
            f"pyproject requires-python is {python_bounds!r}.",
            "Declare the tested Python compatibility range.",
        ),
        _gate(
            "package_version_consistent",
            package_version == __version__,
            ReleaseGateOwner.AUTOMATION,
            f"pyproject version {package_version} and package version {__version__} agree.",
            "Synchronize pyproject.toml and targetideator.__version__.",
        ),
        _gate(
            "reproducibility_runbook_present",
            (project_root / "src/targetideator/fixtures/paper/REPRODUCE.md").is_file(),
            ReleaseGateOwner.AUTOMATION,
            "The checksum-bound P6.6 reproduction runbook is packaged.",
            "Add a checksum-bound reproduction runbook.",
        ),
        _gate(
            "release_surface_local_path_clean",
            not local_path_findings,
            ReleaseGateOwner.AUTOMATION,
            f"Static release-surface scan found {len(local_path_findings)} local-path or secret-shaped files.",
            "Remove local paths or secret material from release surfaces.",
        ),
        _gate(
            "ignore_hygiene_present",
            required_ignores.issubset(set(ignore_text.splitlines())),
            ReleaseGateOwner.AUTOMATION,
            "The ignore file covers environments, caches, bytecode, and generated outputs.",
            "Add the required generated-file patterns to .gitignore.",
        ),
        _gate(
            "project_license_declared",
            bool(license_files),
            ReleaseGateOwner.PROJECT_OWNER,
            f"Found {len(license_files)} project license files.",
            "Choose an appropriate project license and add the authoritative LICENSE file; automation must not choose it.",
        ),
        _gate(
            "citation_metadata_complete",
            citation_path.is_file(),
            ReleaseGateOwner.PROJECT_OWNER,
            f"CITATION.cff present: {citation_path.is_file()}.",
            "Provide author-approved names, title, version, and identifiers in CITATION.cff.",
        ),
        _gate(
            "data_redistribution_ledger_complete",
            ledger_path.is_file(),
            ReleaseGateOwner.DATA_STEWARD,
            f"DATA_REDISTRIBUTION_LEDGER.md present: {ledger_path.is_file()}; {redistribution_count} packaged fixture/artifact files require review.",
            "Complete a source-by-source redistribution ledger before public upload.",
        ),
        _gate(
            "project_vcs_root_isolated",
            git_marker_present,
            ReleaseGateOwner.PROJECT_OWNER,
            f"Project-root .git marker present: {git_marker_present}.",
            "Create or move the project into its own repository/worktree before tagging a release.",
        ),
        _gate(
            "package_payload_within_budget",
            payload_bytes <= PAYLOAD_BUDGET_BYTES,
            ReleaseGateOwner.AUTOMATION,
            f"Package payload is {payload_bytes} bytes against a {PAYLOAD_BUDGET_BYTES}-byte budget; {oversized_count} files exceed 5 MiB.",
            "Split bulk/raw fixtures into a separately governed data artifact or implement an external data-root contract.",
        ),
    ]
    passed_count = sum(row.status == ReleaseGateStatus.PASSED for row in gates)
    blocked_count = len(gates) - passed_count
    quality = ReleaseAuditQuality(
        passed_gate_count=passed_count,
        blocked_gate_count=blocked_count,
        safe_automated_hardening_complete=(
            passed_count == 6 and not local_path_findings and package_version == __version__
        ),
        sensitive_local_path_finding_count=len(local_path_findings),
        package_payload_file_count=len(payload),
        package_payload_byte_count=payload_bytes,
        package_payload_over_budget_bytes=over_budget,
        redistribution_review_file_count=redistribution_count,
        oversized_payload_file_count=oversized_count,
        license_file_count=len(license_files),
        citation_file_count=int(citation_path.is_file()),
        redistribution_ledger_file_count=int(ledger_path.is_file()),
        engineering_gate_passed=(len(gates) == 11 and passed_count == 6 and blocked_count == 5),
        blocking_limitations=[
            "No project license has been selected; public redistribution is not authorized by this audit.",
            "Author-approved citation metadata is missing.",
            "Packaged source-derived fixtures lack a completed redistribution ledger.",
            "The project directory is not an isolated repository/worktree root.",
            "The package payload exceeds the 50 MiB release budget and must be split from bulk data.",
        ],
    )
    return gates, payload, quality


def _render_report(snapshot: ReleaseAuditSnapshot, gates: list[ReleaseGateRecord]) -> str:
    q = snapshot.quality
    lines = [
        "# TargetIdeator R1 release-candidate audit",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Release candidate ready: `{str(q.release_candidate_ready).lower()}`",
        f"- Gates passed / blocked: {q.passed_gate_count} / {q.blocked_gate_count}",
        f"- Package payload: {q.package_payload_byte_count} bytes",
        f"- Payload budget: {q.package_payload_budget_bytes} bytes",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- **{row.gate_id}**: `{row.status.value}` ({row.owner.value}) — {row.evidence}"
        for row in gates
    )
    lines.extend(["", "## Upload boundary", "", "No publication or package upload is authorized until all five blockers are resolved.", ""])
    return "\n".join(lines)


def write_release_audit_artifacts(
    output_dir: Path, root: Path | None = None
) -> tuple[ReleaseAuditSnapshot, ReleaseAuditManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    project_root = root or _project_root()
    gates, payload, quality = build_release_audit_records(project_root)
    gate_path = output_dir / "r1_release_gate_audit.jsonl.gz"
    payload_path = output_dir / "r1_package_payload_inventory.jsonl.gz"
    _write_jsonl_gzip(gate_path, [row.model_dump(mode="json") for row in gates])
    _write_jsonl_gzip(payload_path, [row.model_dump(mode="json") for row in payload])
    snapshot = ReleaseAuditSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        gate_audit_path=gate_path.name,
        gate_audit_sha256=file_sha256(gate_path),
        payload_inventory_path=payload_path.name,
        payload_inventory_sha256=file_sha256(payload_path),
        quality=quality,
        warning=(
            "STATIC RELEASE-CANDIDATE AUDIT ONLY. No license choice, legal clearance, "
            "repository creation, publication, or package upload is performed."
        ),
    )
    snapshot_path = output_dir / "r1_release_audit_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "r1_release_audit_report.md").write_text(
        _render_report(snapshot, gates), encoding="utf-8"
    )
    manifest = ReleaseAuditManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(project_root),
        gate_audit_path=gate_path.name,
        gate_audit_sha256=file_sha256(gate_path),
        payload_inventory_path=payload_path.name,
        payload_inventory_sha256=file_sha256(payload_path),
        payload_inventory_record_count=len(payload),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r1_release_audit_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class ReleaseAuditStore:
    def __init__(
        self, snapshot: ReleaseAuditSnapshot, manifest: ReleaseAuditManifest, root: Path
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "ReleaseAuditStore":
        return cls(
            ReleaseAuditSnapshot.model_validate(_load_json(snapshot_path)),
            ReleaseAuditManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _rows(self, filename: str, limit: int) -> list[dict]:
        rows = []
        with gzip.open(self.root / filename, "rt", encoding="utf-8") as stream:
            for line in stream:
                rows.append(json.loads(line))
                if len(rows) >= limit:
                    break
        return rows

    def gates(self) -> list[dict]:
        return self._rows(self.manifest.gate_audit_path, 11)

    def largest_payload_files(self, limit: int = 20) -> list[dict]:
        rows = self._rows(
            self.manifest.payload_inventory_path,
            self.manifest.payload_inventory_record_count,
        )
        return sorted(rows, key=lambda row: (-row["byte_count"], row["relative_path"]))[:limit]

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.gate_audit_path)
                == self.manifest.gate_audit_sha256
                and file_sha256(self.root / self.manifest.payload_inventory_path)
                == self.manifest.payload_inventory_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "historical_snapshot_superseded_by": "ti:packaging-split:r2-code-data-bundle-v1",
            "warning": self.snapshot.warning,
        }


def load_default_release_audit_store() -> ReleaseAuditStore:
    return ReleaseAuditStore.load(
        default_release_audit_snapshot_path(), default_release_audit_manifest_path()
    )
