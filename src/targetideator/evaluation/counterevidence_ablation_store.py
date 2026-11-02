"""Build P6.4 full versus explicit-counterevidence-masked critic comparisons."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.contracts.models import Verdict
from targetideator.evaluation.counterevidence_ablation_models import (
    CounterevidenceAblationManifest,
    CounterevidenceAblationQuality,
    CounterevidenceAblationSnapshot,
    CounterevidenceCellComparison,
    CounterevidenceHypothesisComparison,
    CounterevidenceMaskLedgerRecord,
)
from targetideator.evaluation.paired_control_store import default_paired_control_manifest_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.store import (
    build_falsification_result,
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

BUILDER_VERSION = "p6.4-counterevidence-role-masking-v1"
SNAPSHOT_ID = "ti:counterevidence-ablation:explicit-role-masking-v1"
CREATED_AT = datetime(2026, 11, 3, 3, 30, tzinfo=timezone.utc)


def default_counterevidence_ablation_snapshot_path() -> Path:
    return fixture_path("p6_4_counterevidence_ablation_snapshot.json")


def default_counterevidence_ablation_manifest_path() -> Path:
    return fixture_path("p6_4_counterevidence_ablation_manifest.json")


def _blocked(verdict: Verdict) -> bool:
    return verdict in {Verdict.ABSTAIN, Verdict.REJECT}


def build_counterevidence_ablation_records() -> tuple[
    list[CounterevidenceMaskLedgerRecord],
    list[CounterevidenceCellComparison],
    list[CounterevidenceHypothesisComparison],
    CounterevidenceAblationQuality,
]:
    portfolio = load_default_ideation_store().portfolio
    full_results = {
        row.hypothesis_id: row for row in load_default_falsification_store().snapshot.results
    }
    ledger: list[CounterevidenceMaskLedgerRecord] = []
    cells: list[CounterevidenceCellComparison] = []
    hypotheses: list[CounterevidenceHypothesisComparison] = []

    for hypothesis in portfolio.hypotheses:
        for claim_id in hypothesis.counterevidence_claim_ids:
            ledger.append(
                CounterevidenceMaskLedgerRecord(
                    id=stable_id("counterevidence-mask", f"{hypothesis.id}-{claim_id}"),
                    hypothesis_id=hypothesis.id,
                    target_id=hypothesis.target.identifier,
                    counterevidence_claim_id=claim_id,
                )
            )
        full = full_results[hypothesis.id]
        masked = build_falsification_result(hypothesis, mask_counterevidence=True)
        full_by_type = {row.critic_type: row for row in full.assessments}
        masked_by_type = {row.critic_type: row for row in masked.assessments}
        for critic_type in full_by_type:
            before = full_by_type[critic_type]
            after = masked_by_type[critic_type]
            cells.append(
                CounterevidenceCellComparison(
                    id=stable_id(
                        "counterevidence-cell-comparison",
                        f"{hypothesis.id}-{critic_type.value}",
                    ),
                    hypothesis_id=hypothesis.id,
                    critic_type=critic_type,
                    full_verdict=before.verdict,
                    masked_verdict=after.verdict,
                    verdict_changed=before.verdict != after.verdict,
                    full_rule_id=before.rule_id,
                    masked_rule_id=after.rule_id,
                    rule_changed=before.rule_id != after.rule_id,
                    full_evidence_claim_count=len(before.evidence_claim_ids),
                    masked_evidence_claim_count=len(after.evidence_claim_ids),
                    evidence_reference_count_changed=(
                        before.evidence_claim_ids != after.evidence_claim_ids
                    ),
                    full_counterevidence_reference_count=len(
                        before.counterevidence_claim_ids
                    ),
                    removed_counterevidence_reference_count=len(
                        before.counterevidence_claim_ids
                    ),
                    full_evidence_gap_count=len(before.evidence_gaps),
                    masked_evidence_gap_count=len(after.evidence_gaps),
                )
            )
        full_non_survive = sum(
            row.verdict != Verdict.SURVIVE for row in full.assessments
        )
        masked_non_survive = sum(
            row.verdict != Verdict.SURVIVE for row in masked.assessments
        )
        hypotheses.append(
            CounterevidenceHypothesisComparison(
                id=stable_id("counterevidence-hypothesis-comparison", hypothesis.id),
                hypothesis_id=hypothesis.id,
                target_id=hypothesis.target.identifier,
                target_label=hypothesis.target.label,
                masked_binding_count=len(hypothesis.counterevidence_claim_ids),
                full_combined_verdict=full.combined_verdict,
                masked_combined_verdict=masked.combined_verdict,
                combined_verdict_changed=full.combined_verdict != masked.combined_verdict,
                full_binding_critic_types=full.binding_critic_types,
                masked_binding_critic_types=masked.binding_critic_types,
                binding_critic_set_changed=(
                    set(full.binding_critic_types) != set(masked.binding_critic_types)
                ),
                full_non_survive_critic_count=full_non_survive,
                masked_non_survive_critic_count=masked_non_survive,
                qualification_proxy_lost_count=max(
                    0, full_non_survive - masked_non_survive
                ),
                full_projected_revision_field_count=len(full.revision_fields),
                masked_projected_revision_field_count=len(masked.revision_fields),
                projected_revision_fields_changed=(
                    full.revision_fields != masked.revision_fields
                ),
                full_blocked=_blocked(full.combined_verdict),
                masked_blocked=_blocked(masked.combined_verdict),
                block_decision_changed=(
                    _blocked(full.combined_verdict) != _blocked(masked.combined_verdict)
                ),
            )
        )

    removed_refs = sum(row.removed_counterevidence_reference_count for row in cells)
    verdict_changes = sum(row.verdict_changed for row in cells)
    rule_changes = sum(row.rule_changed for row in cells)
    evidence_changes = sum(row.evidence_reference_count_changed for row in cells)
    combined_changes = sum(row.combined_verdict_changed for row in hypotheses)
    binding_changes = sum(row.binding_critic_set_changed for row in hypotheses)
    revision_changes = sum(row.projected_revision_fields_changed for row in hypotheses)
    full_non_survive = sum(row.full_non_survive_critic_count for row in hypotheses)
    masked_non_survive = sum(row.masked_non_survive_critic_count for row in hypotheses)
    lost_proxy = sum(row.qualification_proxy_lost_count for row in hypotheses)
    full_blocked = sum(row.full_blocked for row in hypotheses)
    masked_blocked = sum(row.masked_blocked for row in hypotheses)
    block_changes = sum(row.block_decision_changed for row in hypotheses)
    quality = CounterevidenceAblationQuality(
        paired_hypothesis_count=len(hypotheses),
        critic_cell_count=len(cells),
        mask_ledger_record_count=len(ledger),
        hypotheses_with_masked_counterevidence_count=sum(
            row.masked_binding_count > 0 for row in hypotheses
        ),
        removed_counterevidence_reference_count=removed_refs,
        cell_verdict_changed_count=verdict_changes,
        cell_rule_changed_count=rule_changes,
        cell_evidence_reference_changed_count=evidence_changes,
        combined_verdict_changed_count=combined_changes,
        binding_critic_set_changed_count=binding_changes,
        projected_revision_fields_changed_count=revision_changes,
        full_non_survive_critic_count=full_non_survive,
        masked_non_survive_critic_count=masked_non_survive,
        qualification_proxy_lost_count=lost_proxy,
        full_blocked_hypothesis_count=full_blocked,
        masked_blocked_hypothesis_count=masked_blocked,
        block_decision_changed_count=block_changes,
        counterevidence_local_sensitivity_detected=(
            verdict_changes > 0 or rule_changes > 0
        ),
        engineering_gate_passed=(
            len(hypotheses) == 5
            and len(cells) == 20
            and len(ledger) == 4
            and removed_refs == 8
            and verdict_changes == 1
            and rule_changes == 2
            and evidence_changes == 7
            and combined_changes == 0
            and block_changes == 0
        ),
        blocking_limitations=[
            "Masking hides the explicit refutes/counter role but retains the source document in the frozen mechanism chain.",
            "Only four counterevidence binding occurrences across five model-silver hypotheses are available.",
            "A local deterministic-rule change is not evidence that the counterclaim is scientifically correct or complete.",
            "No combined verdict or block decision changed, so decision-level value of counterevidence is not supported in this slice.",
            "No outcome, model refit, clinical metric, C1, or C4 comparison is performed.",
        ],
    )
    return ledger, cells, hypotheses, quality


def _source_checksums() -> dict[str, str]:
    paths = (
        default_ideation_manifest_path(),
        default_falsification_manifest_path(),
        default_paired_control_manifest_path(),
    )
    return {path.name: file_sha256(path) for path in paths}


def _render_report(snapshot: CounterevidenceAblationSnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P6.4 counterevidence masking ablation",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Hypothesis pairs / critic cells: {q.paired_hypothesis_count} / {q.critic_cell_count}",
            f"- Masked binding occurrences: {q.mask_ledger_record_count}",
            f"- Removed critic counter references: {q.removed_counterevidence_reference_count}",
            f"- Cell verdict / rule changes: {q.cell_verdict_changed_count} / {q.cell_rule_changed_count}",
            f"- Combined verdict changes: {q.combined_verdict_changed_count}",
            f"- Block decision changes: {q.block_decision_changed_count}",
            f"- Qualification proxies lost after masking: {q.qualification_proxy_lost_count}",
            "",
            "## Conclusion",
            "",
            "Local critic sensitivity is detectable, but decision-level counterevidence value is not supported on this frozen slice.",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def write_counterevidence_ablation_artifacts(
    output_dir: Path,
) -> tuple[CounterevidenceAblationSnapshot, CounterevidenceAblationManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger, cells, hypotheses, quality = build_counterevidence_ablation_records()
    ledger_path = output_dir / "p6_4_counterevidence_mask_ledger.jsonl.gz"
    cell_path = output_dir / "p6_4_critic_cell_comparisons.jsonl.gz"
    hypothesis_path = output_dir / "p6_4_hypothesis_comparisons.jsonl.gz"
    _write_jsonl_gzip(ledger_path, [row.model_dump(mode="json") for row in ledger])
    _write_jsonl_gzip(cell_path, [row.model_dump(mode="json") for row in cells])
    _write_jsonl_gzip(hypothesis_path, [row.model_dump(mode="json") for row in hypotheses])
    snapshot = CounterevidenceAblationSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        mask_ledger_path=ledger_path.name,
        mask_ledger_sha256=file_sha256(ledger_path),
        cell_comparison_path=cell_path.name,
        cell_comparison_sha256=file_sha256(cell_path),
        hypothesis_comparison_path=hypothesis_path.name,
        hypothesis_comparison_sha256=file_sha256(hypothesis_path),
        quality=quality,
        warning=(
            "MODEL-ONLY COUNTEREVIDENCE ABLATION. Local rule sensitivity does not "
            "establish scientific correctness or decision-level value."
        ),
    )
    snapshot_path = output_dir / "p6_4_counterevidence_ablation_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p6_4_counterevidence_ablation_report.md").write_text(
        _render_report(snapshot), encoding="utf-8"
    )
    manifest = CounterevidenceAblationManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        mask_ledger_path=ledger_path.name,
        mask_ledger_sha256=file_sha256(ledger_path),
        cell_comparison_path=cell_path.name,
        cell_comparison_sha256=file_sha256(cell_path),
        hypothesis_comparison_path=hypothesis_path.name,
        hypothesis_comparison_sha256=file_sha256(hypothesis_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "p6_4_counterevidence_ablation_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class CounterevidenceAblationStore:
    def __init__(
        self,
        snapshot: CounterevidenceAblationSnapshot,
        manifest: CounterevidenceAblationManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(
        cls, snapshot_path: Path, manifest_path: Path
    ) -> "CounterevidenceAblationStore":
        return cls(
            CounterevidenceAblationSnapshot.model_validate(_load_json(snapshot_path)),
            CounterevidenceAblationManifest.model_validate(_load_json(manifest_path)),
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

    def ledger(self) -> list[dict]:
        return self._rows(self.manifest.mask_ledger_path, 4)

    def cells(self, changed_only: bool = False) -> list[dict]:
        return self._rows(
            self.manifest.cell_comparison_path,
            20,
            None
            if not changed_only
            else lambda row: row["verdict_changed"] or row["rule_changed"],
        )

    def hypotheses(self) -> list[dict]:
        return self._rows(self.manifest.hypothesis_comparison_path, 5)

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.mask_ledger_path) == self.manifest.mask_ledger_sha256
                and file_sha256(self.root / self.manifest.cell_comparison_path) == self.manifest.cell_comparison_sha256
                and file_sha256(self.root / self.manifest.hypothesis_comparison_path) == self.manifest.hypothesis_comparison_sha256
                and file_sha256(self.root / self.manifest.snapshot_path) == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_counterevidence_ablation_store() -> CounterevidenceAblationStore:
    return CounterevidenceAblationStore.load(
        default_counterevidence_ablation_snapshot_path(),
        default_counterevidence_ablation_manifest_path(),
    )
