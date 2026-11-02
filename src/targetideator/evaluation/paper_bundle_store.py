"""Build the P6.6 reproducible methods/artifact and negative-results bundle."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.evaluation.paper_bundle_models import (
    PaperBundleManifest,
    PaperBundleQuality,
    PaperBundleSnapshot,
    PaperFileInventoryRecord,
    PaperFileRole,
    ReadinessGateRecord,
    ReadinessGateStatus,
    SourceManifestInventoryRecord,
)
from targetideator.evaluation.store import load_default_evaluation_store
from targetideator.evaluation.synthesis_store import load_default_claim_synthesis_store
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip

BUILDER_VERSION = "p6.6-reproducible-paper-artifact-bundle-v1"
SNAPSHOT_ID = "ti:paper-bundle:reproducible-methods-negative-results-v1"
CREATED_AT = datetime(2026, 11, 3, 14, 0, tzinfo=timezone.utc)

P6_MANIFESTS = {
    "P6.0": "p6_0_evaluation_manifest.json",
    "P6.1": "p6_1_robustness_manifest.json",
    "P6.2": "p6_2_cohort_stress_manifest.json",
    "P6.3": "p6_3_paired_control_manifest.json",
    "P6.4": "p6_4_counterevidence_ablation_manifest.json",
    "P6.5": "p6_5_claim_synthesis_manifest.json",
}

PAPER_FILES = {
    "paper/README.md": PaperFileRole.INDEX,
    "paper/POSITIONING.md": PaperFileRole.POSITIONING,
    "paper/METHODS.md": PaperFileRole.METHODS,
    "paper/RESULTS.md": PaperFileRole.RESULTS,
    "paper/LIMITATIONS.md": PaperFileRole.LIMITATIONS,
    "paper/REPRODUCE.md": PaperFileRole.REPRODUCIBILITY,
    "paper/tables/table_1_source_manifest_inventory.md": PaperFileRole.TABLE,
    "paper/tables/table_2_claim_disposition.md": PaperFileRole.TABLE,
    "paper/tables/table_3_readiness_gates.md": PaperFileRole.TABLE,
}


def _fixture_path(filename: str) -> Path:
    return fixture_path(filename)


def default_paper_bundle_snapshot_path() -> Path:
    return _fixture_path("p6_6_paper_bundle_snapshot.json")


def default_paper_bundle_manifest_path() -> Path:
    return _fixture_path("p6_6_paper_bundle_manifest.json")


def _manifest_snapshot_id(path: Path, fallback: str) -> str:
    manifest = _load_json(path)
    return str(manifest.get("snapshot_id") or manifest.get("portfolio_id") or fallback)


def _source_manifest_inventory() -> list[SourceManifestInventoryRecord]:
    p60_inventory = load_default_evaluation_store().artifacts()
    rows = []
    for item in p60_inventory:
        filename = item["manifest_filename"]
        path = _fixture_path(filename)
        rows.append(
            SourceManifestInventoryRecord(
                id=stable_id("paper-source-manifest", item["stage_id"]),
                stage_id=item["stage_id"],
                manifest_filename=filename,
                manifest_sha256=file_sha256(path),
                source_snapshot_id=_manifest_snapshot_id(path, item["stage_id"]),
            )
        )
    for stage_id, filename in P6_MANIFESTS.items():
        path = _fixture_path(filename)
        rows.append(
            SourceManifestInventoryRecord(
                id=stable_id("paper-source-manifest", stage_id),
                stage_id=stage_id,
                manifest_filename=filename,
                manifest_sha256=file_sha256(path),
                source_snapshot_id=_manifest_snapshot_id(path, stage_id),
            )
        )
    rows.sort(key=lambda row: tuple(int(x) for x in row.stage_id[1:].split(".")))
    if len(rows) != 22 or len({row.manifest_filename for row in rows}) != 22:
        raise ValueError("paper bundle requires exactly 22 distinct source manifests")
    return rows


def _source_checksums() -> dict[str, str]:
    return {
        row.manifest_filename: row.manifest_sha256
        for row in _source_manifest_inventory()
    }


def _readiness_gates() -> list[ReadinessGateRecord]:
    rows = [
        {
            "gate_id": "artifact_checksum_completeness",
            "status": ReadinessGateStatus.PASSED,
            "gate_scope": "artifact_release",
            "evidence": "All 22 claim-relevant source manifests have frozen SHA-256 checksums.",
        },
        {
            "gate_id": "deterministic_rebuild_contract",
            "status": ReadinessGateStatus.PASSED,
            "gate_scope": "artifact_release",
            "evidence": "P6.0-P6.5 expose deterministic builders, manifests, and verifier commands.",
        },
        {
            "gate_id": "negative_result_preservation",
            "status": ReadinessGateStatus.PASSED,
            "gate_scope": "artifact_release",
            "evidence": "The P6.4 decision-level negative result is present in results, limitations, and the claim table.",
        },
        {
            "gate_id": "headline_scientific_claim_support",
            "status": ReadinessGateStatus.BLOCKED,
            "gate_scope": "scientific_submission",
            "evidence": "P6.5 reports zero scientifically supported claims and zero claim-status promotions.",
            "blocking_reason": "C1-C4 lack the required identified benchmark, gold labels, or decision metrics.",
        },
        {
            "gate_id": "target_benchmark_identification",
            "status": ReadinessGateStatus.BLOCKED,
            "gate_scope": "scientific_submission",
            "evidence": "P5.9 found material mapping selection and retained the target-validation no-go.",
            "blocking_reason": "The mapped target subset is not exchangeable with the intended benchmark population.",
        },
        {
            "gate_id": "final_human_gold",
            "status": ReadinessGateStatus.BLOCKED,
            "gate_scope": "scientific_submission",
            "evidence": "The literature layer remains provisional/model-assisted rather than final adjudicated human gold.",
            "blocking_reason": "No completed independent double review and adjudication are available by design.",
        },
    ]
    return [
        ReadinessGateRecord(id=stable_id("paper-readiness-gate", row["gate_id"]), **row)
        for row in rows
    ]


def _render_source_table(rows: list[SourceManifestInventoryRecord]) -> str:
    lines = [
        "# Table 1. Frozen source-manifest inventory",
        "",
        "| Stage | Manifest | Snapshot | SHA-256 |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {row.stage_id} | `{row.manifest_filename}` | `{row.source_snapshot_id}` | `{row.manifest_sha256}` |"
        for row in rows
    )
    lines.append("")
    return "\n".join(lines)


def _render_gate_table(rows: list[ReadinessGateRecord]) -> str:
    lines = [
        "# Table 3. Artifact and scientific readiness gates",
        "",
        "| Gate | Scope | Status | Evidence / blocking reason |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| `{row.gate_id}` | {row.gate_scope} | **{row.status.value}** | "
        f"{row.evidence}{' Blocker: ' + row.blocking_reason if row.blocking_reason else ''} |"
        for row in rows
    )
    lines.append("")
    return "\n".join(lines)


def _paper_content(
    source_rows: list[SourceManifestInventoryRecord],
    gates: list[ReadinessGateRecord],
) -> dict[str, str]:
    claim_table = load_default_claim_synthesis_store().paper_table()
    return {
        "paper/README.md": """# TargetIdeator reproducible methods and negative-results artifact

This bundle freezes the executable engineering evidence produced through P6.5. It is suitable for artifact inspection, methods reporting, and transparent negative-result reporting. It is not evidence that TargetIdeator improves target discovery, calibration, clinical success, or expert decision quality.

## Bundle map

- `POSITIONING.md`: allowed and forbidden paper positioning;
- `METHODS.md`: frozen pipeline and evaluation methods;
- `RESULTS.md`: engineering results, including the P6.4 negative result;
- `LIMITATIONS.md`: identification, label, and generalization blockers;
- `REPRODUCE.md`: one-command verifiers and rebuild instructions;
- `tables/`: source inventory, claim dispositions, and readiness gates.

Artifact release readiness and scientific submission readiness are separate. The former passes; the latter remains blocked.
""",
        "paper/POSITIONING.md": """# Positioning

## Supported positioning

TargetIdeator is a reproducible, provenance-aware development system for structuring target hypotheses, tracing temporal evidence, exposing falsification requirements, and preserving negative evaluation results.

The current contribution is an auditable methods/artifact package with engineering controls and explicit no-go boundaries.

## Forbidden positioning

- validated or state-of-the-art drug-target discovery;
- improved target ranking over gene-only or established baselines;
- calibrated probability of clinical success;
- validated scientific correctness of the falsifier;
- human-validated literature claim extraction;
- demonstrated clinical, investment, or experimental decision utility.

Packaging completion must not be described as scientific claim validation.
""",
        "paper/METHODS.md": """# Methods summary

The system uses versioned evidence releases, explicit temporal cutoffs, record-level provenance, span-grounded provisional literature claims, dependency-family correction, structured hypothesis tuples, fixed-taxonomy falsification, constrained revision, and abstaining multi-head development contracts.

Evaluation proceeds through a preregistered claim registry and frozen manifests. P6.1 measures structural sensitivity under deterministic graph perturbations. P6.2 tests dependency-aware count invariance under duplicate-cohort injection. P6.3 compares proposer-only output with the fixed falsify/revise path using an internal qualification proxy. P6.4 masks only explicit counterevidence roles while retaining source documents. P6.5 maps every result back to C1-C6 without promoting gates.

No P6 experiment reveals future target outcomes, refits an outcome model, computes a clinical metric, or substitutes model-assisted labels for final human gold.
""",
        "paper/RESULTS.md": """# Results

Twenty-two source manifests are checksum-bound. P6.1 completed 16 structural perturbation scenarios. P6.2 kept dependency-corrected independent counts invariant while family-blind counts inflated by as much as 20.93%. P6.3 reduced the deterministic critic-exposed qualification proxy from 16 to 0, but three possible false-rejection paths remain unlabeled and no rate is reported.

P6.4 is a decision-level negative result: explicit counter-role masking changed 1/20 local critic verdicts, but 0/5 combined verdicts and 0/5 block decisions. P6.5 therefore records four completed engineering controls, zero claim-status changes, zero scientifically decisive metrics, and zero scientifically supported claims.

The reproducible artifact gate passes. The scientific submission gate does not.
""",
        "paper/LIMITATIONS.md": """# Limitations

The literature benchmark is provisional and lacks completed independent adjudication. The five hypothesis records are restricted to a four-target seed panel and cannot establish generalization. Mapping availability is strongly selected, so the mapped subset cannot support an unbiased target-level benchmark. Registry termination reasons do not identify target efficacy or causality. Ordinal readiness outputs are not calibrated probabilities.

P6.1-P6.4 are deterministic engineering controls. Their structural stability, count invariance, proxy reduction, or local sensitivity cannot establish scientific correctness. In particular, P6.4 did not detect decision-level benefit from explicit counter roles in this slice.

C1 and C4 remain blocked by identification, C2 by missing gold and comparative decision metrics, C3 by missing independent correctness and false-rejection labels, and C5 by the absence of a credible assay outcome model.
""",
        "paper/REPRODUCE.md": """# Reproduce

From the repository root:

```bash
uv sync --extra dev
uv run targetideator verify-p6-evaluation
uv run targetideator verify-p6-robustness
uv run targetideator verify-p6-cohort-stress
uv run targetideator verify-p6-paired-control
uv run targetideator verify-p6-counterevidence-ablation
uv run targetideator verify-p6-claim-synthesis
uv run targetideator verify-p6-paper-bundle
uv run pytest
```

Rebuild this artifact:

```bash
uv run targetideator build-p6-paper-bundle --output-dir outputs/p6-6-paper-bundle-rebuild
```

Compare the rebuilt manifest and file inventory with the frozen artifacts before interpreting any result.
""",
        "paper/tables/table_1_source_manifest_inventory.md": _render_source_table(source_rows),
        "paper/tables/table_2_claim_disposition.md": claim_table,
        "paper/tables/table_3_readiness_gates.md": _render_gate_table(gates),
    }


def _write_paper_files(output_dir: Path, content: dict[str, str]) -> list[PaperFileInventoryRecord]:
    rows = []
    for relative_path in sorted(content):
        path = output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content[relative_path], encoding="utf-8")
        rows.append(
            PaperFileInventoryRecord(
                id=stable_id("paper-file", relative_path),
                relative_path=relative_path,
                role=PAPER_FILES[relative_path],
                sha256=file_sha256(path),
                byte_count=path.stat().st_size,
            )
        )
    return rows


def _quality(
    sources: list[SourceManifestInventoryRecord],
    gates: list[ReadinessGateRecord],
    paper_files: list[PaperFileInventoryRecord],
) -> PaperBundleQuality:
    claim_table = load_default_claim_synthesis_store().paper_table()
    artifact_passed = sum(
        row.gate_scope == "artifact_release" and row.status == ReadinessGateStatus.PASSED
        for row in gates
    )
    scientific_blocked = sum(
        row.gate_scope == "scientific_submission" and row.status == ReadinessGateStatus.BLOCKED
        for row in gates
    )
    return PaperBundleQuality(
        source_manifest_count=len(sources),
        paper_file_count=len(paper_files),
        readiness_gate_count=len(gates),
        passed_artifact_gate_count=artifact_passed,
        blocked_scientific_gate_count=scientific_blocked,
        artifact_release_ready=(
            len(sources) == 22
            and len(paper_files) == 9
            and artifact_passed == 3
            and all(len(row.manifest_sha256) == 64 for row in sources)
        ),
        negative_result_preserved=(
            "decision-level negative result" in claim_table
            and any(
                row.gate_id == "negative_result_preservation"
                and row.status == ReadinessGateStatus.PASSED
                for row in gates
            )
        ),
        engineering_gate_passed=(
            artifact_passed == 3
            and scientific_blocked == 3
            and len(sources) == 22
            and len(paper_files) == 9
        ),
        blocking_limitations=[
            "Artifact release readiness does not imply scientific submission readiness.",
            "C1-C4 remain blocked by identification, final gold, or independent decision metrics.",
            "The paper bundle must be positioned as methods/artifact and negative-results work.",
            "No future target outcome, model refit, clinical metric, or scientific gate promotion occurs.",
        ],
    )


def write_paper_bundle_artifacts(
    output_dir: Path,
) -> tuple[PaperBundleSnapshot, PaperBundleManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = _source_manifest_inventory()
    gates = _readiness_gates()
    paper_files = _write_paper_files(output_dir, _paper_content(sources, gates))
    quality = _quality(sources, gates, paper_files)

    source_path = output_dir / "p6_6_source_manifest_inventory.jsonl.gz"
    gate_path = output_dir / "p6_6_readiness_gates.jsonl.gz"
    paper_file_path = output_dir / "p6_6_paper_file_inventory.jsonl.gz"
    _write_jsonl_gzip(source_path, [row.model_dump(mode="json") for row in sources])
    _write_jsonl_gzip(gate_path, [row.model_dump(mode="json") for row in gates])
    _write_jsonl_gzip(
        paper_file_path, [row.model_dump(mode="json") for row in paper_files]
    )

    snapshot = PaperBundleSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        source_manifest_inventory_path=source_path.name,
        source_manifest_inventory_sha256=file_sha256(source_path),
        readiness_gate_path=gate_path.name,
        readiness_gate_sha256=file_sha256(gate_path),
        paper_file_inventory_path=paper_file_path.name,
        paper_file_inventory_sha256=file_sha256(paper_file_path),
        quality=quality,
        warning=(
            "REPRODUCIBLE METHODS/ARTIFACT BUNDLE, NOT A VALIDATED TARGET-DISCOVERY "
            "PAPER. Artifact readiness and scientific readiness are separate gates."
        ),
    )
    snapshot_path = output_dir / "p6_6_paper_bundle_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = PaperBundleManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        source_manifest_inventory_path=source_path.name,
        source_manifest_inventory_sha256=file_sha256(source_path),
        readiness_gate_path=gate_path.name,
        readiness_gate_sha256=file_sha256(gate_path),
        paper_file_inventory_path=paper_file_path.name,
        paper_file_inventory_sha256=file_sha256(paper_file_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "p6_6_paper_bundle_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class PaperBundleStore:
    def __init__(
        self, snapshot: PaperBundleSnapshot, manifest: PaperBundleManifest, root: Path
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "PaperBundleStore":
        return cls(
            PaperBundleSnapshot.model_validate(_load_json(snapshot_path)),
            PaperBundleManifest.model_validate(_load_json(manifest_path)),
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

    def sources(self) -> list[dict]:
        return self._rows(self.manifest.source_manifest_inventory_path, 22)

    def gates(self) -> list[dict]:
        return self._rows(self.manifest.readiness_gate_path, 6)

    def paper_files(self) -> list[dict]:
        return self._rows(self.manifest.paper_file_inventory_path, 9)

    def paper_file(self, relative_path: str) -> str | None:
        allowed = {row["relative_path"] for row in self.paper_files()}
        if relative_path not in allowed:
            return None
        return (self.root / relative_path).read_text(encoding="utf-8")

    def quality_report(self) -> dict:
        paper_files_match = all(
            file_sha256(self.root / row["relative_path"]) == row["sha256"]
            for row in self.paper_files()
        )
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                paper_files_match
                and file_sha256(self.root / self.manifest.source_manifest_inventory_path)
                == self.manifest.source_manifest_inventory_sha256
                and file_sha256(self.root / self.manifest.readiness_gate_path)
                == self.manifest.readiness_gate_sha256
                and file_sha256(self.root / self.manifest.paper_file_inventory_path)
                == self.manifest.paper_file_inventory_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums()
            == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_paper_bundle_store() -> PaperBundleStore:
    return PaperBundleStore.load(
        default_paper_bundle_snapshot_path(), default_paper_bundle_manifest_path()
    )
