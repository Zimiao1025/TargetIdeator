"""Strict P2.1 contracts for deterministic, temporal epistemic claims."""

from __future__ import annotations

from collections import Counter
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from targetideator.contracts.models import StableId
from targetideator.evidence.models import CanonicalEntity, StrictModel


class ClaimKind(StrEnum):
    SOURCE_EVIDENCE_FACT = "source_evidence_fact"
    CLINICAL_DEVELOPMENT_ASSERTION = "clinical_development_assertion"
    TRIAL_REGISTRY_STATE = "trial_registry_state"


class ClaimPolarity(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    QUALIFIES = "qualifies"
    NEUTRAL = "neutral"


class ClaimRelationType(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    QUALIFIES = "qualifies"
    REPLICATES = "replicates"
    DERIVED_FROM = "derived_from"
    SAME_STUDY_AS = "same_study_as"
    SAME_COHORT_AS = "same_cohort_as"
    SUPERSEDES = "supersedes"


class ClaimObject(StrictModel):
    entity: CanonicalEntity | None = None
    literal: str | None = None

    @model_validator(mode="after")
    def exactly_one_value(self) -> "ClaimObject":
        if (self.entity is None) == (self.literal is None):
            raise ValueError("claim object requires exactly one entity or literal")
        return self


class StructuredClaimContext(StrictModel):
    species: Literal["human"] = "human"
    disease: CanonicalEntity | None = None
    target: CanonicalEntity | None = None
    drug: CanonicalEntity | None = None
    trial: CanonicalEntity
    population: str = Field(min_length=1)
    anatomical_region: str = Field(min_length=1)
    cell_type: str = Field(min_length=1)
    model_system: str = Field(min_length=1)
    clinical_phase: float | None = Field(default=None, ge=0, le=4)
    clinical_status: str | None = None
    trial_phase: str | None = None
    trial_status: str | None = None
    trial_last_update_posted_date: date | None = None
    outcome_scope: str = Field(min_length=1)


class ClaimProvenance(StrictModel):
    mode: Literal["structured_fields"] = "structured_fields"
    source_name: Literal["Open Targets ChEMBL evidence", "AACT studies"]
    source_record_id: str = Field(min_length=1)
    source_observation_id: StableId
    source_snapshot_id: StableId
    available_on: date
    source_url: HttpUrl
    raw_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transform_version: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    field_map: dict[str, str] = Field(min_length=1)
    verbatim_span: None = None


class EpistemicClaim(StrictModel):
    id: StableId
    assertion_key: StableId
    kind: ClaimKind
    subject: CanonicalEntity
    predicate: str = Field(min_length=1)
    object: ClaimObject
    polarity: ClaimPolarity
    direction: Literal["unknown"] = "unknown"
    scope: Literal["clinical_development", "registry_state"]
    context: StructuredClaimContext
    observed_in: str = Field(min_length=1)
    available_on: date
    effect_size: None = None
    effect_size_missing_reason: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)
    interpretation_boundary: str = Field(min_length=1)
    curation_status: Literal["automated_unreviewed"] = "automated_unreviewed"
    provenance: ClaimProvenance

    @model_validator(mode="after")
    def dates_and_scope_are_consistent(self) -> "EpistemicClaim":
        if self.available_on != self.provenance.available_on:
            raise ValueError("claim and provenance availability dates differ")
        if self.kind == ClaimKind.TRIAL_REGISTRY_STATE and self.scope != "registry_state":
            raise ValueError("trial state claims must use registry_state scope")
        if self.kind != ClaimKind.TRIAL_REGISTRY_STATE and self.scope != "clinical_development":
            raise ValueError("ChEMBL-derived claims must use clinical_development scope")
        return self


class ClaimRelation(StrictModel):
    id: StableId
    source_claim_id: StableId
    target_claim_id: StableId
    relation_type: ClaimRelationType
    available_on: date
    evidence_family_id: StableId
    notes: str = Field(min_length=1)


class EvidenceFamily(StrictModel):
    id: StableId
    dependency_key: str = Field(pattern=r"^NCT\d{8}$")
    trial: CanonicalEntity
    member_claim_ids: list[StableId] = Field(min_length=1)
    independence_unit: Literal["registered_trial"] = "registered_trial"
    correction_rationale: str = Field(min_length=1)


class ClaimGraphSnapshot(StrictModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    id: StableId
    source_clinical_snapshot_id: StableId
    source_clinical_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    converter_version: str = Field(min_length=1)
    claims: list[EpistemicClaim]
    relations: list[ClaimRelation]
    evidence_families: list[EvidenceFamily]

    @model_validator(mode="after")
    def graph_integrity(self) -> "ClaimGraphSnapshot":
        claim_ids = [item.id for item in self.claims]
        relation_ids = [item.id for item in self.relations]
        family_ids = [item.id for item in self.evidence_families]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim observation IDs must be unique")
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("claim relation IDs must be unique")
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("evidence family IDs must be unique")
        known_claims = set(claim_ids)
        known_families = set(family_ids)
        for relation in self.relations:
            if relation.source_claim_id not in known_claims or relation.target_claim_id not in known_claims:
                raise ValueError(f"relation {relation.id} references a missing claim")
            if relation.source_claim_id == relation.target_claim_id:
                raise ValueError(f"relation {relation.id} cannot be a self edge")
            if relation.evidence_family_id not in known_families:
                raise ValueError(f"relation {relation.id} references a missing evidence family")
        memberships = Counter(
            claim_id for family in self.evidence_families for claim_id in family.member_claim_ids
        )
        if set(memberships) != known_claims or any(value != 1 for value in memberships.values()):
            raise ValueError("every claim must belong to exactly one evidence family")
        for family in self.evidence_families:
            if family.trial.identifier != family.dependency_key:
                raise ValueError(f"evidence family {family.id} has inconsistent trial key")
        return self


class ClaimGraphRawArtifact(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClaimGraphManifest(StrictModel):
    schema_version: Literal["2.1.0"] = "2.1.0"
    snapshot_id: StableId
    source_artifact: ClaimGraphRawArtifact
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    converter_version: str = Field(min_length=1)
    claim_count: int = Field(ge=0)
    relation_count: int = Field(ge=0)
    evidence_family_count: int = Field(ge=0)


class ClaimGraphQueryResult(StrictModel):
    snapshot_id: StableId
    disease_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    as_of_date: date
    selected_chembl_release: str | None
    selected_aact_snapshot: str | None
    claims: list[EpistemicClaim]
    relations: list[ClaimRelation]
    evidence_families: list[EvidenceFamily]
    naive_claim_count: int = Field(ge=0)
    independent_evidence_count: int = Field(ge=0)
    dependency_correction_ratio: float = Field(ge=0, le=1)
    post_cutoff_leakage_count: int = Field(ge=0)
    retrospective_valid: bool
    warning: str = Field(min_length=1)


class ClaimChange(StrictModel):
    assertion_key: StableId
    earlier_claim_id: StableId
    later_claim_id: StableId
    changed_fields: list[str] = Field(min_length=1)


class ClaimGraphDiff(StrictModel):
    earlier_date: date
    later_date: date
    added_assertion_keys: list[StableId]
    removed_assertion_keys: list[StableId]
    changed_claims: list[ClaimChange]
