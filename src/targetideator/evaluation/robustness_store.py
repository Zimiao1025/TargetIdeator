"""Run deterministic claim-graph perturbations and structural propagation audits."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from targetideator.claims.store import (
    default_claim_graph_manifest_path,
    load_default_claim_graph_store,
)
from targetideator.evaluation.robustness_models import (
    GraphLayer,
    PerturbationKind,
    PerturbationLedgerRecord,
    RobustnessManifest,
    RobustnessQuality,
    RobustnessScenario,
    RobustnessSnapshot,
    TargetPropagationRecord,
)
from targetideator.evaluation.store import (
    default_evaluation_manifest_path,
)
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ideation.store import (
    default_ideation_manifest_path,
    load_default_ideation_store,
)
from targetideator.io import write_json
from targetideator.literature.store import (
    default_literature_manifest_path,
    load_default_literature_store,
)
from targetideator.outcomes.identity_store import _write_jsonl_gzip

BUILDER_VERSION = "p6.1-claim-graph-robustness-v1"
SNAPSHOT_ID = "ti:robustness-run:claim-graph-fixed-perturbations-v1"
CREATED_AT = datetime(2026, 11, 2, 23, 45, tzinfo=timezone.utc)
SELECTION_SEED = 20261102
LEVELS = (0.01, 0.05, 0.1, 0.2)
DEPENDENCY_RELATIONS = {"same_study_as", "same_cohort_as", "replicates"}
POLARITY_FLIP = {
    "supports": "refutes",
    "refutes": "supports",
    "qualifies": "neutral",
    "neutral": "qualifies",
}


def default_robustness_snapshot_path() -> Path:
    return fixture_path("p6_1_robustness_snapshot.json")


def default_robustness_manifest_path() -> Path:
    return fixture_path("p6_1_robustness_manifest.json")


def _stable_order(ids: list[str], kind: PerturbationKind) -> list[str]:
    return sorted(
        ids,
        key=lambda value: (
            hashlib.sha256(
                f"{SELECTION_SEED}|{kind.value}|{value}".encode("utf-8")
            ).hexdigest(),
            value,
        ),
    )


def _selected_count(total: int, fraction: float) -> int:
    return max(1, round(total * fraction))


def _components(claim_ids: set[str], relations: list[dict]) -> tuple[int, float]:
    if not claim_ids:
        return 0, 0.0
    adjacency = {claim_id: set() for claim_id in claim_ids}
    for relation in relations:
        source = relation["source_claim_id"]
        target = relation["target_claim_id"]
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)
    seen = set()
    sizes = []
    for claim_id in sorted(claim_ids):
        if claim_id in seen:
            continue
        stack = [claim_id]
        seen.add(claim_id)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        sizes.append(size)
    return len(sizes), max(sizes) / len(claim_ids)


def _literature_target(claim: dict) -> tuple[str, str]:
    return claim["target"]["identifier"], claim["target"]["label"]


def _structured_target(claim: dict) -> tuple[str, str] | None:
    target = claim["context"].get("target")
    if target is not None:
        return target["identifier"], target["label"]
    if claim["subject"].get("entity_type") == "gene":
        return claim["subject"]["identifier"], claim["subject"]["label"]
    return None


def _context_sha(claim: dict) -> str:
    return hashlib.sha256(canonical_json_bytes(claim["context"])).hexdigest()


def _incident_relation_ids(claim_ids: set[str], relations: list[dict]) -> list[str]:
    return sorted(
        relation["id"]
        for relation in relations
        if relation["source_claim_id"] in claim_ids
        or relation["target_claim_id"] in claim_ids
    )


def _target_signature(claims: list[dict], relations: list[dict]) -> str:
    claim_ids = {claim["id"] for claim in claims}
    payload = {
        "claims": sorted(
            (claim["id"], claim["polarity"], _context_sha(claim))
            for claim in claims
        ),
        "incident_relations": _incident_relation_ids(claim_ids, relations),
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _target_records(
    scenario_id: str,
    baseline_claims: list[dict],
    perturbed_claims: list[dict],
    baseline_relations: list[dict],
    perturbed_relations: list[dict],
    target_getter,
    polarity_changed: set[str],
    context_changed: set[str],
    p3_bindings: dict[str, set[str]],
) -> list[TargetPropagationRecord]:
    baseline_by_target: dict[tuple[str, str], list[dict]] = defaultdict(list)
    perturbed_by_target: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for claim in baseline_claims:
        target = target_getter(claim)
        if target is not None:
            baseline_by_target[target].append(claim)
    for claim in perturbed_claims:
        target = target_getter(claim)
        if target is not None:
            perturbed_by_target[target].append(claim)
    rows = []
    for (target_id, target_label), baseline in sorted(baseline_by_target.items()):
        perturbed = perturbed_by_target.get((target_id, target_label), [])
        baseline_ids = {claim["id"] for claim in baseline}
        perturbed_ids = {claim["id"] for claim in perturbed}
        bound_hypotheses = {
            hypothesis_id
            for hypothesis_id, claim_ids in p3_bindings.items()
            if claim_ids & baseline_ids
        }
        impacted_hypotheses = {
            hypothesis_id
            for hypothesis_id, claim_ids in p3_bindings.items()
            if claim_ids & (polarity_changed | context_changed | (baseline_ids - perturbed_ids))
        }
        rows.append(
            TargetPropagationRecord(
                id=stable_id("target-propagation", f"{scenario_id}-{target_id}"),
                scenario_id=scenario_id,
                target_id=target_id,
                target_label=target_label,
                baseline_claim_count=len(baseline),
                perturbed_claim_count=len(perturbed),
                claim_retention=len(perturbed) / len(baseline),
                polarity_changed_claim_count=len(baseline_ids & polarity_changed),
                context_changed_claim_count=len(baseline_ids & context_changed),
                baseline_incident_relation_count=len(
                    _incident_relation_ids(baseline_ids, baseline_relations)
                ),
                perturbed_incident_relation_count=len(
                    _incident_relation_ids(perturbed_ids, perturbed_relations)
                ),
                signature_changed=(
                    _target_signature(baseline, baseline_relations)
                    != _target_signature(perturbed, perturbed_relations)
                ),
                p3_hypothesis_binding_count=len(bound_hypotheses),
                p3_hypothesis_binding_impacted_count=len(
                    bound_hypotheses & impacted_hypotheses
                ),
            )
        )
    return rows


def _corrupt_context(claim: dict) -> dict:
    changed = {**claim, "context": {**claim["context"]}}
    changed["context"].update(
        {
            "species": "[CORRUPTED_CONTEXT]",
            "model_system": "[CORRUPTED_CONTEXT]",
            "population": "[CORRUPTED_CONTEXT]",
            "anatomical_region": "[CORRUPTED_CONTEXT]",
            "cell_type": "[CORRUPTED_CONTEXT]",
        }
    )
    return changed


def _scenario(
    kind: PerturbationKind,
    fraction: float,
    selected: set[str],
    literature_claims: list[dict],
    literature_relations: list[dict],
    structured_claims: list[dict],
    structured_relations: list[dict],
    dependency_ids: set[str],
    p3_bindings: dict[str, set[str]],
) -> tuple[RobustnessScenario, list[TargetPropagationRecord]]:
    if kind == PerturbationKind.DEPENDENCY_EDGE_REMOVAL:
        layer = GraphLayer.STRUCTURED_DEPENDENCY
        baseline_claims = structured_claims
        baseline_relations = structured_relations
        perturbed_claims = structured_claims
        perturbed_relations = [
            relation for relation in structured_relations if relation["id"] not in selected
        ]
        polarity_changed: set[str] = set()
        context_changed: set[str] = set()
        target_getter = _structured_target
        eligible_count = len(dependency_ids)
    else:
        layer = GraphLayer.PROVISIONAL_LITERATURE
        baseline_claims = literature_claims
        baseline_relations = literature_relations
        target_getter = _literature_target
        eligible_count = len(literature_claims)
        polarity_changed = set()
        context_changed = set()
        if kind == PerturbationKind.CLAIM_DROP:
            perturbed_claims = [claim for claim in literature_claims if claim["id"] not in selected]
            remaining = {claim["id"] for claim in perturbed_claims}
            perturbed_relations = [
                relation
                for relation in literature_relations
                if relation["source_claim_id"] in remaining
                and relation["target_claim_id"] in remaining
            ]
        elif kind == PerturbationKind.POLARITY_FLIP:
            polarity_changed = selected
            perturbed_claims = [
                {**claim, "polarity": POLARITY_FLIP[claim["polarity"]]}
                if claim["id"] in selected
                else claim
                for claim in literature_claims
            ]
            perturbed_relations = literature_relations
        else:
            context_changed = selected
            perturbed_claims = [
                _corrupt_context(claim) if claim["id"] in selected else claim
                for claim in literature_claims
            ]
            perturbed_relations = literature_relations

    scenario_id = stable_id("robustness-scenario", f"{kind.value}-{fraction:.2f}")
    target_rows = _target_records(
        scenario_id,
        baseline_claims,
        perturbed_claims,
        baseline_relations,
        perturbed_relations,
        target_getter,
        polarity_changed,
        context_changed,
        p3_bindings if layer == GraphLayer.PROVISIONAL_LITERATURE else {},
    )
    baseline_ids = {claim["id"] for claim in baseline_claims}
    perturbed_ids = {claim["id"] for claim in perturbed_claims}
    baseline_components, _ = _components(baseline_ids, baseline_relations)
    perturbed_components, largest_fraction = _components(
        perturbed_ids, perturbed_relations
    )
    baseline_dependency_count = sum(
        relation["relation_type"] in DEPENDENCY_RELATIONS
        for relation in baseline_relations
    )
    perturbed_dependency_count = sum(
        relation["relation_type"] in DEPENDENCY_RELATIONS
        for relation in perturbed_relations
    )
    modified_claims = polarity_changed | context_changed
    stale_relation_count = sum(
        relation["source_claim_id"] in modified_claims
        or relation["target_claim_id"] in modified_claims
        for relation in perturbed_relations
    )
    relation_semantic_agreement = (
        1 - stale_relation_count / len(perturbed_relations)
        if perturbed_relations
        else 1.0
    )
    claim_retention = len(perturbed_claims) / len(baseline_claims)
    relation_retention = (
        len(perturbed_relations) / len(baseline_relations)
        if baseline_relations
        else 1.0
    )
    dependency_retention = (
        perturbed_dependency_count / baseline_dependency_count
        if baseline_dependency_count
        else 1.0
    )
    polarity_agreement = 1 - len(polarity_changed) / len(baseline_claims)
    context_agreement = 1 - len(context_changed) / len(baseline_claims)
    changed_target_count = sum(row.signature_changed for row in target_rows)
    changed_target_fraction = changed_target_count / len(target_rows)
    realized_fraction = len(selected) / eligible_count
    p3_bound = set().union(*p3_bindings.values()) if p3_bindings else set()
    directly_impacted = selected & p3_bound if layer == GraphLayer.PROVISIONAL_LITERATURE else set()
    changed_hypotheses = sum(
        bool(claim_ids & directly_impacted) for claim_ids in p3_bindings.values()
    )
    signature_similarity = sum(
        (
            claim_retention,
            relation_retention,
            dependency_retention,
            polarity_agreement,
            context_agreement,
        )
    ) / 5
    return (
        RobustnessScenario(
            id=scenario_id,
            perturbation_kind=kind,
            graph_layer=layer,
            requested_fraction=fraction,
            eligible_record_count=eligible_count,
            perturbed_record_count=len(selected),
            realized_fraction=realized_fraction,
            baseline_claim_count=len(baseline_claims),
            perturbed_claim_count=len(perturbed_claims),
            claim_retention=claim_retention,
            baseline_relation_count=len(baseline_relations),
            perturbed_relation_count=len(perturbed_relations),
            relation_retention=relation_retention,
            baseline_dependency_edge_count=baseline_dependency_count,
            perturbed_dependency_edge_count=perturbed_dependency_count,
            dependency_edge_retention=dependency_retention,
            polarity_agreement=polarity_agreement,
            context_agreement=context_agreement,
            stale_relation_count=stale_relation_count,
            relation_endpoint_semantic_agreement=relation_semantic_agreement,
            baseline_component_count=baseline_components,
            perturbed_component_count=perturbed_components,
            largest_component_fraction=largest_fraction,
            target_count=len(target_rows),
            target_signature_changed_count=changed_target_count,
            target_signature_changed_fraction=changed_target_fraction,
            propagation_ratio=changed_target_fraction / realized_fraction,
            p3_bound_claim_impacted_count=len(directly_impacted),
            p3_bound_claim_impact_fraction=(
                len(directly_impacted) / len(p3_bound) if p3_bound else 0.0
            ),
            p3_hypothesis_signature_changed_count=changed_hypotheses,
            graph_signature_similarity=signature_similarity,
        ),
        target_rows,
    )


def build_robustness_records() -> tuple[
    list[PerturbationLedgerRecord],
    list[RobustnessScenario],
    list[TargetPropagationRecord],
    RobustnessQuality,
]:
    literature = load_default_literature_store().snapshot
    structured = load_default_claim_graph_store().snapshot
    portfolio = load_default_ideation_store().portfolio
    literature_claims = [row.model_dump(mode="json") for row in literature.provisional_gold_claims]
    literature_relations = [
        row.model_dump(mode="json") for row in literature.provisional_gold_relations
    ]
    structured_claims = [row.model_dump(mode="json") for row in structured.claims]
    structured_relations = [row.model_dump(mode="json") for row in structured.relations]
    dependency_relations = [
        row
        for row in structured_relations
        if row["relation_type"] in DEPENDENCY_RELATIONS
    ]
    dependency_ids = {row["id"] for row in dependency_relations}
    p3_bindings = {
        hypothesis.id: set(hypothesis.mechanism_claim_ids)
        for hypothesis in portfolio.hypotheses
    }
    literature_ids = [row["id"] for row in literature_claims]
    ledger = []
    scenarios = []
    target_rows = []
    selected_by_kind: dict[PerturbationKind, list[set[str]]] = defaultdict(list)
    for kind in PerturbationKind:
        eligible_ids = (
            list(dependency_ids)
            if kind == PerturbationKind.DEPENDENCY_EDGE_REMOVAL
            else literature_ids
        )
        ordered = _stable_order(eligible_ids, kind)
        layer = (
            GraphLayer.STRUCTURED_DEPENDENCY
            if kind == PerturbationKind.DEPENDENCY_EDGE_REMOVAL
            else GraphLayer.PROVISIONAL_LITERATURE
        )
        for fraction in LEVELS:
            selected = set(ordered[: _selected_count(len(ordered), fraction)])
            selected_by_kind[kind].append(selected)
            ledger.append(
                PerturbationLedgerRecord(
                    id=stable_id("perturbation-ledger", f"{kind.value}-{fraction:.2f}"),
                    perturbation_kind=kind,
                    graph_layer=layer,
                    requested_fraction=fraction,
                    eligible_record_count=len(ordered),
                    selected_record_count=len(selected),
                    selected_record_ids=sorted(selected),
                )
            )
            scenario, scenario_targets = _scenario(
                kind,
                fraction,
                selected,
                literature_claims,
                literature_relations,
                structured_claims,
                structured_relations,
                dependency_ids,
                p3_bindings,
            )
            scenarios.append(scenario)
            target_rows.extend(scenario_targets)
    nested = all(
        all(rows[index] < rows[index + 1] for index in range(len(rows) - 1))
        for rows in selected_by_kind.values()
    )
    p3_bound = set().union(*p3_bindings.values())
    quality = RobustnessQuality(
        target_propagation_record_count=len(target_rows),
        provisional_literature_claim_count=len(literature_claims),
        provisional_literature_relation_count=len(literature_relations),
        structured_claim_count=len(structured_claims),
        structured_relation_count=len(structured_relations),
        structured_dependency_edge_count=len(dependency_relations),
        p3_bound_literature_claim_count=len(p3_bound),
        nested_selection_invariant_passed=nested,
        maximum_p3_bound_claim_impact_count=max(
            row.p3_bound_claim_impacted_count for row in scenarios
        ),
        maximum_p3_hypothesis_signature_changed_count=max(
            row.p3_hypothesis_signature_changed_count for row in scenarios
        ),
        minimum_graph_signature_similarity=min(
            row.graph_signature_similarity for row in scenarios
        ),
        engineering_gate_passed=(
            len(ledger) == 16
            and len(scenarios) == 16
            and len(literature_claims) == 150
            and len(dependency_relations) == 86
            and len(p3_bound) == 21
            and nested
            and all(row.outcome_field_used_count == 0 for row in scenarios)
            and all(row.model_refit_count == 0 for row in scenarios)
        ),
        blocking_limitations=[
            "The literature layer is provisional single-annotator data, not final human gold.",
            "Synthetic corruption measures structural and binding sensitivity, not scientific correctness.",
            "P3 binding impact is a provenance-signature change; no hypothesis score or outcome model is recomputed.",
            "Dependency-edge removal uses structured same-study edges and does not simulate every real evidence dependency.",
            "This experiment cannot unlock C1, C2, or C4 scientific claims and produces no clinical metric.",
        ],
    )
    return ledger, scenarios, target_rows, quality


def render_robustness_report(snapshot: RobustnessSnapshot) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P6.1 claim-graph robustness",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Scenarios: {q.scenario_count}",
            f"- Provisional literature claims: {q.provisional_literature_claim_count}",
            f"- Structured dependency edges: {q.structured_dependency_edge_count}",
            f"- P3-bound claims: {q.p3_bound_literature_claim_count}",
            f"- Maximum impacted P3-bound claims: {q.maximum_p3_bound_claim_impact_count}",
            f"- Minimum graph signature similarity: {q.minimum_graph_signature_similarity:.4f}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def _source_checksums() -> dict[str, str]:
    paths = (
        default_claim_graph_manifest_path(),
        default_literature_manifest_path(),
        default_ideation_manifest_path(),
        default_evaluation_manifest_path(),
    )
    return {path.name: file_sha256(path) for path in paths}


def write_robustness_artifacts(output_dir: Path) -> tuple[RobustnessSnapshot, RobustnessManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger, scenarios, target_rows, quality = build_robustness_records()
    ledger_path = output_dir / "p6_1_perturbation_ledger.jsonl.gz"
    scenario_path = output_dir / "p6_1_robustness_scenarios.jsonl.gz"
    target_path = output_dir / "p6_1_target_propagation.jsonl.gz"
    _write_jsonl_gzip(ledger_path, [row.model_dump(mode="json") for row in ledger])
    _write_jsonl_gzip(scenario_path, [row.model_dump(mode="json") for row in scenarios])
    _write_jsonl_gzip(target_path, [row.model_dump(mode="json") for row in target_rows])
    snapshot = RobustnessSnapshot(
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
            "MODEL-ONLY STRUCTURAL ROBUSTNESS. Synthetic graph perturbations do not "
            "validate claims, clinical outcomes, calibration, C1, or C4."
        ),
    )
    snapshot_path = output_dir / "p6_1_robustness_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p6_1_robustness_report.md").write_text(
        render_robustness_report(snapshot), encoding="utf-8"
    )
    manifest = RobustnessManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        ledger_path=ledger_path.name,
        ledger_sha256=file_sha256(ledger_path),
        scenario_path=scenario_path.name,
        scenario_sha256=file_sha256(scenario_path),
        target_propagation_path=target_path.name,
        target_propagation_sha256=file_sha256(target_path),
        target_propagation_record_count=len(target_rows),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p6_1_robustness_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class RobustnessStore:
    def __init__(self, snapshot: RobustnessSnapshot, manifest: RobustnessManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "RobustnessStore":
        return cls(
            RobustnessSnapshot.model_validate(_load_json(snapshot_path)),
            RobustnessManifest.model_validate(_load_json(manifest_path)),
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

    def scenarios(self, kind: str | None = None) -> list[dict]:
        return self._sample(
            self.manifest.scenario_path,
            self.manifest.scenario_record_count,
            None if kind is None else lambda row: row["perturbation_kind"] == kind,
        )

    def ledger(self, kind: str | None = None) -> list[dict]:
        return self._sample(
            self.manifest.ledger_path,
            self.manifest.ledger_record_count,
            None if kind is None else lambda row: row["perturbation_kind"] == kind,
        )

    def target_propagation(self, scenario_id: str | None = None, limit: int = 100) -> list[dict]:
        return self._sample(
            self.manifest.target_propagation_path,
            limit,
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


def load_default_robustness_store() -> RobustnessStore:
    return RobustnessStore.load(default_robustness_snapshot_path(), default_robustness_manifest_path())
