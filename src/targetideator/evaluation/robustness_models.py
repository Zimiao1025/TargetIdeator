"""Contracts for P6.1 deterministic claim-graph robustness experiments."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class PerturbationKind(StrEnum):
    CLAIM_DROP = "claim_drop"
    POLARITY_FLIP = "polarity_flip"
    CONTEXT_CORRUPTION = "context_corruption"
    DEPENDENCY_EDGE_REMOVAL = "dependency_edge_removal"


class GraphLayer(StrEnum):
    PROVISIONAL_LITERATURE = "p2_2_provisional_literature_claim_layer"
    STRUCTURED_DEPENDENCY = "p2_1_structured_dependency_layer"


class PerturbationLedgerRecord(StrictModel):
    id: StableId
    perturbation_kind: PerturbationKind
    graph_layer: GraphLayer
    requested_fraction: Literal[0.01, 0.05, 0.1, 0.2]
    selection_seed: Literal[20261102] = 20261102
    selection_policy: Literal[
        "stable_sha256_order_nested_prefix"
    ] = "stable_sha256_order_nested_prefix"
    eligible_record_count: int = Field(gt=0)
    selected_record_count: int = Field(gt=0)
    selected_record_ids: list[StableId] = Field(min_length=1)


class RobustnessScenario(StrictModel):
    id: StableId
    perturbation_kind: PerturbationKind
    graph_layer: GraphLayer
    requested_fraction: Literal[0.01, 0.05, 0.1, 0.2]
    eligible_record_count: int = Field(gt=0)
    perturbed_record_count: int = Field(gt=0)
    realized_fraction: float = Field(gt=0, le=1)
    baseline_claim_count: int = Field(gt=0)
    perturbed_claim_count: int = Field(ge=0)
    claim_retention: float = Field(ge=0, le=1)
    baseline_relation_count: int = Field(ge=0)
    perturbed_relation_count: int = Field(ge=0)
    relation_retention: float = Field(ge=0, le=1)
    baseline_dependency_edge_count: int = Field(ge=0)
    perturbed_dependency_edge_count: int = Field(ge=0)
    dependency_edge_retention: float = Field(ge=0, le=1)
    polarity_agreement: float = Field(ge=0, le=1)
    context_agreement: float = Field(ge=0, le=1)
    stale_relation_count: int = Field(ge=0)
    relation_endpoint_semantic_agreement: float = Field(ge=0, le=1)
    baseline_component_count: int = Field(gt=0)
    perturbed_component_count: int = Field(ge=0)
    largest_component_fraction: float = Field(ge=0, le=1)
    target_count: int = Field(gt=0)
    target_signature_changed_count: int = Field(ge=0)
    target_signature_changed_fraction: float = Field(ge=0, le=1)
    propagation_ratio: float = Field(ge=0)
    p3_bound_claim_impacted_count: int = Field(ge=0)
    p3_bound_claim_impact_fraction: float = Field(ge=0, le=1)
    p3_hypothesis_signature_changed_count: int = Field(ge=0)
    graph_signature_similarity: float = Field(ge=0, le=1)
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0


class TargetPropagationRecord(StrictModel):
    id: StableId
    scenario_id: StableId
    target_id: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    baseline_claim_count: int = Field(ge=0)
    perturbed_claim_count: int = Field(ge=0)
    claim_retention: float = Field(ge=0, le=1)
    polarity_changed_claim_count: int = Field(ge=0)
    context_changed_claim_count: int = Field(ge=0)
    baseline_incident_relation_count: int = Field(ge=0)
    perturbed_incident_relation_count: int = Field(ge=0)
    signature_changed: bool
    p3_hypothesis_binding_count: int = Field(ge=0)
    p3_hypothesis_binding_impacted_count: int = Field(ge=0)


class RobustnessQuality(StrictModel):
    perturbation_kind_count: Literal[4] = 4
    severity_level_count: Literal[4] = 4
    scenario_count: Literal[16] = 16
    ledger_record_count: Literal[16] = 16
    target_propagation_record_count: int = Field(gt=0)
    provisional_literature_claim_count: int = Field(gt=0)
    provisional_literature_relation_count: int = Field(ge=0)
    structured_claim_count: int = Field(gt=0)
    structured_relation_count: int = Field(gt=0)
    structured_dependency_edge_count: int = Field(gt=0)
    p3_bound_literature_claim_count: int = Field(gt=0)
    nested_selection_invariant_passed: bool
    maximum_p3_bound_claim_impact_count: int = Field(ge=0)
    maximum_p3_hypothesis_signature_changed_count: int = Field(ge=0)
    minimum_graph_signature_similarity: float = Field(ge=0, le=1)
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    c2_scientific_claim_unlocked: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class RobustnessSnapshot(StrictModel):
    schema_version: Literal["6.1.0"] = "6.1.0"
    id: StableId
    created_at: datetime
    perturbation_policy: Literal[
        "fixed_nested_1_5_10_20_percent_stable_hash"
    ] = "fixed_nested_1_5_10_20_percent_stable_hash"
    evaluation_policy: Literal[
        "structure_and_binding_propagation_only_no_outcome_or_model_refit"
    ] = "structure_and_binding_propagation_only_no_outcome_or_model_refit"
    literature_layer_policy: Literal[
        "provisional_single_annotator_labels_not_final_gold"
    ] = "provisional_single_annotator_labels_not_final_gold"
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_path: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_propagation_path: str = Field(min_length=1)
    target_propagation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: RobustnessQuality
    warning: str = Field(min_length=1)


class RobustnessManifest(StrictModel):
    schema_version: Literal["6.1.0"] = "6.1.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=4)
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_record_count: Literal[16] = 16
    scenario_path: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_record_count: Literal[16] = 16
    target_propagation_path: str = Field(min_length=1)
    target_propagation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_propagation_record_count: int = Field(gt=0)
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
