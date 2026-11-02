"""Contracts for the frozen P2.2 double-review batch."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from targetideator.claims.models import ClaimPolarity
from targetideator.contracts.models import StableId
from targetideator.evidence.models import StrictModel
from targetideator.literature.models import ClaimDirection, LiteratureClaimTheme


class ReviewDisposition(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVISE = "revise"


class TargetGrounding(StrEnum):
    EXPLICIT = "explicit"
    CONTEXTUAL = "contextual"
    ABSENT = "absent"
    WRONG_TARGET = "wrong_target"


class EvidenceRole(StrEnum):
    DIRECT_RESULT = "direct_result"
    SECONDARY_OR_BACKGROUND = "secondary_or_background"
    CONTEXTUAL_INFERENCE = "contextual_inference"
    NEGATIVE_RESULT = "negative_result"
    NOT_TARGET_EVIDENCE = "not_target_evidence"


class ClaimReview(StrictModel):
    id: StableId
    task_id: StableId
    claim_id: StableId
    review_pass: Literal["A", "B"]
    reviewer_id: str = Field(min_length=1)
    reviewer_kind: Literal["model_assisted"] = "model_assisted"
    guideline_version: Literal["literature-claim-review-v1"] = "literature-claim-review-v1"
    blinded_to_other_pass: Literal[True] = True
    completed_at: datetime
    disposition: ReviewDisposition
    target_grounding: TargetGrounding
    evidence_role: EvidenceRole
    is_atomic_claim: bool
    proposed_theme: LiteratureClaimTheme | None = None
    proposed_polarity: ClaimPolarity | None = None
    proposed_direction: ClaimDirection | None = None
    rationale: str = Field(min_length=1)
    human_signed_off: Literal[False] = False

    @model_validator(mode="after")
    def labels_follow_disposition(self) -> "ClaimReview":
        labels = (self.proposed_theme, self.proposed_polarity, self.proposed_direction)
        if self.disposition == ReviewDisposition.REJECT and any(item is not None for item in labels):
            raise ValueError("rejected claim reviews cannot retain semantic labels")
        if self.disposition != ReviewDisposition.REJECT and any(item is None for item in labels):
            raise ValueError("accepted/revised claim reviews require all semantic labels")
        return self


class DoubleReviewResult(StrictModel):
    task_id: StableId
    claim_id: StableId
    reviews: list[ClaimReview] = Field(min_length=2, max_length=2)
    agreement: bool
    disagreement_fields: list[str]
    status: Literal["pending_human_double_review"] = "pending_human_double_review"
    eligible_for_adjudication: Literal[False] = False
    adjudicated: Literal[False] = False

    @model_validator(mode="after")
    def reviews_are_distinct_and_consistent(self) -> "DoubleReviewResult":
        if {item.review_pass for item in self.reviews} != {"A", "B"}:
            raise ValueError("double review requires distinct A and B passes")
        if len({item.reviewer_id for item in self.reviews}) != 2:
            raise ValueError("double review passes require distinct reviewer IDs")
        if any(item.task_id != self.task_id or item.claim_id != self.claim_id for item in self.reviews):
            raise ValueError("review references do not match their task")
        if self.agreement != (not self.disagreement_fields):
            raise ValueError("agreement flag must match disagreement fields")
        return self


class ReviewBatchSummary(StrictModel):
    task_count: int = Field(ge=0)
    model_pass_count: int = Field(ge=0)
    agreement_count: int = Field(ge=0)
    disagreement_count: int = Field(ge=0)
    consensus_accept_count: int = Field(ge=0)
    consensus_reject_count: int = Field(ge=0)
    disposition_disagreement_count: int = Field(ge=0)
    human_signed_review_count: Literal[0] = 0
    adjudicated_count: Literal[0] = 0
    final_gold_claim_count: Literal[0] = 0


class LiteratureReviewBatch(StrictModel):
    schema_version: Literal["2.2-review.1"] = "2.2-review.1"
    id: StableId
    source_snapshot_id: StableId
    guideline_version: Literal["literature-claim-review-v1"] = "literature-claim-review-v1"
    created_at: datetime
    review_results: list[DoubleReviewResult] = Field(min_length=1)
    summary: ReviewBatchSummary
    status: Literal["model_pre_review_complete_human_review_pending"] = (
        "model_pre_review_complete_human_review_pending"
    )
    annotation_layer: Literal["provisional_gold"] = "provisional_gold"
    p3_gate_passed: Literal[False] = False
    warning: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_batch(self) -> "LiteratureReviewBatch":
        task_ids = [item.task_id for item in self.review_results]
        claim_ids = [item.claim_id for item in self.review_results]
        if len(task_ids) != len(set(task_ids)) or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("review batch tasks and claims must be unique")
        if self.summary.task_count != len(self.review_results):
            raise ValueError("review batch summary task count mismatch")
        return self


class ExternalCommentRecommendation(StrictModel):
    source_file: Literal["a_reviewer.md", "b_reviewer.md"]
    recommendation: Literal[
        "accept", "reject", "revise", "accept_or_revise", "reject_or_revise"
    ]
    formally_signed: Literal[False] = False


class ProposedCommentResolution(StrictModel):
    task_id: StableId
    claim_id: StableId
    external_comments: list[ExternalCommentRecommendation] = Field(min_length=2, max_length=2)
    model_pass_dispositions: dict[Literal["A", "B"], ReviewDisposition]
    proposed_disposition: ReviewDisposition
    proposed_target_grounding: TargetGrounding
    proposed_evidence_role: EvidenceRole
    proposed_theme: LiteratureClaimTheme | None = None
    proposed_polarity: ClaimPolarity | None = None
    proposed_direction: ClaimDirection | None = None
    replacement_claim_id: StableId | None = None
    rationale: str = Field(min_length=1)
    status: Literal["awaiting_formal_human_confirmation"] = (
        "awaiting_formal_human_confirmation"
    )
    modifies_provisional_gold: Literal[False] = False
    adjudicated: Literal[False] = False

    @model_validator(mode="after")
    def proposed_labels_follow_disposition(self) -> "ProposedCommentResolution":
        labels = (self.proposed_theme, self.proposed_polarity, self.proposed_direction)
        if self.proposed_disposition == ReviewDisposition.REJECT and any(
            item is not None for item in labels
        ):
            raise ValueError("rejected proposed resolutions cannot retain semantic labels")
        if self.proposed_disposition != ReviewDisposition.REJECT and any(
            item is None for item in labels
        ):
            raise ValueError("accepted/revised proposed resolutions require semantic labels")
        return self


class ExpertCommentResolutionBatch(StrictModel):
    schema_version: Literal["2.2-review-comments.1"] = "2.2-review-comments.1"
    id: StableId
    review_batch_id: StableId
    source_snapshot_id: StableId
    created_at: datetime
    source_file_sha256: dict[str, str]
    resolutions: list[ProposedCommentResolution] = Field(min_length=1)
    proposed_accept_count: int = Field(ge=0)
    proposed_reject_count: int = Field(ge=0)
    proposed_revise_count: int = Field(ge=0)
    formal_human_review_count: Literal[0] = 0
    adjudicated_count: Literal[0] = 0
    final_gold_claim_count: Literal[0] = 0
    p3_gate_passed: Literal[False] = False
    status: Literal["comments_resolved_formal_review_pending"] = (
        "comments_resolved_formal_review_pending"
    )

    @model_validator(mode="after")
    def validate_counts(self) -> "ExpertCommentResolutionBatch":
        counts = {
            disposition: sum(item.proposed_disposition == disposition for item in self.resolutions)
            for disposition in ReviewDisposition
        }
        if (
            self.proposed_accept_count != counts[ReviewDisposition.ACCEPT]
            or self.proposed_reject_count != counts[ReviewDisposition.REJECT]
            or self.proposed_revise_count != counts[ReviewDisposition.REVISE]
        ):
            raise ValueError("comment resolution disposition counts do not match records")
        return self


class HumanReviewDecision(StrictModel):
    task_id: StableId
    claim_id: StableId
    reviewer_slot: Literal["A", "B"]
    source_recommendation: Literal[
        "accept", "reject", "revise", "accept_or_revise", "reject_or_revise"
    ]
    system_proposed_disposition: ReviewDisposition
    system_proposed_target_grounding: TargetGrounding
    system_proposed_evidence_role: EvidenceRole
    system_proposed_theme: LiteratureClaimTheme | None = None
    system_proposed_polarity: ClaimPolarity | None = None
    system_proposed_direction: ClaimDirection | None = None
    system_replacement_claim_id: StableId | None = None
    reviewer_disposition: ReviewDisposition | None = None
    reviewer_target_grounding: TargetGrounding | None = None
    reviewer_evidence_role: EvidenceRole | None = None
    reviewer_is_atomic_claim: bool | None = None
    reviewer_theme: LiteratureClaimTheme | None = None
    reviewer_polarity: ClaimPolarity | None = None
    reviewer_direction: ClaimDirection | None = None
    reviewer_replacement_claim_id: StableId | None = None
    reviewer_rationale: str | None = None
    reviewer_confirmed: bool = False

    @model_validator(mode="after")
    def confirmed_decision_is_complete(self) -> "HumanReviewDecision":
        if not self.reviewer_confirmed:
            return self
        required = (
            self.reviewer_disposition,
            self.reviewer_target_grounding,
            self.reviewer_evidence_role,
            self.reviewer_is_atomic_claim,
            self.reviewer_rationale,
        )
        if any(item is None for item in required):
            raise ValueError("confirmed human review decision is incomplete")
        semantic = (self.reviewer_theme, self.reviewer_polarity, self.reviewer_direction)
        if self.reviewer_disposition == ReviewDisposition.REJECT:
            if any(item is not None for item in semantic):
                raise ValueError("confirmed rejected decision cannot retain semantic labels")
        elif any(item is None for item in semantic):
            raise ValueError("confirmed accepted/revised decision requires semantic labels")
        return self


class HumanReviewSubmission(StrictModel):
    schema_version: Literal["2.2-human-review.1"] = "2.2-human-review.1"
    id: StableId
    source_snapshot_id: StableId
    review_batch_id: StableId
    comment_resolution_id: StableId
    reviewer_slot: Literal["A", "B"]
    review_mode: Literal["blind_independent", "non_blinded"] = "non_blinded"
    model_assistance_exposed_before_signoff: bool = True
    blind_input_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    decisions: list[HumanReviewDecision] = Field(min_length=1)
    human_signed_off: bool = False
    signed_at: datetime | None = None
    signature_statement: str | None = None
    status: Literal["draft", "signed"] = "draft"

    @model_validator(mode="after")
    def validate_submission(self) -> "HumanReviewSubmission":
        task_ids = [item.task_id for item in self.decisions]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("human review submission tasks must be unique")
        if any(item.reviewer_slot != self.reviewer_slot for item in self.decisions):
            raise ValueError("decision reviewer slot differs from submission")
        if self.review_mode == "blind_independent":
            if self.model_assistance_exposed_before_signoff:
                raise ValueError("blind review cannot expose model assistance before sign-off")
            if self.blind_input_sha256 is None:
                raise ValueError("blind review requires source input checksum")
        if self.human_signed_off:
            if self.status != "signed":
                raise ValueError("signed human review must have signed status")
            if not self.reviewer_id or not self.reviewer_role:
                raise ValueError("signed human review requires reviewer identity and role")
            if self.signed_at is None or not self.signature_statement:
                raise ValueError("signed human review requires timestamp and signature statement")
            if not all(item.reviewer_confirmed for item in self.decisions):
                raise ValueError("all human review decisions must be confirmed before sign-off")
        elif self.status != "draft" or self.signed_at is not None:
            raise ValueError("unsigned human review must remain an undated draft")
        return self


class HumanReviewReadiness(StrictModel):
    schema_version: Literal["2.2-human-readiness.1"] = "2.2-human-readiness.1"
    source_snapshot_id: StableId
    review_batch_id: StableId
    submission_ids: list[StableId] = Field(min_length=2, max_length=2)
    task_count: int = Field(ge=0)
    reviewer_a_confirmed_count: int = Field(ge=0)
    reviewer_b_confirmed_count: int = Field(ge=0)
    reviewer_a_unconfirmed_task_ids: list[StableId]
    reviewer_b_unconfirmed_task_ids: list[StableId]
    reviewer_a_missing_task_ids: list[StableId]
    reviewer_b_missing_task_ids: list[StableId]
    reviewer_a_unexpected_task_ids: list[StableId]
    reviewer_b_unexpected_task_ids: list[StableId]
    task_claim_mismatch_ids: list[StableId]
    signed_submission_count: int = Field(ge=0, le=2)
    distinct_human_reviewers: bool
    blind_independent_submission_count: int = Field(ge=0, le=2)
    blocking_reasons: list[str]
    eligible_for_adjudication: bool
    status: Literal["blocked", "ready_for_adjudication"]
    adjudicated_count: Literal[0] = 0
    final_gold_claim_count: Literal[0] = 0
    p3_gate_passed: Literal[False] = False

    @model_validator(mode="after")
    def readiness_matches_blockers(self) -> "HumanReviewReadiness":
        ready = not self.blocking_reasons
        if self.eligible_for_adjudication != ready:
            raise ValueError("adjudication eligibility must match blocking reasons")
        if (self.status == "ready_for_adjudication") != ready:
            raise ValueError("readiness status must match blocking reasons")
        return self


class BlindHumanReviewDecision(StrictModel):
    """Evidence-complete review item that contains no model-assisted recommendation."""

    task_id: StableId
    claim_id: StableId
    reviewer_slot: Literal["A", "B"]
    assigned_target_label: str = Field(min_length=1)
    assigned_target_identifier: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    paragraph_id: StableId
    paragraph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paragraph_text: str = Field(min_length=1)
    verbatim_span: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    reviewer_disposition: ReviewDisposition | None = None
    reviewer_target_grounding: TargetGrounding | None = None
    reviewer_evidence_role: EvidenceRole | None = None
    reviewer_is_atomic_claim: bool | None = None
    reviewer_theme: LiteratureClaimTheme | None = None
    reviewer_polarity: ClaimPolarity | None = None
    reviewer_direction: ClaimDirection | None = None
    reviewer_replacement_claim_id: StableId | None = None
    reviewer_rationale: str | None = None
    reviewer_confirmed: bool = False

    @model_validator(mode="after")
    def evidence_and_decision_are_valid(self) -> "BlindHumanReviewDecision":
        paragraph_hash = hashlib.sha256(self.paragraph_text.encode("utf-8")).hexdigest()
        if paragraph_hash != self.paragraph_sha256:
            raise ValueError("blind review paragraph checksum mismatch")
        if self.paragraph_text[self.span_start : self.span_end] != self.verbatim_span:
            raise ValueError("blind review verbatim span does not match offsets")
        if not self.reviewer_confirmed:
            return self
        required = (
            self.reviewer_disposition,
            self.reviewer_target_grounding,
            self.reviewer_evidence_role,
            self.reviewer_is_atomic_claim,
            self.reviewer_rationale,
        )
        if any(item is None for item in required):
            raise ValueError("confirmed blind review decision is incomplete")
        semantic = (self.reviewer_theme, self.reviewer_polarity, self.reviewer_direction)
        if self.reviewer_disposition == ReviewDisposition.REJECT:
            if any(item is not None for item in semantic):
                raise ValueError("confirmed rejected blind decision cannot retain semantic labels")
        elif any(item is None for item in semantic):
            raise ValueError("confirmed accepted/revised blind decision requires semantic labels")
        return self


class BlindHumanReviewSubmission(StrictModel):
    """Editable, independently signed review submission with evidence but no model labels."""

    schema_version: Literal["2.2-blind-human-review.1"] = "2.2-blind-human-review.1"
    id: StableId
    source_snapshot_id: StableId
    review_batch_id: StableId
    reviewer_slot: Literal["A", "B"]
    review_mode: Literal["blind_independent"] = "blind_independent"
    model_assistance_exposed_before_signoff: Literal[False] = False
    reviewer_id: str | None = None
    reviewer_role: str | None = None
    decisions: list[BlindHumanReviewDecision] = Field(min_length=1)
    human_signed_off: bool = False
    signed_at: datetime | None = None
    signature_statement: str | None = None
    status: Literal["draft", "signed"] = "draft"

    @model_validator(mode="after")
    def validate_submission(self) -> "BlindHumanReviewSubmission":
        task_ids = [item.task_id for item in self.decisions]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("blind human review tasks must be unique")
        if any(item.reviewer_slot != self.reviewer_slot for item in self.decisions):
            raise ValueError("blind decision reviewer slot differs from submission")
        if self.human_signed_off:
            if self.status != "signed":
                raise ValueError("signed blind review must have signed status")
            if not self.reviewer_id or not self.reviewer_role:
                raise ValueError("signed blind review requires reviewer identity and role")
            if self.signed_at is None or not self.signature_statement:
                raise ValueError("signed blind review requires timestamp and signature statement")
            if not all(item.reviewer_confirmed for item in self.decisions):
                raise ValueError("all blind review decisions must be confirmed before sign-off")
        elif self.status != "draft" or self.signed_at is not None:
            raise ValueError("unsigned blind review must remain an undated draft")
        return self


class AdjudicationQueueEntry(StrictModel):
    task_id: StableId
    claim_id: StableId
    disagreement_fields: list[str]
    requires_adjudicator_decision: Literal[True] = True
    status: Literal["pending"] = "pending"


class LiteratureAdjudicationQueue(StrictModel):
    schema_version: Literal["2.2-adjudication.1"] = "2.2-adjudication.1"
    id: StableId
    source_snapshot_id: StableId
    review_batch_id: StableId
    reviewer_a_submission_id: StableId
    reviewer_b_submission_id: StableId
    entries: list[AdjudicationQueueEntry] = Field(min_length=1)
    agreement_count: int = Field(ge=0)
    disagreement_count: int = Field(ge=0)
    status: Literal["ready_for_adjudication"] = "ready_for_adjudication"
    adjudicated_count: Literal[0] = 0
    final_gold_claim_count: Literal[0] = 0
    p3_gate_passed: Literal[False] = False

    @model_validator(mode="after")
    def counts_match_entries(self) -> "LiteratureAdjudicationQueue":
        disagreement_count = sum(bool(item.disagreement_fields) for item in self.entries)
        if disagreement_count != self.disagreement_count:
            raise ValueError("adjudication disagreement count mismatch")
        if len(self.entries) - disagreement_count != self.agreement_count:
            raise ValueError("adjudication agreement count mismatch")
        return self
