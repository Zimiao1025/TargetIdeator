"""P6.2 deterministic repeated-cohort injection and dependency controls."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.claims.store import (
    default_claim_graph_manifest_path,
    load_default_claim_graph_store,
)
from targetideator.evaluation.cohort_stress_models import (
    CohortInjectionLedgerRecord,
    CohortInjectionScenario,
    CohortStressManifest,
    CohortStressQuality,
    CohortStressSnapshot,
    CohortTargetPropagationRecord,
)
from targetideator.evaluation.robustness_store import default_robustness_manifest_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip

BUILDER_VERSION = "p6.2-duplicate-cohort-stress-v1"
SNAPSHOT_ID = "ti:cohort-stress:dependency-correction-fixed-injection-v1"
CREATED_AT = datetime(2026, 11, 3, 0, 30, tzinfo=timezone.utc)
AS_OF_DATE = date(2025, 9, 17)
SELECTION_SEED = 20261103
LEVELS = (0.01, 0.05, 0.1, 0.2)
TARGETS = ("IL23A", "JAK1", "TNFSF15", "NOD2")
DISEASE_ID = "MONDO:0005011"


def default_cohort_stress_snapshot_path() -> Path:
    return fixture_path("p6_2_cohort_stress_snapshot.json")


def default_cohort_stress_manifest_path() -> Path:
    return fixture_path("p6_2_cohort_stress_manifest.json")


def _stable_order(ids: list[str]) -> list[str]:
    return sorted(
        ids,
        key=lambda value: (
            hashlib.sha256(f"{SELECTION_SEED}|cohort-injection|{value}".encode()).hexdigest(),
            value,
        ),
    )


def _selected_count(total: int, fraction: float) -> int:
    return max(1, round(total * fraction))


def build_cohort_stress_records() -> tuple[
    list[CohortInjectionLedgerRecord],
    list[CohortInjectionScenario],
    list[CohortTargetPropagationRecord],
    CohortStressQuality,
]:
    store = load_default_claim_graph_store()
    family_claim_ids: dict[str, set[str]] = {}
    family_keys: dict[str, str] = {}
    family_targets: dict[str, str] = {}
    target_claim_counts: dict[str, int] = {}
    target_family_counts: dict[str, int] = {}

    for target_id in TARGETS:
        query = store.query(DISEASE_ID, target_id, AS_OF_DATE)
        if query.independent_evidence_count == 0:
            continue
        target_claim_counts[target_id] = query.naive_claim_count
        target_family_counts[target_id] = query.independent_evidence_count
        for family in query.evidence_families:
            if family.id in family_targets and family_targets[family.id] != target_id:
                raise ValueError(f"Evidence family {family.id} crosses frozen target strata")
            family_targets[family.id] = target_id
            family_keys[family.id] = family.dependency_key
            family_claim_ids[family.id] = set(family.member_claim_ids)

    family_ids = sorted(family_claim_ids)
    active_targets = tuple(sorted(target_claim_counts))
    baseline_claim_count = sum(target_claim_counts.values())
    baseline_family_count = len(family_ids)
    bundle_sizes = {len(ids) for ids in family_claim_ids.values()}
    if baseline_claim_count != 129 or baseline_family_count != 43 or bundle_sizes != {3}:
        raise ValueError("Frozen P6.2 baseline no longer matches 129 claims / 43 three-record families")

    ordered = _stable_order(family_ids)
    ledger: list[CohortInjectionLedgerRecord] = []
    scenarios: list[CohortInjectionScenario] = []
    target_rows: list[CohortTargetPropagationRecord] = []
    selections: list[set[str]] = []

    for fraction in LEVELS:
        selected = set(ordered[: _selected_count(baseline_family_count, fraction)])
        selections.append(selected)
        injected_claim_count = sum(len(family_claim_ids[item]) for item in selected)
        selected_by_target: dict[str, int] = defaultdict(int)
        injected_by_target: dict[str, int] = defaultdict(int)
        for family_id in selected:
            target_id = family_targets[family_id]
            selected_by_target[target_id] += 1
            injected_by_target[target_id] += len(family_claim_ids[family_id])

        scenario_id = stable_id("cohort-stress-scenario", f"injection-{fraction:.2f}")
        ledger.append(
            CohortInjectionLedgerRecord(
                id=stable_id("cohort-injection-ledger", f"injection-{fraction:.2f}"),
                requested_fraction=fraction,
                selected_family_count=len(selected),
                selected_family_ids=sorted(selected),
                selected_dependency_keys=sorted(family_keys[item] for item in selected),
                injected_bundle_count=len(selected),
                injected_claim_record_count=injected_claim_count,
            )
        )
        scenarios.append(
            CohortInjectionScenario(
                id=scenario_id,
                requested_fraction=fraction,
                selected_family_count=len(selected),
                injected_claim_record_count=injected_claim_count,
                naive_claim_record_count=baseline_claim_count + injected_claim_count,
                naive_claim_inflation_fraction=injected_claim_count / baseline_claim_count,
                family_blind_independent_count=baseline_family_count + len(selected),
                family_blind_inflation_fraction=len(selected) / baseline_family_count,
                false_independent_units_prevented=len(selected),
                lineage_stripped_failure_exposed_count=len(selected),
                target_naive_count_changed_count=sum(
                    selected_by_target[target_id] > 0 for target_id in active_targets
                ),
            )
        )
        for target_id in active_targets:
            target_rows.append(
                CohortTargetPropagationRecord(
                    id=stable_id("cohort-target-propagation", f"{scenario_id}-{target_id}"),
                    scenario_id=scenario_id,
                    target_id=target_id,
                    baseline_claim_record_count=target_claim_counts[target_id],
                    baseline_independent_family_count=target_family_counts[target_id],
                    selected_family_count=selected_by_target[target_id],
                    injected_claim_record_count=injected_by_target[target_id],
                    naive_claim_record_count=(
                        target_claim_counts[target_id] + injected_by_target[target_id]
                    ),
                    family_blind_independent_count=(
                        target_family_counts[target_id] + selected_by_target[target_id]
                    ),
                    dependency_corrected_independent_count=target_family_counts[target_id],
                )
            )

    nested = all(selections[index] < selections[index + 1] for index in range(3))
    correction_invariant = all(
        row.dependency_corrected_independent_count == baseline_family_count
        and row.dependency_corrected_inflation_fraction == 0
        and row.target_corrected_count_changed_count == 0
        for row in scenarios
    ) and all(not row.dependency_corrected_count_changed for row in target_rows)
    negative_control = all(
        row.lineage_stripped_failure_exposed_count == row.selected_family_count
        and row.family_blind_independent_count > baseline_family_count
        for row in scenarios
    )
    quality = CohortStressQuality(
        nested_selection_invariant_passed=nested,
        active_family_bundle_size_uniform=bundle_sizes == {3},
        maximum_naive_claim_inflation_fraction=max(
            row.naive_claim_inflation_fraction for row in scenarios
        ),
        maximum_family_blind_inflation_fraction=max(
            row.family_blind_inflation_fraction for row in scenarios
        ),
        dependency_correction_invariant_passed=correction_invariant,
        lineage_stripped_negative_control_passed=negative_control,
        engineering_gate_passed=(
            len(ledger) == 4
            and len(scenarios) == 4
            and len(target_rows) == 8
            and nested
            and correction_invariant
            and negative_control
        ),
        blocking_limitations=[
            "Injected copies are synthetic stress records, not observed duplicate publications or cohorts.",
            "The control tests count invariance only; it does not validate claim truth, causal direction, or scientific independence labels.",
            "Dependency correction succeeds only when evidence-family lineage is present and correct; the stripped-lineage control fails by design.",
            "No hypothesis score, outcome field, calibration model, or target-level clinical metric is computed.",
            "This experiment cannot unlock C1, C2, C3, or C4 scientific claims.",
        ],
    )
    return ledger, scenarios, target_rows, quality


def _source_checksums() -> dict[str, str]:
    paths = (default_claim_graph_manifest_path(), default_robustness_manifest_path())
    return {path.name: file_sha256(path) for path in paths}


def _render_report(snapshot: CohortStressSnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P6.2 duplicate-cohort dependency stress",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Baseline active claims: {q.baseline_claim_record_count}",
            f"- Baseline evidence families: {q.baseline_independent_family_count}",
            f"- Scenarios: {q.scenario_count}",
            f"- Maximum naive inflation: {q.maximum_naive_claim_inflation_fraction:.4f}",
            f"- Maximum corrected inflation: {q.maximum_dependency_corrected_inflation_fraction:.4f}",
            f"- Lineage-stripped negative control passed: {str(q.lineage_stripped_negative_control_passed).lower()}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def write_cohort_stress_artifacts(
    output_dir: Path,
) -> tuple[CohortStressSnapshot, CohortStressManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger, scenarios, target_rows, quality = build_cohort_stress_records()
    ledger_path = output_dir / "p6_2_cohort_injection_ledger.jsonl.gz"
    scenario_path = output_dir / "p6_2_cohort_stress_scenarios.jsonl.gz"
    target_path = output_dir / "p6_2_cohort_target_propagation.jsonl.gz"
    _write_jsonl_gzip(ledger_path, [row.model_dump(mode="json") for row in ledger])
    _write_jsonl_gzip(scenario_path, [row.model_dump(mode="json") for row in scenarios])
    _write_jsonl_gzip(target_path, [row.model_dump(mode="json") for row in target_rows])
    snapshot = CohortStressSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        ledger_path=ledger_path.name,
        ledger_sha256=file_sha256(ledger_path),
        scenario_path=scenario_path.name,
        scenario_sha256=file_sha256(scenario_path),
        target_propagation_path=target_path.name,
        target_propagation_sha256=file_sha256(target_path),
        quality=quality,
        warning=(
            "MODEL-ONLY COUNT INVARIANCE CONTROL. Synthetic cohort duplication does not "
            "validate scientific independence, outcomes, C1, C2, C3, or C4."
        ),
    )
    snapshot_path = output_dir / "p6_2_cohort_stress_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p6_2_cohort_stress_report.md").write_text(
        _render_report(snapshot), encoding="utf-8"
    )
    manifest = CohortStressManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        ledger_path=ledger_path.name,
        ledger_sha256=file_sha256(ledger_path),
        scenario_path=scenario_path.name,
        scenario_sha256=file_sha256(scenario_path),
        target_propagation_path=target_path.name,
        target_propagation_sha256=file_sha256(target_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p6_2_cohort_stress_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class CohortStressStore:
    def __init__(self, snapshot: CohortStressSnapshot, manifest: CohortStressManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "CohortStressStore":
        return cls(
            CohortStressSnapshot.model_validate(_load_json(snapshot_path)),
            CohortStressManifest.model_validate(_load_json(manifest_path)),
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

    def scenarios(self) -> list[dict]:
        return self._rows(self.manifest.scenario_path, 4)

    def ledger(self) -> list[dict]:
        return self._rows(self.manifest.ledger_path, 4)

    def targets(self, scenario_id: str | None = None) -> list[dict]:
        return self._rows(
            self.manifest.target_propagation_path,
            8,
            None if scenario_id is None else lambda row: row["scenario_id"] == scenario_id,
        )

    def quality_report(self) -> dict:
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.ledger_path) == self.manifest.ledger_sha256
                and file_sha256(self.root / self.manifest.scenario_path) == self.manifest.scenario_sha256
                and file_sha256(self.root / self.manifest.target_propagation_path) == self.manifest.target_propagation_sha256
                and file_sha256(self.root / self.manifest.snapshot_path) == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": _source_checksums() == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_cohort_stress_store() -> CohortStressStore:
    return CohortStressStore.load(
        default_cohort_stress_snapshot_path(), default_cohort_stress_manifest_path()
    )
