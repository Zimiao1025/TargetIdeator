"""Strict contracts for the P3 model-silver development slice."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.claims.models import ClaimPolarity
from targetideator.contracts.models import (
    CurationStatus,
    EntityRef,
    InterventionDirection,
    Modality,
    StableId,
)
from targetideator.evidence.models import CanonicalEntity, StrictModel
from targetideator.literature.models import ClaimDirection, LiteratureClaimTheme
from targetideator.literature.review_models import (
    EvidenceRole,
    ReviewDisposition,
    TargetGrounding,
)


class SilverSelectionAction(StrEnum):
    RETAIN_ORIGINAL = "retain_original"
    USE_EXISTING_REPLACEMENT = "use_existing_replacement"
    EXCLUDE = "exclude"


class ModelSilverDecision(StrictModel):
    task_id: StableId
    original_claim_id: StableId
    disposition: ReviewDisposition
    selection_action: SilverSelectionAction
    selected_claim_id: StableId | None = None
    target_grounding: TargetGrounding
    evidence_role: EvidenceRole
    theme: LiteratureClaimTheme | None = None
    polarity: ClaimPolarity | None = None
    direction: ClaimDirection | None = None
    rationale: str = Field(min_length=1)
    provenance_sources: list[str] = Field(min_length=1)
    verification_status: Literal["model_only_unverified"] = "model_only_unverified"

    @model_validator(mode="after")
    def selection_matches_disposition(self) -> "ModelSilverDecision":
        selected = self.selected_claim_id is not None
        if self.selection_action == SilverSelectionAction.EXCLUDE and selected:
            raise ValueError("excluded silver decisions cannot select a claim")
        if self.selection_action != SilverSelectionAction.EXCLUDE and not selected:
            raise ValueError("retained silver decisions require a selected claim")
        if self.disposition == ReviewDisposition.REJECT and selected:
            raise ValueError("rejected silver decisions cannot select a claim")
        labels = (self.theme, self.polarity, self.direction)
        if selected and any(item is None for item in labels):
            raise ValueError("selected silver claims require complete semantic labels")
        return self


class ModelSilverLiteratureLayer(StrictModel):
    schema_version: Literal["2.2-model-silver.1"] = "2.2-model-silver.1"
    id: StableId
    created_at: datetime
    source_snapshot_id: StableId
    source_review_batch_id: StableId
    source_comment_resolution_id: StableId
    decisions: list[ModelSilverDecision] = Field(min_length=1)
    selected_claim_ids: list[StableId]
    selected_claim_count: int = Field(ge=0)
    excluded_claim_count: int = Field(ge=0)
    human_review_count: Literal[0] = 0
    annotation_layer: Literal["model_adjudicated_silver"] = "model_adjudicated_silver"
    eligible_for_p3_development: Literal[True] = True
    eligible_for_scientific_validation: Literal[False] = False
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def counts_are_consistent(self) -> "ModelSilverLiteratureLayer":
        selected = [item.selected_claim_id for item in self.decisions if item.selected_claim_id]
        if selected != self.selected_claim_ids or len(selected) != len(set(selected)):
            raise ValueError("silver selected claim IDs must be ordered, unique, and decision-bound")
        if self.selected_claim_count != len(selected):
            raise ValueError("silver selected claim count mismatch")
        if self.excluded_claim_count != len(self.decisions) - len(selected):
            raise ValueError("silver excluded claim count mismatch")
        return self


class RecallRoute(StrEnum):
    HUMAN_GENETICS = "human_genetics"
    CLINICAL_DEVELOPMENT = "clinical_development"
    EXPRESSION_CONTEXT = "expression_context"
    LITERATURE_MECHANISM = "literature_mechanism"


class CandidateRouteSignal(StrictModel):
    id: StableId
    target: CanonicalEntity
    route: RecallRoute
    route_score: float = Field(ge=0, le=1)
    route_rank: int = Field(ge=1)
    evidence_ids: list[StableId] = Field(min_length=1)
    supporting_claim_ids: list[StableId] = Field(default_factory=list)
    counterevidence_claim_ids: list[StableId] = Field(default_factory=list)
    source_snapshot_ids: list[StableId] = Field(min_length=1)
    retrospective_valid: bool
    limitations: list[str] = Field(min_length=1)


class IdeationCandidate(StrictModel):
    id: StableId
    disease: EntityRef
    target: CanonicalEntity
    route_signals: list[CandidateRouteSignal] = Field(min_length=1)
    route_count: int = Field(ge=1)
    unranked: Literal[True] = True
    known_seed_panel_member: Literal[True] = True
    development_only: Literal[True] = True
    information_gaps: list[str]

    @model_validator(mode="after")
    def route_count_matches(self) -> "IdeationCandidate":
        routes = [item.route for item in self.route_signals]
        if len(routes) != len(set(routes)) or self.route_count != len(routes):
            raise ValueError("candidate route signals must be unique and count-matched")
        if any(item.target.identifier != self.target.identifier for item in self.route_signals):
            raise ValueError("candidate signal target mismatch")
        return self


class ComposedHypothesis(StrictModel):
    id: StableId
    template_source_hypothesis_id: StableId
    disease: EntityRef
    target: CanonicalEntity
    population: str = Field(min_length=1)
    cell_state: str = Field(min_length=1)
    proposed_direction: InterventionDirection
    proposed_modality: Modality
    mechanism_claim_ids: list[StableId] = Field(min_length=1)
    supporting_claim_ids: list[StableId]
    counterevidence_claim_ids: list[StableId]
    candidate_route_ids: list[StableId] = Field(min_length=1)
    information_gaps: list[str] = Field(min_length=1)
    evidence_layer: Literal["model_adjudicated_silver"] = "model_adjudicated_silver"
    verification_status: Literal["development_only_model_unverified"] = (
        "development_only_model_unverified"
    )
    curation_status: Literal[CurationStatus.AUTOMATED] = CurationStatus.AUTOMATED

    @model_validator(mode="after")
    def support_is_bound_to_mechanism(self) -> "ComposedHypothesis":
        mechanism = set(self.mechanism_claim_ids)
        if set(self.supporting_claim_ids) - mechanism:
            raise ValueError("supporting claims must be present in the mechanism chain")
        if set(self.counterevidence_claim_ids) - mechanism:
            raise ValueError("counterevidence claims must be present in the mechanism chain")
        return self


class IdeationQuality(StrictModel):
    fixed_seed_target_count: int = Field(ge=0)
    recalled_seed_target_count: int = Field(ge=0)
    fixed_seed_recall: float = Field(ge=0, le=1)
    candidate_count: int = Field(ge=0)
    hypothesis_count: int = Field(ge=0)
    route_candidate_counts: dict[RecallRoute, int]
    all_routes_nonzero: bool
    mechanism_claim_binding_coverage: float = Field(ge=0, le=1)
    post_cutoff_leakage_count: int = Field(ge=0)
    model_silver_claim_count: int = Field(ge=0)
    human_validated_claim_count: Literal[0] = 0
    minimum_portfolio_size_met: bool
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p3_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class IdeationPortfolio(StrictModel):
    schema_version: Literal["3.0-development.1"] = "3.0-development.1"
    id: StableId
    created_at: datetime
    as_of_date: date
    disease_brief_id: StableId
    source_snapshot_ids: list[StableId] = Field(min_length=1)
    silver_layer: ModelSilverLiteratureLayer
    route_signals: list[CandidateRouteSignal] = Field(min_length=1)
    candidates: list[IdeationCandidate] = Field(min_length=1)
    hypotheses: list[ComposedHypothesis] = Field(min_length=1)
    quality: IdeationQuality
    portfolio_ordering: Literal["target_label_then_template_id_not_a_scientific_rank"] = (
        "target_label_then_template_id_not_a_scientific_rank"
    )
    use_policy: Literal["engineering_and_hypothesis_development_only"] = (
        "engineering_and_hypothesis_development_only"
    )
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def portfolio_integrity(self) -> "IdeationPortfolio":
        candidate_targets = {item.target.identifier for item in self.candidates}
        if any(item.target.identifier not in candidate_targets for item in self.hypotheses):
            raise ValueError("hypothesis target is absent from candidate union")
        signal_ids = {item.id for item in self.route_signals}
        if any(
            route_id not in signal_ids
            for item in self.hypotheses
            for route_id in item.candidate_route_ids
        ):
            raise ValueError("hypothesis references a missing route signal")
        counts = Counter(item.route for item in self.route_signals)
        if self.quality.route_candidate_counts != dict(counts):
            raise ValueError("portfolio route counts differ from quality summary")
        if self.quality.candidate_count != len(self.candidates):
            raise ValueError("portfolio candidate count mismatch")
        if self.quality.hypothesis_count != len(self.hypotheses):
            raise ValueError("portfolio hypothesis count mismatch")
        return self


class IdeationManifest(StrictModel):
    schema_version: Literal["3.0-development.1"] = "3.0-development.1"
    portfolio_id: StableId
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    hypothesis_count: int = Field(ge=0)
    scientific_validation_gate_passed: Literal[False] = False
