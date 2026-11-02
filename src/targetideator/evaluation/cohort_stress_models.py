"""Contracts for P6.2 duplicate-cohort dependency stress tests."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel


class CohortInjectionLedgerRecord(StrictModel):
    id: StableId
    requested_fraction: Literal[0.01, 0.05, 0.1, 0.2]
    selection_seed: Literal[20261103] = 20261103
    selection_policy: Literal[
        "stable_sha256_order_nested_family_prefix"
    ] = "stable_sha256_order_nested_family_prefix"
    eligible_family_count: Literal[43] = 43
    selected_family_count: int = Field(gt=0)
    selected_family_ids: list[StableId] = Field(min_length=1)
    selected_dependency_keys: list[str] = Field(min_length=1)
    injected_bundle_count: int = Field(gt=0)
    injected_claim_record_count: int = Field(gt=0)
    injected_identity_policy: Literal[
        "new_claim_and_assertion_identity_preserved_evidence_family_lineage"
    ] = "new_claim_and_assertion_identity_preserved_evidence_family_lineage"


class CohortInjectionScenario(StrictModel):
    id: StableId
    requested_fraction: Literal[0.01, 0.05, 0.1, 0.2]
    selected_family_count: int = Field(gt=0)
    baseline_claim_record_count: Literal[129] = 129
    injected_claim_record_count: int = Field(gt=0)
    naive_claim_record_count: int = Field(gt=129)
    naive_claim_inflation_fraction: float = Field(gt=0)
    baseline_independent_family_count: Literal[43] = 43
    family_blind_independent_count: int = Field(gt=43)
    family_blind_inflation_fraction: float = Field(gt=0)
    dependency_corrected_independent_count: Literal[43] = 43
    dependency_corrected_inflation_fraction: Literal[0.0] = 0.0
    false_independent_units_prevented: int = Field(gt=0)
    lineage_stripped_failure_exposed_count: int = Field(gt=0)
    target_naive_count_changed_count: int = Field(gt=0)
    target_corrected_count_changed_count: Literal[0] = 0
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0


class CohortTargetPropagationRecord(StrictModel):
    id: StableId
    scenario_id: StableId
    target_id: str = Field(min_length=1)
    baseline_claim_record_count: int = Field(gt=0)
    baseline_independent_family_count: int = Field(gt=0)
    selected_family_count: int = Field(ge=0)
    injected_claim_record_count: int = Field(ge=0)
    naive_claim_record_count: int = Field(gt=0)
    family_blind_independent_count: int = Field(gt=0)
    dependency_corrected_independent_count: int = Field(gt=0)
    dependency_corrected_count_changed: Literal[False] = False


class CohortStressQuality(StrictModel):
    severity_level_count: Literal[4] = 4
    scenario_count: Literal[4] = 4
    ledger_record_count: Literal[4] = 4
    target_propagation_record_count: Literal[8] = 8
    baseline_claim_record_count: Literal[129] = 129
    baseline_independent_family_count: Literal[43] = 43
    baseline_target_count: Literal[2] = 2
    nested_selection_invariant_passed: bool
    active_family_bundle_size_uniform: bool
    active_family_bundle_size: Literal[3] = 3
    maximum_naive_claim_inflation_fraction: float = Field(gt=0)
    maximum_family_blind_inflation_fraction: float = Field(gt=0)
    maximum_dependency_corrected_inflation_fraction: Literal[0.0] = 0.0
    dependency_correction_invariant_passed: bool
    lineage_stripped_negative_control_passed: bool
    outcome_field_used_count: Literal[0] = 0
    model_refit_count: Literal[0] = 0
    clinical_metric_count: Literal[0] = 0
    c1_status_changed: Literal[False] = False
    c4_status_changed: Literal[False] = False
    c2_scientific_claim_unlocked: Literal[False] = False
    c3_scientific_claim_unlocked: Literal[False] = False
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p6_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class CohortStressSnapshot(StrictModel):
    schema_version: Literal["6.2.0"] = "6.2.0"
    id: StableId
    created_at: datetime
    as_of_date: Literal["2025-09-17"] = "2025-09-17"
    injection_policy: Literal[
        "nested_family_selection_new_claim_identity_preserved_cohort_lineage"
    ] = "nested_family_selection_new_claim_identity_preserved_cohort_lineage"
    evaluation_policy: Literal[
        "naive_vs_family_blind_vs_dependency_corrected_counts_only"
    ] = "naive_vs_family_blind_vs_dependency_corrected_counts_only"
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_path: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_propagation_path: str = Field(min_length=1)
    target_propagation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: CohortStressQuality
    warning: str = Field(min_length=1)


class CohortStressManifest(StrictModel):
    schema_version: Literal["6.2.0"] = "6.2.0"
    snapshot_id: StableId
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=2)
    ledger_path: str = Field(min_length=1)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_record_count: Literal[4] = 4
    scenario_path: str = Field(min_length=1)
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_record_count: Literal[4] = 4
    target_propagation_path: str = Field(min_length=1)
    target_propagation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_propagation_record_count: Literal[8] = 8
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
