"""Build the P6.3 frozen proposer-only versus falsify-revise paired control."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.contracts.models import Verdict
from targetideator.evaluation.cohort_stress_store import default_cohort_stress_manifest_path
from targetideator.evaluation.paired_control_models import (
    CriticCellAuditRecord,
    FalseRejectionPropagationRecord,
    PairedControlManifest,
    PairedControlQuality,
    PairedControlRecord,
    PairedControlSnapshot,
)
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.store import (
    default_falsification_manifest_path,
    load_default_falsification_store,
)
from targetideator.ideation.store import (
    default_ideation_manifest_path,
    load_default_ideation_store,
)
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.revision.models import RevisionStatus
from targetideator.revision.store import (
    default_revision_manifest_path,
    load_default_revision_store,
)

BUILDER_VERSION = "p6.3-fixed-paired-proposer-falsify-revise-v1"
SNAPSHOT_ID = "ti:paired-control:proposer-vs-falsify-revise-v1"
CREATED_AT = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)


def default_paired_control_snapshot_path() -> Path:
    return fixture_path("p6_3_paired_control_snapshot.json")


def default_paired_control_manifest_path() -> Path:
    return fixture_path("p6_3_paired_control_manifest.json")


def build_paired_control_records() -> tuple[
    list[PairedControlRecord],
    list[CriticCellAuditRecord],
    list[FalseRejectionPropagationRecord],
    PairedControlQuality,
]:
    portfolio = load_default_ideation_store().portfolio
    falsification = load_default_falsification_store().snapshot
    revision = load_default_revision_store().snapshot
    results = {row.hypothesis_id: row for row in falsification.results}
    candidates = {row.source_hypothesis_id: row for row in revision.candidates}
    pairs: list[PairedControlRecord] = []
    audits: list[CriticCellAuditRecord] = []
    queue: list[FalseRejectionPropagationRecord] = []

    for hypothesis in portfolio.hypotheses:
        result = results[hypothesis.id]
        candidate = candidates[hypothesis.id]
        pair_id = stable_id("paired-control", hypothesis.id)
        patch_by_assessment: dict[str, list] = {}
        for patch in candidate.patches:
            patch_by_assessment.setdefault(patch.source_assessment_id, []).append(patch)
        non_survive = [
            assessment
            for assessment in result.assessments
            if assessment.verdict != Verdict.SURVIVE
        ]
        survive = [
            assessment
            for assessment in result.assessments
            if assessment.verdict == Verdict.SURVIVE
        ]
        covered = sum(bool(patch_by_assessment.get(item.id)) for item in non_survive)
        residual = len(non_survive) - covered
        source_counters = set(hypothesis.counterevidence_claim_ids)
        critic_counters = set().union(
            *(set(item.counterevidence_claim_ids) for item in result.assessments)
        )
        revised_counters = set(candidate.revised_hypothesis.counterevidence_claim_ids)
        retained_by_critic = len(source_counters & critic_counters)
        retained_by_revision = len(source_counters & revised_counters)
        abstaining = [
            assessment
            for assessment in result.assessments
            if assessment.verdict == Verdict.ABSTAIN
        ]
        propagated = (
            result.combined_verdict == Verdict.ABSTAIN
            and candidate.revision_status == RevisionStatus.BLOCKED_PENDING_EVIDENCE
        )
        pairs.append(
            PairedControlRecord(
                id=pair_id,
                hypothesis_id=hypothesis.id,
                target_id=hypothesis.target.identifier,
                target_label=hypothesis.target.label,
                surviving_critic_count=len(survive),
                critic_exposed_unsupported_proxy_count=len(non_survive),
                proposer_only_unqualified_proxy_count=len(non_survive),
                full_path_unqualified_proxy_count=residual,
                unsupported_proxy_reduction_count=len(non_survive) - residual,
                unsupported_proxy_reduction_fraction=(
                    (len(non_survive) - residual) / len(non_survive)
                    if non_survive
                    else 0.0
                ),
                source_counterevidence_binding_count=len(source_counters),
                critic_counterevidence_retained_count=retained_by_critic,
                revised_counterevidence_retained_count=retained_by_revision,
                counterevidence_retention_fraction=(
                    retained_by_revision / len(source_counters) if source_counters else None
                ),
                combined_verdict=result.combined_verdict,
                revision_status=candidate.revision_status,
                revision_patch_count=len(candidate.patches),
                covered_non_survive_critic_count=covered,
                abstain_critic_count=len(abstaining),
                abstain_to_block_propagated=propagated,
                potential_false_rejection_review_required=propagated,
            )
        )
        for assessment in result.assessments:
            patches = patch_by_assessment.get(assessment.id, [])
            unsupported_proxy = assessment.verdict != Verdict.SURVIVE
            audits.append(
                CriticCellAuditRecord(
                    id=stable_id("critic-cell-audit", assessment.id),
                    pair_id=pair_id,
                    hypothesis_id=hypothesis.id,
                    assessment_id=assessment.id,
                    critic_type=assessment.critic_type,
                    verdict=assessment.verdict,
                    evidence_gap_count=len(assessment.evidence_gaps),
                    counterevidence_claim_count=len(assessment.counterevidence_claim_ids),
                    critic_exposed_unsupported_proxy=unsupported_proxy,
                    revision_patch_count=len(patches),
                    full_path_qualification_present=bool(patches),
                    counterevidence_retained_in_revised_core=set(
                        assessment.counterevidence_claim_ids
                    ).issubset(revised_counters),
                    survive_patch_leak=(assessment.verdict == Verdict.SURVIVE and bool(patches)),
                )
            )
        if propagated:
            queue.append(
                FalseRejectionPropagationRecord(
                    id=stable_id("false-rejection-review", hypothesis.id),
                    pair_id=pair_id,
                    hypothesis_id=hypothesis.id,
                    target_id=hypothesis.target.identifier,
                    abstaining_assessment_ids=[item.id for item in abstaining],
                    abstaining_critic_types=[item.critic_type for item in abstaining],
                )
            )

    proposer_proxy = sum(row.proposer_only_unqualified_proxy_count for row in pairs)
    full_proxy = sum(row.full_path_unqualified_proxy_count for row in pairs)
    source_counter_count = sum(row.source_counterevidence_binding_count for row in pairs)
    critic_counter_count = sum(row.critic_counterevidence_retained_count for row in pairs)
    revised_counter_count = sum(row.revised_counterevidence_retained_count for row in pairs)
    survive_count = sum(row.surviving_critic_count for row in pairs)
    abstain_count = sum(row.abstain_critic_count for row in pairs)
    survive_leaks = sum(row.survive_patch_leak for row in audits)
    retired = sum(
        row.revision_status == RevisionStatus.RETIRED_BY_REJECTION for row in pairs
    )
    core_mutations = sum(row.core_scientific_mutation_count for row in pairs)
    quality = PairedControlQuality(
        paired_hypothesis_count=len(pairs),
        critic_cell_count=len(audits),
        false_rejection_queue_count=len(queue),
        proposer_only_unqualified_proxy_count=proposer_proxy,
        full_path_unqualified_proxy_count=full_proxy,
        unsupported_proxy_reduction_count=proposer_proxy - full_proxy,
        unsupported_proxy_reduction_fraction=(
            (proposer_proxy - full_proxy) / proposer_proxy if proposer_proxy else 0
        ),
        source_counterevidence_binding_count=source_counter_count,
        critic_counterevidence_retained_count=critic_counter_count,
        revised_counterevidence_retained_count=revised_counter_count,
        counterevidence_retention_fraction=(
            revised_counter_count / source_counter_count if source_counter_count else 0
        ),
        surviving_critic_count=survive_count,
        surviving_critic_patch_leak_count=survive_leaks,
        abstain_critic_count=abstain_count,
        abstain_to_block_propagation_count=len(queue),
        retired_by_rejection_count=retired,
        core_scientific_mutation_count=core_mutations,
        c3_paired_engineering_control_completed=True,
        engineering_gate_passed=(
            len(pairs) == 5
            and len(audits) == 20
            and len(queue) == 3
            and proposer_proxy == 16
            and full_proxy == 0
            and source_counter_count == critic_counter_count == revised_counter_count == 4
            and survive_count == 4
            and survive_leaks == 0
            and abstain_count == 8
            and retired == 0
            and core_mutations == 0
        ),
        blocking_limitations=[
            "Unsupported-claim reduction is a critic-exposed proxy defined by the same frozen deterministic rules that create the revisions.",
            "The paired arms are pipeline ablations over five model-silver hypotheses, not independent model generations or human-scored outputs.",
            "Counterevidence retention measures ID/provenance preservation, not whether the counterevidence is scientifically complete or correct.",
            "Three abstention-to-block paths are review candidates; without human gold they cannot be labeled false rejections or used to compute a rate.",
            "No outcome, model refit, clinical metric, or C1/C4 comparison is performed; C3 remains engineering evidence only.",
        ],
    )
    return pairs, audits, queue, quality


def _source_checksums() -> dict[str, str]:
    paths = (
        default_ideation_manifest_path(),
        default_falsification_manifest_path(),
        default_revision_manifest_path(),
        default_cohort_stress_manifest_path(),
    )
    return {path.name: file_sha256(path) for path in paths}


def _render_report(snapshot: PairedControlSnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P6.3 paired proposer/falsify/revise control",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Paired hypotheses / critic cells: {q.paired_hypothesis_count} / {q.critic_cell_count}",
            f"- Critic-exposed unqualified proxy: {q.proposer_only_unqualified_proxy_count} → {q.full_path_unqualified_proxy_count}",
            f"- Counterevidence bindings retained: {q.revised_counterevidence_retained_count}/{q.source_counterevidence_binding_count}",
            f"- Surviving-critic patch leaks: {q.surviving_critic_patch_leak_count}",
            f"- Abstention-to-block review queue: {q.false_rejection_queue_count}",
            f"- False-rejection rate computed: {str(q.false_rejection_rate_computed).lower()}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def write_paired_control_artifacts(
    output_dir: Path,
) -> tuple[PairedControlSnapshot, PairedControlManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs, audits, queue, quality = build_paired_control_records()
    pair_path = output_dir / "p6_3_paired_comparisons.jsonl.gz"
    audit_path = output_dir / "p6_3_critic_cell_audit.jsonl.gz"
    queue_path = output_dir / "p6_3_false_rejection_review_queue.jsonl.gz"
    _write_jsonl_gzip(pair_path, [row.model_dump(mode="json") for row in pairs])
    _write_jsonl_gzip(audit_path, [row.model_dump(mode="json") for row in audits])
    _write_jsonl_gzip(queue_path, [row.model_dump(mode="json") for row in queue])
    snapshot = PairedControlSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        pair_path=pair_path.name,
        pair_sha256=file_sha256(pair_path),
        critic_audit_path=audit_path.name,
        critic_audit_sha256=file_sha256(audit_path),
        false_rejection_queue_path=queue_path.name,
        false_rejection_queue_sha256=file_sha256(queue_path),
        quality=quality,
        warning=(
            "MODEL-ONLY PAIRED PIPELINE CONTROL. Proxy reduction and provenance retention "
            "do not establish scientific correctness or a false-rejection rate."
        ),
    )
    snapshot_path = output_dir / "p6_3_paired_control_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p6_3_paired_control_report.md").write_text(
        _render_report(snapshot), encoding="utf-8"
    )
    manifest = PairedControlManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        pair_path=pair_path.name,
        pair_sha256=file_sha256(pair_path),
        critic_audit_path=audit_path.name,
        critic_audit_sha256=file_sha256(audit_path),
        false_rejection_queue_path=queue_path.name,
        false_rejection_queue_sha256=file_sha256(queue_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p6_3_paired_control_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class PairedControlStore:
    def __init__(self, snapshot: PairedControlSnapshot, manifest: PairedControlManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "PairedControlStore":
        return cls(
            PairedControlSnapshot.model_validate(_load_json(snapshot_path)),
            PairedControlManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _rows(self, filename: str, limit: int, predicate=None) -> list[dict]:
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

    def pairs(self) -> list[dict]:
        return self._rows(self.manifest.pair_path, 5)

    def critic_cells(self, hypothesis_id: str | None = None) -> list[dict]:
        return self._rows(
            self.manifest.critic_audit_path,
            20,
            None if hypothesis_id is None else lambda row: row["hypothesis_id"] == hypothesis_id,
        )

    def false_rejection_queue(self) -> list[dict]:
        return self._rows(self.manifest.false_rejection_queue_path, 3)

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.pair_path) == self.manifest.pair_sha256
                and file_sha256(self.root / self.manifest.critic_audit_path) == self.manifest.critic_audit_sha256
                and file_sha256(self.root / self.manifest.false_rejection_queue_path) == self.manifest.false_rejection_queue_sha256
                and file_sha256(self.root / self.manifest.snapshot_path) == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_paired_control_store() -> PairedControlStore:
    return PairedControlStore.load(
        default_paired_control_snapshot_path(), default_paired_control_manifest_path()
    )
