"""Strict contracts for the P4 fixed-taxonomy falsification slice."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.contracts.models import StableId, Verdict
from targetideator.evidence.models import StrictModel


class FailureTaxonomy(StrEnum):
    CAUSAL = "causal"
    DIRECTION = "direction"
    TRANSLATION = "translation"
    SAFETY = "safety"


class FalsifiablePrediction(StrictModel):
    statement: str = Field(min_length=1)
    required_observation: str = Field(min_length=1)
    refutation_condition: str = Field(min_length=1)
    assay_boundary: str = Field(min_length=1)


class CriticAssessment(StrictModel):
    id: StableId
    hypothesis_id: StableId
    critic_type: FailureTaxonomy
    strongest_counter_hypothesis: str = Field(min_length=1)
    fatal_assumption: str = Field(min_length=1)
    evidence_claim_ids: list[StableId]
    counterevidence_claim_ids: list[StableId]
    route_evidence_ids: list[StableId]
    evidence_gaps: list[str]
    falsifiable_prediction: FalsifiablePrediction
    verdict: Verdict
    rationale: str = Field(min_length=1)
    rule_id: str = Field(pattern=r"^p4\.[a-z]+\.[a-z0-9_.-]+$")
    proposer_trace_used: Literal[False] = False
    review_status: Literal["deterministic_model_only_unverified"] = (
        "deterministic_model_only_unverified"
    )

    @model_validator(mode="after")
    def assessment_integrity(self) -> "CriticAssessment":
        if self.verdict == Verdict.UNASSESSED:
            raise ValueError("a P4 critic must emit a substantive or abstaining verdict")
        if set(self.counterevidence_claim_ids) - set(self.evidence_claim_ids):
            raise ValueError("counterevidence must be included in cited evidence claims")
        if self.verdict in {Verdict.ABSTAIN, Verdict.REVISE} and not self.evidence_gaps:
            raise ValueError("abstain/revise assessments must make evidence gaps explicit")
        return self


class FalsificationResult(StrictModel):
    id: StableId
    hypothesis_id: StableId
    assessments: list[CriticAssessment] = Field(min_length=4, max_length=4)
    combined_verdict: Verdict
    combined_rationale: str = Field(min_length=1)
    binding_critic_types: list[FailureTaxonomy] = Field(min_length=1)
    revision_fields: list[str]
    original_hypothesis_preserved: Literal[True] = True

    @model_validator(mode="after")
    def four_fixed_critics_are_present(self) -> "FalsificationResult":
        critic_types = [item.critic_type for item in self.assessments]
        if len(set(critic_types)) != 4 or set(critic_types) != set(FailureTaxonomy):
            raise ValueError("each hypothesis requires exactly the four fixed critics")
        if any(item.hypothesis_id != self.hypothesis_id for item in self.assessments):
            raise ValueError("critic assessment hypothesis mismatch")
        if self.combined_verdict == Verdict.UNASSESSED:
            raise ValueError("combined verdict cannot be unassessed")
        if set(self.binding_critic_types) - set(critic_types):
            raise ValueError("binding critics must be present in the assessment set")
        return self


class FalsificationQuality(StrictModel):
    hypothesis_count: int = Field(ge=0)
    critic_assessment_count: int = Field(ge=0)
    expected_critic_assessment_count: int = Field(ge=0)
    taxonomy_counts: dict[FailureTaxonomy, int]
    verdict_counts: dict[Verdict, int]
    combined_verdict_counts: dict[Verdict, int]
    taxonomy_coverage: float = Field(ge=0, le=1)
    claim_reference_integrity: float = Field(ge=0, le=1)
    fixed_rule_coverage: float = Field(ge=0, le=1)
    proposer_trace_leakage_count: int = Field(ge=0)
    human_review_count: Literal[0] = 0
    engineering_gate_passed: bool
    scientific_validation_gate_passed: Literal[False] = False
    formal_p4_gate_passed: Literal[False] = False
    blocking_limitations: list[str] = Field(min_length=1)


class FalsificationSnapshot(StrictModel):
    schema_version: Literal["4.0-development.1"] = "4.0-development.1"
    id: StableId
    created_at: datetime
    as_of_date: date
    source_portfolio_id: StableId
    source_portfolio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy: list[FailureTaxonomy] = Field(min_length=4, max_length=4)
    merge_policy: Literal[
        "reject_then_two_abstentions_then_revise_then_single_abstention_then_survive"
    ] = "reject_then_two_abstentions_then_revise_then_single_abstention_then_survive"
    results: list[FalsificationResult] = Field(min_length=1)
    quality: FalsificationQuality
    use_policy: Literal["engineering_and_hypothesis_development_only"] = (
        "engineering_and_hypothesis_development_only"
    )
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def snapshot_integrity(self) -> "FalsificationSnapshot":
        if self.taxonomy != list(FailureTaxonomy):
            raise ValueError("the P4 taxonomy must be fixed and canonically ordered")
        ids = [item.hypothesis_id for item in self.results]
        if len(ids) != len(set(ids)):
            raise ValueError("each hypothesis may appear only once")
        assessments = [item for result in self.results for item in result.assessments]
        taxonomy_counts = Counter(item.critic_type for item in assessments)
        verdict_counts = Counter(item.verdict for item in assessments)
        combined_counts = Counter(item.combined_verdict for item in self.results)
        if self.quality.taxonomy_counts != dict(taxonomy_counts):
            raise ValueError("taxonomy counts differ from the result set")
        if self.quality.verdict_counts != dict(verdict_counts):
            raise ValueError("critic verdict counts differ from the result set")
        if self.quality.combined_verdict_counts != dict(combined_counts):
            raise ValueError("combined verdict counts differ from the result set")
        if self.quality.hypothesis_count != len(self.results):
            raise ValueError("quality hypothesis count mismatch")
        if self.quality.critic_assessment_count != len(assessments):
            raise ValueError("quality critic count mismatch")
        return self


class FalsificationManifest(StrictModel):
    schema_version: Literal["4.0-development.1"] = "4.0-development.1"
    snapshot_id: StableId
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    builder_version: str = Field(min_length=1)
    source_checksums: dict[str, str] = Field(min_length=1)
    hypothesis_count: int = Field(ge=0)
    critic_assessment_count: int = Field(ge=0)
    scientific_validation_gate_passed: Literal[False] = False
