"""Synthesize P6.0-P6.4 into a frozen paper-claim disposition table."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.evaluation.cohort_stress_store import load_default_cohort_stress_store
from targetideator.evaluation.counterevidence_ablation_store import (
    load_default_counterevidence_ablation_store,
)
from targetideator.evaluation.models import ClaimEvaluationStatus
from targetideator.evaluation.paired_control_store import load_default_paired_control_store
from targetideator.evaluation.robustness_store import load_default_robustness_store
from targetideator.evaluation.store import load_default_evaluation_store
from targetideator.evaluation.synthesis_models import (
    ClaimDispositionRecord,
    ClaimSynthesisManifest,
    ClaimSynthesisQuality,
    ClaimSynthesisSnapshot,
    ExperimentDispositionRecord,
    ExperimentResultClass,
)
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip

BUILDER_VERSION = "p6.5-frozen-claim-disposition-synthesis-v1"
SNAPSHOT_ID = "ti:claim-synthesis:p6-frozen-disposition-v1"
CREATED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)

SOURCE_MANIFESTS = {
    "P6.0": "p6_0_evaluation_manifest.json",
    "P6.1": "p6_1_robustness_manifest.json",
    "P6.2": "p6_2_cohort_stress_manifest.json",
    "P6.3": "p6_3_paired_control_manifest.json",
    "P6.4": "p6_4_counterevidence_ablation_manifest.json",
}


def _fixture_path(filename: str) -> Path:
    return fixture_path(filename)


def default_claim_synthesis_snapshot_path() -> Path:
    return _fixture_path("p6_5_claim_synthesis_snapshot.json")


def default_claim_synthesis_manifest_path() -> Path:
    return _fixture_path("p6_5_claim_synthesis_manifest.json")


def _source_checksums() -> dict[str, str]:
    return {
        filename: file_sha256(_fixture_path(filename))
        for filename in SOURCE_MANIFESTS.values()
    }


def _source_snapshot_id(experiment_id: str) -> str:
    manifest = _load_json(_fixture_path(SOURCE_MANIFESTS[experiment_id]))
    return str(manifest["snapshot_id"])


def _experiment_dispositions() -> list[ExperimentDispositionRecord]:
    p60 = load_default_evaluation_store().quality_report()
    p61 = load_default_robustness_store().quality_report()
    p62 = load_default_cohort_stress_store().quality_report()
    p63 = load_default_paired_control_store().quality_report()
    p64 = load_default_counterevidence_ablation_store().quality_report()

    if any(
        report["scientific_validation_gate_passed"]
        for report in (p60, p61, p62, p63, p64)
    ):
        raise ValueError("P6 source unexpectedly promotes a scientific gate")
    if any(not report["engineering_gate_passed"] for report in (p60, p61, p62, p63, p64)):
        raise ValueError("P6 source engineering gate is not reproducibly satisfied")

    rows = [
        {
            "experiment_id": "P6.0",
            "primary_claim_codes": ["C1", "C2", "C3", "C4", "C5", "C6"],
            "result_class": ExperimentResultClass.AUDIT_BOUNDARY,
            "observed_finding": (
                "Six claims were preregistered against 16 frozen manifests; zero claims "
                "were scientifically supported and future target outcomes remained withheld."
            ),
            "intended_scope": "Claim registry, artifact checksum inventory, and no-reveal replay boundary.",
        },
        {
            "experiment_id": "P6.1",
            "primary_claim_codes": ["C2", "C6"],
            "result_class": ExperimentResultClass.STRUCTURAL_SENSITIVITY,
            "observed_finding": (
                f"Sixteen fixed perturbation scenarios reached a minimum graph-signature "
                f"similarity of {p61['minimum_graph_signature_similarity']:.4f}; this measures "
                "structure and error propagation only."
            ),
            "intended_scope": "Deterministic claim-graph structural robustness without outcome recomputation.",
        },
        {
            "experiment_id": "P6.2",
            "primary_claim_codes": ["C2", "C6"],
            "result_class": ExperimentResultClass.ENGINEERING_INVARIANCE,
            "observed_finding": (
                f"Dependency-corrected counts remained invariant while family-blind counts "
                f"inflated by up to {p62['maximum_family_blind_inflation_fraction']:.2%}; "
                "the stripped-lineage negative control failed as intended."
            ),
            "intended_scope": "Duplicate-cohort count invariance when evidence-family lineage is present.",
        },
        {
            "experiment_id": "P6.3",
            "primary_claim_codes": ["C3", "C6"],
            "result_class": ExperimentResultClass.UNVALIDATED_PROXY_REDUCTION,
            "observed_finding": (
                f"The critic-exposed unqualified proxy fell from "
                f"{p63['proposer_only_unqualified_proxy_count']} to "
                f"{p63['full_path_unqualified_proxy_count']}, but three false-rejection "
                "candidates lack adjudicated labels and no rate was computed."
            ),
            "intended_scope": "Paired pipeline control over frozen model-silver hypotheses.",
        },
        {
            "experiment_id": "P6.4",
            "primary_claim_codes": ["C3", "C6"],
            "result_class": ExperimentResultClass.DECISION_LEVEL_NEGATIVE,
            "observed_finding": (
                f"Counter-role masking changed {p64['cell_verdict_changed_count']}/20 local "
                f"verdicts but {p64['combined_verdict_changed_count']}/5 combined verdicts "
                "and 0/5 block decisions; decision-level value was not supported."
            ),
            "intended_scope": "Incremental effect of explicit counterevidence roles, with source documents retained.",
        },
    ]

    result = []
    for row in rows:
        experiment_id = row["experiment_id"]
        filename = SOURCE_MANIFESTS[experiment_id]
        result.append(
            ExperimentDispositionRecord(
                id=stable_id("experiment-disposition", experiment_id),
                source_snapshot_id=_source_snapshot_id(experiment_id),
                source_manifest_filename=filename,
                source_manifest_sha256=file_sha256(_fixture_path(filename)),
                **row,
            )
        )
    return result


def _claim_dispositions() -> list[ClaimDispositionRecord]:
    source_claims = {
        row["claim_code"]: row for row in load_default_evaluation_store().claims()
    }
    synthesis = {
        "C1": {
            "experiments": ["P6.0"],
            "controls": 0,
            "finding": "Tuple-versus-gene comparison remains unidentified; P6.1-P6.4 do not test C1.",
            "blockers": ["No exchangeable target-level temporal benchmark; the P5.9 selection no-go remains active."],
        },
        "C2": {
            "experiments": ["P6.0", "P6.1", "P6.2"],
            "controls": 2,
            "finding": "Structural perturbation and dependency-count controls are reproducible, but no faithfulness or calibration benefit is established.",
            "blockers": ["No final human gold, flat-retrieval comparison, or decision-linked calibration metric."],
        },
        "C3": {
            "experiments": ["P6.0", "P6.3", "P6.4"],
            "controls": 2,
            "finding": "The fixed path removes a deterministic qualification proxy, while counter-role masking shows no decision-level effect in this slice.",
            "blockers": ["No independent correctness labels, counterevidence-recall benchmark, or valid-hypothesis false-rejection rate."],
        },
        "C4": {
            "experiments": ["P6.0"],
            "controls": 0,
            "finding": "No calibrated multi-head comparison is legal because hypothesis-linked outcome identification remains invalid.",
            "blockers": ["No valid hypothesis-linked outcome labels; ordinal readiness values remain non-probabilistic."],
        },
        "C5": {
            "experiments": ["P6.0"],
            "controls": 0,
            "finding": "EVI remains deferred; no experiment in P6.1-P6.4 estimates an assay outcome model.",
            "blockers": ["The frozen artifacts cannot estimate p(y|H,a,E)."],
        },
        "C6": {
            "experiments": ["P6.0", "P6.1", "P6.2", "P6.3", "P6.4"],
            "controls": 4,
            "finding": "All P6 controls are checksum-bound and preserve negative/null results, strengthening reproducibility but not target-level validity.",
            "blockers": ["Leakage-aware engineering controls expose missing identification and labels but cannot supply them."],
        },
    }
    result = []
    for claim_code in sorted(source_claims):
        source = source_claims[claim_code]
        spec = synthesis[claim_code]
        status = ClaimEvaluationStatus(source["current_status"])
        result.append(
            ClaimDispositionRecord(
                id=stable_id("claim-disposition", claim_code),
                claim_code=claim_code,
                title=source["title"],
                baseline_status=status,
                synthesized_status=status,
                supporting_experiment_ids=spec["experiments"],
                completed_engineering_control_count=spec["controls"],
                synthesized_finding=spec["finding"],
                remaining_blockers=spec["blockers"],
                forbidden_conclusions=source["forbidden_conclusions"],
            )
        )
    return result


def _quality(
    claims: list[ClaimDispositionRecord], experiments: list[ExperimentDispositionRecord]
) -> ClaimSynthesisQuality:
    statuses = Counter(row.synthesized_status for row in claims)
    quality = ClaimSynthesisQuality(
        engineering_evidence_only_claim_count=statuses[
            ClaimEvaluationStatus.ENGINEERING_EVIDENCE_ONLY
        ],
        blocked_claim_count=(
            statuses[ClaimEvaluationStatus.BLOCKED_BY_IDENTIFICATION]
            + statuses[ClaimEvaluationStatus.BLOCKED_BY_MISSING_GOLD]
        ),
        deferred_claim_count=statuses[ClaimEvaluationStatus.DEFERRED_OUT_OF_SCOPE],
        completed_engineering_control_count=len(experiments) - 1,
        decision_level_negative_result_count=sum(
            row.result_class == ExperimentResultClass.DECISION_LEVEL_NEGATIVE
            for row in experiments
        ),
        engineering_gate_passed=(
            len(claims) == 6
            and len(experiments) == 5
            and all(not row.status_changed for row in claims)
            and all(not row.scientifically_supported for row in claims)
            and all(not row.scientific_validation_gate_passed for row in experiments)
            and all(row.result_reported_without_gate_promotion for row in experiments)
        ),
        blocking_limitations=[
            "P6.1-P6.4 provide engineering controls, not scientifically decisive claim metrics.",
            "C1 and C4 remain blocked by target-level identification and mapping selection.",
            "C2 remains blocked by missing final gold and a decision-linked flat-retrieval comparison.",
            "C3 lacks independent correctness and false-rejection labels; P6.4 is a decision-level negative result.",
            "C5 remains deferred because no assay outcome model can be estimated.",
        ],
    )
    return quality


def render_paper_table(
    claims: list[ClaimDispositionRecord], experiments: list[ExperimentDispositionRecord]
) -> str:
    lines = [
        "# TargetIdeator P6 frozen claim-disposition table",
        "",
        "> Engineering synthesis only. No scientific gate is promoted.",
        "",
        "## Claim disposition",
        "",
        "| Claim | Synthesized status | Controls | Finding |",
        "|---|---|---:|---|",
    ]
    lines.extend(
        f"| {row.claim_code} {row.title} | `{row.synthesized_status.value}` | "
        f"{row.completed_engineering_control_count} | {row.synthesized_finding} |"
        for row in claims
    )
    lines.extend(
        [
            "",
            "## Experiment disposition",
            "",
            "| Experiment | Result class | Scientific gate | Frozen finding |",
            "|---|---|---|---|",
        ]
    )
    lines.extend(
        f"| {row.experiment_id} | `{row.result_class.value}` | false | {row.observed_finding} |"
        for row in experiments
    )
    lines.extend(
        [
            "",
            "## Frozen conclusion",
            "",
            "P6.1-P6.4 close four engineering controls, but no paper claim changes status. "
            "P6.4 is retained as a decision-level negative result; C1/C4 remain no-go.",
            "",
        ]
    )
    return "\n".join(lines)


def write_claim_synthesis_artifacts(
    output_dir: Path,
) -> tuple[ClaimSynthesisSnapshot, ClaimSynthesisManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    claims = _claim_dispositions()
    experiments = _experiment_dispositions()
    quality = _quality(claims, experiments)
    claim_path = output_dir / "p6_5_claim_dispositions.jsonl.gz"
    experiment_path = output_dir / "p6_5_experiment_dispositions.jsonl.gz"
    paper_table_path = output_dir / "p6_5_claim_disposition_table.md"
    _write_jsonl_gzip(claim_path, [row.model_dump(mode="json") for row in claims])
    _write_jsonl_gzip(
        experiment_path, [row.model_dump(mode="json") for row in experiments]
    )
    paper_table_path.write_text(
        render_paper_table(claims, experiments), encoding="utf-8"
    )
    snapshot = ClaimSynthesisSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        claim_disposition_path=claim_path.name,
        claim_disposition_sha256=file_sha256(claim_path),
        experiment_disposition_path=experiment_path.name,
        experiment_disposition_sha256=file_sha256(experiment_path),
        paper_table_path=paper_table_path.name,
        paper_table_sha256=file_sha256(paper_table_path),
        quality=quality,
        warning=(
            "PAPER-TABLE SYNTHESIS, NOT SCIENTIFIC VALIDATION. Frozen engineering controls "
            "are dispositioned without changing any claim gate."
        ),
    )
    snapshot_path = output_dir / "p6_5_claim_synthesis_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = ClaimSynthesisManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        claim_disposition_path=claim_path.name,
        claim_disposition_sha256=file_sha256(claim_path),
        experiment_disposition_path=experiment_path.name,
        experiment_disposition_sha256=file_sha256(experiment_path),
        paper_table_path=paper_table_path.name,
        paper_table_sha256=file_sha256(paper_table_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "p6_5_claim_synthesis_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class ClaimSynthesisStore:
    def __init__(
        self,
        snapshot: ClaimSynthesisSnapshot,
        manifest: ClaimSynthesisManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "ClaimSynthesisStore":
        return cls(
            ClaimSynthesisSnapshot.model_validate(_load_json(snapshot_path)),
            ClaimSynthesisManifest.model_validate(_load_json(manifest_path)),
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

    def claims(self) -> list[dict]:
        return self._rows(self.manifest.claim_disposition_path, 6)

    def experiments(self) -> list[dict]:
        return self._rows(self.manifest.experiment_disposition_path, 5)

    def paper_table(self) -> str:
        return (self.root / self.manifest.paper_table_path).read_text(encoding="utf-8")

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.claim_disposition_path)
                == self.manifest.claim_disposition_sha256
                and file_sha256(self.root / self.manifest.experiment_disposition_path)
                == self.manifest.experiment_disposition_sha256
                and file_sha256(self.root / self.manifest.paper_table_path)
                == self.manifest.paper_table_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums()
            == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_claim_synthesis_store() -> ClaimSynthesisStore:
    return ClaimSynthesisStore.load(
        default_claim_synthesis_snapshot_path(),
        default_claim_synthesis_manifest_path(),
    )
