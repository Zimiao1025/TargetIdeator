"""Strict contracts for the P5 uncalibrated development decision engine."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel
from targetideator.revision.models import RevisionStatus


class DecisionHeadName(StrEnum):
    CAUSAL_RELEVANCE = "causal_relevance"
    CORRECT_DIRECTION = "correct_direction"
    TRANSLATABLE_EFFICACY = "translatable_efficacy"
    MODALITY_FEASIBILITY = "modality_feasibility"
    SAFETY_WINDOW = "safety_window"


class FeatureEffect(StrEnum):
    INCREASES_READINESS = "increases_readiness"
    DECREASES_READINESS = "decreases_readiness"
    BLOCKS = "blocks"
    CONTEXT_ONLY = "context_only"


class HeadUncertainty(StrEnum):
    HIGH_UNCALIBRATED = "high_uncalibrated"
    UNBOUNDED_MISSING = "unbounded_missing"


class DecisionStatus(StrEnum):
    BLOCKED_UPSTREAM = "blocked_upstream"
    ABSTAIN_MISSING_REQUIRED_HEADS = "abstain_missing_required_heads"
    ELIGIBLE_UNRANKED = "eligible_unranked"


class ParetoStatus(StrEnum):
    EXCLUDED_UPSTREAM = "excluded_upstream"
    INCOMPARABLE_MISSING_HEADS = "incomparable_missing_heads"
    FRONTIER = "frontier"
    DOMINATED = "dominated"


FeatureValue = str | int | float | bool


class FeatureContribution(StrictModel):
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    value: FeatureValue
    effect: FeatureEffect
    source_ids: list[StableId]
    rationale: str = Field(min_length=1)


class DecisionHead(StrictModel):
    id: StableId
    hypothesis_id: StableId
    head_name: DecisionHeadName
    score: float | None = Field(default=None, ge=0, le=1)
    score_scale: Literal["ordinal_development_readiness_not_probability"] = (
        "ordinal_development_readiness_not_probability"
    )
    rule_id: str = Field(pattern=r"^p5\.[a-z_]+\.[a-z0-9_.-]+$")
    feature_contributions: list[FeatureContribution] = Field(min_length=1)
    evidence_claim_ids: list[StableId]
    route_evidence_ids: list[StableId]
    evidence_coverage: float = Field(ge=0, le=1)
    missing_requirements: list[str]
    abstained: bool
    uncertainty: HeadUncertainty
    calibration_status: Literal["not_calibrated_no_outcome_labels"] = (
        "not_calibrated_no_outcome_labels"
    )
    probability_interpretation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def missingness_is_not_imputed(self) -> "DecisionHead":
        if self.abstained != (self.score is None):
            raise ValueError("head score must be absent exactly when the head abstains")
        if self.abstained and not self.missing_requirements:
            raise ValueError("an abstaining head must state missing requirements")
        expected = (
            HeadUncertainty.UNBOUNDED_MISSING
            if self.abstained
            else HeadUncertainty.HIGH_UNCALIBRATED
        )
        if self.uncertainty != expected:
            raise ValueError("head uncertainty must reflect missingness and absent calibration")
        return self


class CandidateDecision(StrictModel):
    id: StableId
    hypothesis_id: StableId
    revision_candidate_id: StableId
    upstream_revision_status: RevisionStatus
    heads: list[DecisionHead] = Field(min_length=5, max_length=5)
    missing_required_heads: list[DecisionHeadName]
    decision_status: DecisionStatus
    abstention_reasons: list[str]
    weighted_utility: float | None = Field(default=None, ge=0, le=1)
    default_weights: dict[DecisionHeadName, float]
    pareto_status: ParetoStatus
    rank: Literal[None] = None
    not_ranked: Literal[True] = True
    eligible_for_scientific_decision: Literal[False] = False

    @model_validator(mode="after")
    def decision_integrity(self) -> "CandidateDecision":
        names = [item.head_name for item in self.heads]
        if names != list(DecisionHeadName):
            raise ValueError("candidate must contain all five heads in canonical order")
        if any(item.hypothesis_id != self.hypothesis_id for item in self.heads):
            raise ValueError("decision head hypothesis mismatch")
        missing = [item.head_name for item in self.heads if item.abstained]
        if self.missing_required_heads != missing:
            raise ValueError("candidate missing-head list differs from head outputs")
        if set(self.default_weights) != set(DecisionHeadName):
            raise ValueError("default utility weights must cover all heads")
        if abs(sum(self.default_weights.values()) - 1.0) > 1e-9:
            raise ValueError("default utility weights must sum to one")
        if self.decision_status == DecisionStatus.BLOCKED_UPSTREAM:
            if self.pareto_status != ParetoStatus.EXCLUDED_UPSTREAM:
                raise ValueError("upstream-blocked candidates must be excluded from Pareto analysis")
        elif self.missing_required_heads:
            if self.decision_status != DecisionStatus.ABSTAIN_MISSING_REQUIRED_HEADS:
                raise ValueError("missing heads must propagate to candidate abstention")
            if self.pareto_status != ParetoStatus.INCOMPARABLE_MISSING_HEADS:
                raise ValueError("missing-head candidates cannot enter a complete Pareto frontier")
        elif self.decision_status != DecisionStatus.ELIGIBLE_UNRANKED:
            raise ValueError("complete candidates must remain eligible and unranked")
        if self.weighted_utility is not None and (
            self.decision_status != DecisionStatus.ELIGIBLE_UNRANKED
        ):
            raise ValueError("utility cannot be computed for blocked or abstained candidates")
        if self.decision_status != DecisionStatus.ELIGIBLE_UNRANKED and not self.abstention_reasons:
            raise ValueError("blocked/abstained candidates require explicit reasons")
        return self


class CalibrationSummary(StrictModel):
    fitted: Literal[False] = False
    method: Literal["none"] = "none"
    outcome_label_count: Literal[0] = 0
    train_count: Literal[0] = 0
    validation_count: Literal[0] = 0
    test_count: Literal[0] = 0
    brier_score: Literal[None] = None
    expected_calibration_error: Literal[None] = None
    pr_auc: Literal[None] = None
    reason: Literal[
        "no_temporal_outcome_labels_do_not_fit_or_claim_calibration"
    ] = "no_temporal_outcome_labels_do_not_fit_or_claim_calibration"


class RiskCoverageSummary(StrictModel):
    available: Literal[False] = False
    aurc: Literal[None] = None
    selective_accuracy: dict[str, float] = Field(default_factory=dict)
    curve: list[dict[str, float]] = Field(default_factory=list)
    reason: Literal[
        "no_outcome_labels_risk_cannot_be_estimated"
    ] = "no_outcome_labels_risk_cannot_be_estimated"


class ParetoSummary(StrictModel):
    head_order: list[DecisionHeadName] = Field(min_length=5, max_length=5)
    fully_scorable_candidate_ids: list[StableId]
    frontier_candidate_ids: list[StableId]
    dominated_candidate_ids: list[StableId]
    incomparable_missing_head_candidate_ids: list[StableId]
    excluded_upstream_candidate_ids: list[StableId]
    default_weights: dict[DecisionHeadName, float]
    policy: Literal[
        "complete_heads_only_no_missing_value_imputation_no_forced_ranking"
    ] = "complete_heads_only_no_missing_value_imputation_no_forced_ranking"


class DecisionQuality(StrictModel):
    candidate_count: int = Field(ge=0)
    head_count: int = Field(ge=0)
    expected_head_count: int = Field(ge=0)
    head_counts: dict[DecisionHeadName, int]
    observed_head_score_count: int = Field(ge=0)
    abstained_head_count: int = Field(ge=0)
    head_score_coverage: float = Field(ge=0, le=1)
    upstream_blocked_candidate_count: int = Field(ge=0)
    missing_head_abstention_candidate_count: int = Field(ge=0)
    fully_scorable_candidate_count: int = Field(ge=0)
    pareto_frontier_candidate_count: int = Field(ge=0)
    probability_output_count: int = Field(ge=0)
    outcome_label_count: Literal[0] = 0
    post_cutoff_leakage_count: int = Field(ge=0)
    engineering_gate_passed: bool
    calibration_gate_passed: Literal[False] = False
    scientific_validation_gate_passed: Literal[False] = False
    formal_p5_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class DecisionSnapshot(StrictModel):
    schema_version: Literal["5.0-development.1"] = "5.0-development.1"
    id: StableId
    created_at: datetime
    as_of_date: date
    source_portfolio_id: StableId
    source_falsification_snapshot_id: StableId
    source_revision_snapshot_id: StableId
    source_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[CandidateDecision] = Field(min_length=1)
    calibration: CalibrationSummary
    risk_coverage: RiskCoverageSummary
    pareto: ParetoSummary
    quality: DecisionQuality
    use_policy: Literal[
        "engineering_only_uncalibrated_not_probability_not_scientific_ranking"
    ] = "engineering_only_uncalibrated_not_probability_not_scientific_ranking"
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def snapshot_integrity(self) -> "DecisionSnapshot":
        ids = [item.hypothesis_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("each hypothesis may have only one P5 decision")
        heads = [head for item in self.decisions for head in item.heads]
        if self.quality.candidate_count != len(self.decisions):
            raise ValueError("P5 candidate count mismatch")
        if self.quality.head_count != len(heads):
            raise ValueError("P5 head count mismatch")
        if self.quality.head_counts != dict(Counter(item.head_name for item in heads)):
            raise ValueError("P5 head counts mismatch")
        fully_scorable = [
            item.id
            for item in self.decisions
            if item.decision_status == DecisionStatus.ELIGIBLE_UNRANKED
        ]
        if self.pareto.fully_scorable_candidate_ids != fully_scorable:
            raise ValueError("Pareto complete-candidate set mismatch")
        if self.quality.probability_output_count != 0:
            raise ValueError("development scores must never be counted as probabilities")
        return self


class DecisionManifest(StrictModel):
    schema_version: Literal["5.0-development.1"] = "5.0-development.1"
    snapshot_id: StableId
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=1)
    candidate_count: int = Field(ge=0)
    head_count: int = Field(ge=0)
    calibration_gate_passed: Literal[False] = False
    scientific_validation_gate_passed: Literal[False] = False
