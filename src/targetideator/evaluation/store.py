"""Build a reproducible P6 claim registry, artifact inventory, and pipeline replay."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.evaluation.models import (
    ArtifactInventoryRecord,
    ClaimEvaluationStatus,
    DecisionReplayRecord,
    EvaluationManifest,
    EvaluationQuality,
    EvaluationSnapshot,
    PaperClaimRecord,
)
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.store import load_default_falsification_store
from targetideator.ids import stable_id
from targetideator.ideation.store import load_default_ideation_store
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.revision.store import load_default_revision_store
from targetideator.scoring.store import load_default_decision_store

BUILDER_VERSION = "p6.0-reproducible-claim-audit-v1"
SNAPSHOT_ID = "ti:evaluation-run:paper-claim-audit-v1"
CREATED_AT = datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)

SOURCE_MANIFESTS = (
    ("P1.2", "opentargets_25_03_25_09_historical_manifest.json", ["C6"]),
    ("P1.3", "clinical_history_manifest.json", ["C6"]),
    ("P2.1", "claim_graph_manifest.json", ["C2", "C3", "C6"]),
    ("P2.2", "literature_manifest.json", ["C2", "C3"]),
    ("P3", "p3_ideation_manifest.json", ["C1", "C3"]),
    ("P4", "p4_falsification_manifest.json", ["C3"]),
    ("P4.1", "p4_revision_manifest.json", ["C3"]),
    ("P5", "p5_decision_manifest.json", ["C1", "C4"]),
    ("P5.2", "p5_2_broad_outcome_manifest.json", ["C4", "C6"]),
    ("P5.3", "p5_3_identity_manifest.json", ["C1", "C4", "C6"]),
    ("P5.4", "p5_4_mapping_audit_manifest.json", ["C4", "C6"]),
    ("P5.5", "p5_5_drug_identity_manifest.json", ["C4", "C6"]),
    ("P5.6", "p5_6_assertion_history_manifest.json", ["C4", "C6"]),
    ("P5.7", "p5_7_independent_assertion_manifest.json", ["C4", "C6"]),
    ("P5.8", "p5_8_support_audit_manifest.json", ["C4", "C6"]),
    ("P5.9", "p5_9_selection_audit_manifest.json", ["C1", "C4", "C6"]),
)


def default_evaluation_snapshot_path() -> Path:
    return fixture_path("p6_0_evaluation_snapshot.json")


def default_evaluation_manifest_path() -> Path:
    return fixture_path("p6_0_evaluation_manifest.json")


def _fixture_path(filename: str) -> Path:
    return fixture_path(filename)


def _paper_claims() -> list[PaperClaimRecord]:
    rows = [
        {
            "claim_code": "C1",
            "title": "Context-specific therapeutic hypothesis search",
            "headline_for_first_paper": True,
            "predeclared_claim": "A full target-direction-context-modality tuple improves decision-aligned prediction over gene-only ranking.",
            "falsification_condition": "C1 fails if a gene-only baseline matches the tuple model on direction-aware temporal metrics under the same abstention policy.",
            "required_metrics": ["PR-AUC", "Brier", "ECE", "risk-coverage", "direction-aware recall@k"],
            "bound_stage_ids": ["P3", "P5", "P5.3", "P5.9"],
            "current_status": "blocked_by_identification",
            "current_evidence": ["Five structured tuples are reproducible, but none is scientifically rankable."],
            "blockers": ["No exchangeable target-level temporal benchmark; mapping selection no-go is active."],
            "forbidden_conclusions": ["Full tuples outperform gene-only ranking.", "Any generated target is clinically superior."],
        },
        {
            "claim_code": "C2",
            "title": "Temporal dependency-aware epistemic claim graph",
            "headline_for_first_paper": True,
            "predeclared_claim": "Temporal claim structure and dependency correction improve faithfulness and calibrated decisions over flat retrieval.",
            "falsification_condition": "C2 fails if oracle/noise ablations show no calibration or contradiction-recall benefit over flat RAG.",
            "required_metrics": ["citation entailment", "citation completeness", "contradiction recall", "noise curves", "Brier", "ECE"],
            "bound_stage_ids": ["P2.1", "P2.2", "P3"],
            "current_status": "blocked_by_missing_gold",
            "current_evidence": ["Versioned structured and span-grounded claim artifacts exist with deterministic lineage."],
            "blockers": ["No final human gold and no oracle/drop/flip/context-corruption experiment."],
            "forbidden_conclusions": ["Claim extraction is human-validated.", "Dependency correction improves calibration."],
        },
        {
            "claim_code": "C3",
            "title": "Generate-falsify-adjudicate",
            "headline_for_first_paper": True,
            "predeclared_claim": "An independent fixed-taxonomy falsifier reduces unsupported high-confidence hypotheses without destroying useful recall.",
            "falsification_condition": "C3 fails if unsupported-claim reduction is absent or is explained only by indiscriminate abstention and recall loss.",
            "required_metrics": ["unsupported-claim rate", "fatal-assumption quality", "counterevidence recall", "valid-hypothesis false rejection"],
            "bound_stage_ids": ["P3", "P4", "P4.1"],
            "current_status": "engineering_evidence_only",
            "current_evidence": ["All five hypotheses pass through four fixed critics and conservative structured revision."],
            "blockers": ["No validated falsification benchmark or paired proposer-only comparison."],
            "forbidden_conclusions": ["The falsifier improves scientific correctness.", "More abstention proves better reliability."],
        },
        {
            "claim_code": "C4",
            "title": "Calibrated multi-head decision",
            "headline_for_first_paper": True,
            "predeclared_claim": "Separate calibrated heads and abstention improve decision quality over a single aggregate score.",
            "falsification_condition": "C4 fails if validation-only calibration and selective prediction do not beat matched simple baselines.",
            "required_metrics": ["Brier", "ECE", "PR-AUC", "AURC", "selective accuracy", "Pareto coverage"],
            "bound_stage_ids": ["P5", "P5.2", "P5.3", "P5.9"],
            "current_status": "blocked_by_identification",
            "current_evidence": ["A five-head abstention contract exists; probabilities and calibration are intentionally withheld."],
            "blockers": ["No valid hypothesis-linked outcome labels; target-validation no-go remains active."],
            "forbidden_conclusions": ["Ordinal readiness values are probabilities.", "The decision engine is calibrated."],
        },
        {
            "claim_code": "C5",
            "title": "Expected value of information planning",
            "headline_for_first_paper": False,
            "predeclared_claim": "A restricted EVI policy reduces experiments needed for the same go/no-go accuracy.",
            "falsification_condition": "C5 fails if EVI does not beat fixed-template, uncertainty, and random policies under a matched budget.",
            "required_metrics": ["go/no-go accuracy per budget", "regret", "assay cost sensitivity"],
            "bound_stage_ids": ["P5"],
            "current_status": "deferred_out_of_scope",
            "current_evidence": ["No credible historical assay outcome model is available."],
            "blockers": ["p(y|H,a,E) cannot be estimated from the frozen artifacts."],
            "forbidden_conclusions": ["LLM-reported uncertainty is EVI.", "An EVI policy has been validated."],
        },
        {
            "claim_code": "C6",
            "title": "Decision-aligned leakage-aware evaluation",
            "headline_for_first_paper": True,
            "predeclared_claim": "Temporal, provenance-aware evaluation gives a more faithful test than random split or narrative rubric.",
            "falsification_condition": "C6 fails if leakage-aware controls do not materially change conclusions or cannot be reproduced from frozen releases.",
            "required_metrics": ["cutoff leakage", "novel-NCT sensitivity", "mapping coverage", "selection diagnostics", "checksum reproducibility"],
            "bound_stage_ids": ["P1.2", "P1.3", "P5.2", "P5.3", "P5.9"],
            "current_status": "engineering_evidence_only",
            "current_evidence": ["Release replay, temporal outcomes, provenance, mapping audit, and selection no-go are reproducible."],
            "blockers": ["The protocol exposes that target-level identification is not currently valid; it does not supply missing labels."],
            "forbidden_conclusions": ["A negative target benchmark has been completed.", "Temporal registry outcomes identify target causality."],
        },
    ]
    return [
        PaperClaimRecord(id=stable_id("paper-claim", row["claim_code"]), **row)
        for row in rows
    ]


def _manifest_snapshot_id(manifest: dict, stage_id: str) -> str:
    for key in ("snapshot_id", "portfolio_id"):
        if manifest.get(key):
            return str(manifest[key])
    return f"manifest-only:{stage_id}"


def _artifact_inventory() -> list[ArtifactInventoryRecord]:
    result = []
    for stage_id, filename, claim_codes in SOURCE_MANIFESTS:
        path = _fixture_path(filename)
        manifest = _load_json(path)
        scientific_flags = [
            value
            for key, value in manifest.items()
            if "scientific_validation_gate_passed" in key
        ]
        if any(scientific_flags):
            raise ValueError(f"{stage_id} unexpectedly declares a scientific gate")
        result.append(
            ArtifactInventoryRecord(
                id=stable_id("evaluation-artifact", stage_id),
                stage_id=stage_id,
                manifest_filename=filename,
                manifest_sha256=file_sha256(path),
                source_snapshot_id=_manifest_snapshot_id(manifest, stage_id),
                bound_claim_codes=claim_codes,
            )
        )
    return result


def _decision_replay() -> list[DecisionReplayRecord]:
    portfolio = load_default_ideation_store().portfolio
    falsification = load_default_falsification_store().snapshot
    revision = load_default_revision_store().snapshot
    decision = load_default_decision_store().snapshot
    falsification_by_id = {row.hypothesis_id: row for row in falsification.results}
    revision_by_id = {row.source_hypothesis_id: row for row in revision.candidates}
    decision_by_id = {row.hypothesis_id: row for row in decision.decisions}
    rows = []
    for hypothesis in sorted(portfolio.hypotheses, key=lambda row: row.id):
        p4 = falsification_by_id[hypothesis.id]
        p4_1 = revision_by_id[hypothesis.id]
        p5 = decision_by_id[hypothesis.id]
        rows.append(
            DecisionReplayRecord(
                id=stable_id("decision-replay", hypothesis.id),
                hypothesis_id=hypothesis.id,
                as_of_date=portfolio.as_of_date.isoformat(),
                target_id=hypothesis.target.identifier,
                target_label=hypothesis.target.label,
                disease_id=(
                    f"{hypothesis.disease.namespace}:{hypothesis.disease.identifier}"
                    if not hypothesis.disease.identifier.startswith(
                        f"{hypothesis.disease.namespace}:"
                    )
                    else hypothesis.disease.identifier
                ),
                population=hypothesis.population,
                cell_state=hypothesis.cell_state,
                proposed_direction=hypothesis.proposed_direction.value,
                proposed_modality=hypothesis.proposed_modality.value,
                supporting_claim_count=len(hypothesis.supporting_claim_ids),
                counterevidence_claim_count=len(hypothesis.counterevidence_claim_ids),
                p3_verification_status=hypothesis.verification_status,
                p4_combined_verdict=p4.combined_verdict.value,
                p4_critic_verdicts={
                    assessment.critic_type.value: assessment.verdict.value
                    for assessment in p4.assessments
                },
                p4_evidence_gap_count=sum(
                    len(assessment.evidence_gaps) for assessment in p4.assessments
                ),
                p4_1_revision_status=p4_1.revision_status.value,
                p4_1_patch_count=len(p4_1.patches),
                p4_1_unresolved_critic_types=[
                    item.value for item in p4_1.unresolved_critic_types
                ],
                p5_decision_status=p5.decision_status.value,
                p5_head_scores={
                    head.head_name.value: head.score for head in p5.heads
                },
                p5_missing_required_heads=[
                    item.value for item in p5.missing_required_heads
                ],
                p5_pareto_status=p5.pareto_status.value,
            )
        )
    return rows


def _quality(
    claims: list[PaperClaimRecord],
    inventory: list[ArtifactInventoryRecord],
    replay: list[DecisionReplayRecord],
) -> EvaluationQuality:
    statuses = Counter(row.current_status for row in claims)
    return EvaluationQuality(
        headline_claim_count=sum(row.headline_for_first_paper for row in claims),
        engineering_evidence_only_claim_count=statuses[
            ClaimEvaluationStatus.ENGINEERING_EVIDENCE_ONLY
        ],
        blocked_claim_count=(
            statuses[ClaimEvaluationStatus.BLOCKED_BY_IDENTIFICATION]
            + statuses[ClaimEvaluationStatus.BLOCKED_BY_MISSING_GOLD]
        ),
        deferred_claim_count=statuses[ClaimEvaluationStatus.DEFERRED_OUT_OF_SCOPE],
        artifact_inventory_count=len(inventory),
        artifact_checksum_coverage=(
            sum(len(row.manifest_sha256) == 64 for row in inventory) / len(inventory)
        ),
        replay_hypothesis_count=len(replay),
        engineering_gate_passed=(
            len(claims) == 6
            and len(inventory) == len(SOURCE_MANIFESTS)
            and len(replay) == 5
            and all(not row.scientifically_supported for row in claims)
            and all(not row.scientific_comparison_allowed for row in replay)
        ),
        blocking_limitations=[
            "No paper headline claim is scientifically supported by the current development artifacts.",
            "C1 and C4 remain blocked by target-level identification and selection bias.",
            "C2 and C3 require final gold and predeclared comparative evaluations.",
            "C5 remains deferred because an assay outcome model cannot be estimated.",
            "The replay ends in abstention or upstream blocking and does not reveal future target outcomes.",
        ],
    )


def render_evaluation_report(snapshot: EvaluationSnapshot, claims: list[PaperClaimRecord]) -> str:
    q = snapshot.quality
    lines = [
        "# TargetIdeator P6.0 reproducible paper-claim audit",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Paper claims: {q.paper_claim_count}",
        f"- Scientifically supported claims: {q.scientifically_supported_claim_count}",
        f"- Frozen upstream manifests: {q.artifact_inventory_count}",
        f"- Replayed hypotheses: {q.replay_hypothesis_count}",
        "",
        "## Claim status",
        "",
    ]
    lines.extend(
        f"- **{row.claim_code} {row.title}**: `{row.current_status.value}`"
        for row in claims
    )
    lines.extend(["", "## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in q.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums() -> dict[str, str]:
    return {
        filename: file_sha256(_fixture_path(filename))
        for _, filename, _ in SOURCE_MANIFESTS
    }


def write_evaluation_artifacts(output_dir: Path) -> tuple[EvaluationSnapshot, EvaluationManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    claims = _paper_claims()
    inventory = _artifact_inventory()
    replay = _decision_replay()
    claim_path = output_dir / "p6_0_paper_claim_registry.jsonl.gz"
    inventory_path = output_dir / "p6_0_artifact_inventory.jsonl.gz"
    replay_path = output_dir / "p6_0_decision_replay.jsonl.gz"
    _write_jsonl_gzip(claim_path, [row.model_dump(mode="json") for row in claims])
    _write_jsonl_gzip(inventory_path, [row.model_dump(mode="json") for row in inventory])
    _write_jsonl_gzip(replay_path, [row.model_dump(mode="json") for row in replay])
    snapshot = EvaluationSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        claim_registry_path=claim_path.name,
        claim_registry_sha256=file_sha256(claim_path),
        artifact_inventory_path=inventory_path.name,
        artifact_inventory_sha256=file_sha256(inventory_path),
        decision_replay_path=replay_path.name,
        decision_replay_sha256=file_sha256(replay_path),
        quality=_quality(claims, inventory, replay),
        warning=(
            "PAPER-CLAIM AUDIT, NOT A SCIENTIFIC RESULT. Current artifacts establish "
            "reproducible engineering boundaries; no headline claim is yet validated."
        ),
    )
    snapshot_path = output_dir / "p6_0_evaluation_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p6_0_evaluation_report.md").write_text(
        render_evaluation_report(snapshot, claims), encoding="utf-8"
    )
    manifest = EvaluationManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        claim_registry_path=claim_path.name,
        claim_registry_sha256=file_sha256(claim_path),
        artifact_inventory_path=inventory_path.name,
        artifact_inventory_sha256=file_sha256(inventory_path),
        artifact_inventory_count=len(inventory),
        decision_replay_path=replay_path.name,
        decision_replay_sha256=file_sha256(replay_path),
        decision_replay_count=len(replay),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p6_0_evaluation_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class EvaluationStore:
    def __init__(self, snapshot: EvaluationSnapshot, manifest: EvaluationManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "EvaluationStore":
        return cls(
            EvaluationSnapshot.model_validate(_load_json(snapshot_path)),
            EvaluationManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, filename: str, limit: int, predicate=None) -> list[dict]:
        rows = []
        with gzip.open(self.root / filename, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if predicate is not None and not predicate(row):
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    break
        return rows

    def claims(self) -> list[dict]:
        return self._sample(self.manifest.claim_registry_path, self.manifest.claim_registry_count)

    def artifacts(self) -> list[dict]:
        return self._sample(self.manifest.artifact_inventory_path, self.manifest.artifact_inventory_count)

    def replay(self, limit: int = 20) -> list[dict]:
        return self._sample(self.manifest.decision_replay_path, limit)

    def hypothesis_replay(self, hypothesis_id: str) -> dict | None:
        rows = self._sample(
            self.manifest.decision_replay_path,
            1,
            lambda row: row["hypothesis_id"] == hypothesis_id,
        )
        return rows[0] if rows else None

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.claim_registry_path) == self.manifest.claim_registry_sha256
                and file_sha256(self.root / self.manifest.artifact_inventory_path) == self.manifest.artifact_inventory_sha256
                and file_sha256(self.root / self.manifest.decision_replay_path) == self.manifest.decision_replay_sha256
                and file_sha256(self.root / self.manifest.snapshot_path) == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_evaluation_store() -> EvaluationStore:
    return EvaluationStore.load(default_evaluation_snapshot_path(), default_evaluation_manifest_path())
