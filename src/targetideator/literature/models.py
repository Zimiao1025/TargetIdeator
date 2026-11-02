"""Strict P2.2 contracts for versioned passages and span-grounded claims."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, HttpUrl, model_validator

from targetideator.claims.models import ClaimPolarity, ClaimRelationType
from targetideator.contracts.models import StableId
from targetideator.evidence.models import CanonicalEntity, StrictModel


class LiteratureClaimTheme(StrEnum):
    GENETIC_ASSOCIATION = "genetic_association"
    DISEASE_ASSOCIATION = "disease_association"
    MECHANISM = "mechanism"
    THERAPEUTIC_EFFECT = "therapeutic_effect"
    BIOMARKER = "biomarker"
    SAFETY_LIMITATION = "safety_or_limitation"


class ClaimDirection(StrEnum):
    INCREASES = "increases"
    DECREASES = "decreases"
    CONTEXT_DEPENDENT = "context_dependent"
    UNKNOWN = "unknown"


class LiteratureQueryRoute(StrictModel):
    target_label: str = Field(min_length=1)
    query: str = Field(min_length=1)
    api_url: HttpUrl
    hit_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)


class LiteratureDocumentVersion(StrictModel):
    id: StableId
    source: Literal["Europe PMC"] = "Europe PMC"
    source_id: str = Field(pattern=r"^(MED|PMC):[A-Za-z0-9]+$")
    pmid: str | None = Field(default=None, pattern=r"^\d+$")
    pmcid: str | None = Field(default=None, pattern=r"^PMC\d+$")
    doi: str | None = None
    title: str = Field(min_length=1)
    abstract_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_date: date
    first_index_date: date
    source_revision_date: date
    version_available_on: date
    captured_at: datetime
    source_api_version: str = Field(min_length=1)
    source_api_url: HttpUrl
    version_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assigned_target: CanonicalEntity
    selection_route: str = Field(min_length=1)
    publication_types: list[str]
    is_open_access: bool

    @model_validator(mode="after")
    def version_date_is_conservative(self) -> "LiteratureDocumentVersion":
        expected = max(self.first_index_date, self.source_revision_date)
        if self.version_available_on != expected:
            raise ValueError("literature version availability must include source revision date")
        return self


class LiteratureParagraph(StrictModel):
    id: StableId
    document_version_id: StableId
    section: Literal["abstract"] = "abstract"
    paragraph_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_on: date
    source_field: Literal["abstractText"] = "abstractText"
    normalization_version: str = Field(min_length=1)


class SpanContext(StrictModel):
    species: str = Field(min_length=1)
    model_system: str = Field(min_length=1)
    population: str = Field(min_length=1)
    anatomical_region: str = Field(min_length=1)
    cell_type: str = Field(min_length=1)


class LiteratureClaim(StrictModel):
    id: StableId
    document_version_id: StableId
    paragraph_id: StableId
    target: CanonicalEntity
    disease: CanonicalEntity
    theme: LiteratureClaimTheme
    predicate: str = Field(min_length=1)
    object_text: str = Field(min_length=1)
    polarity: ClaimPolarity
    direction: ClaimDirection
    context: SpanContext
    verbatim_span: str = Field(min_length=1)
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    paragraph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    available_on: date
    annotation_origin: Literal["provisional_gold", "deterministic_extractor"]
    annotator_or_extractor_id: str = Field(min_length=1)
    review_status: Literal[
        "single_annotator_provisional", "pending_double_review", "adjudicated", "automated_unreviewed"
    ]
    eligible_for_p3: bool = False
    uncertainty: str = Field(min_length=1)

    @model_validator(mode="after")
    def span_offsets_are_ordered(self) -> "LiteratureClaim":
        if self.span_end <= self.span_start:
            raise ValueError("claim span end must be after start")
        if self.eligible_for_p3 and self.review_status != "adjudicated":
            raise ValueError("only adjudicated literature claims may enter P3")
        return self


class LiteratureClaimRelation(StrictModel):
    id: StableId
    source_claim_id: StableId
    target_claim_id: StableId
    relation_type: Literal[
        ClaimRelationType.SUPPORTS,
        ClaimRelationType.REFUTES,
        ClaimRelationType.REPLICATES,
    ]
    available_on: date
    proposition_key: str = Field(min_length=1)
    semantic_overlap: float = Field(ge=0, le=1)
    shared_terms: list[str] = Field(min_length=1)
    relation_cue: str | None = None
    decision_rule: Literal[
        "concordant_proposition_v1",
        "opposite_polarity_v1",
        "explicit_cross_document_replication_v1",
    ]
    rationale: str = Field(min_length=1)
    origin: Literal["provisional_gold", "deterministic_extractor"]
    review_status: Literal["single_annotator_provisional", "adjudicated", "automated_unreviewed"]
    eligible_for_p3: bool = False


class DoubleReviewTask(StrictModel):
    id: StableId
    claim_id: StableId
    required_reviewers: Literal[2] = 2
    status: Literal["pending", "adjudicated"] = "pending"
    reviewer_a: str | None = None
    reviewer_b: str | None = None
    adjudicator: str | None = None


class ExtractionMetrics(StrictModel):
    gold_claim_count: int = Field(ge=0)
    extracted_claim_count: int = Field(ge=0)
    exact_span_true_positive: int = Field(ge=0)
    exact_span_precision: float = Field(ge=0, le=1)
    exact_span_recall: float = Field(ge=0, le=1)
    exact_span_f1: float = Field(ge=0, le=1)
    target_accuracy_on_matched: float = Field(ge=0, le=1)
    theme_accuracy_on_matched: float = Field(ge=0, le=1)
    polarity_accuracy_on_matched: float = Field(ge=0, le=1)
    direction_accuracy_on_matched: float = Field(ge=0, le=1)
    gold_relation_count: int = Field(ge=0)
    extracted_relation_count: int = Field(ge=0)
    relation_precision: float = Field(ge=0, le=1)
    relation_recall: float = Field(ge=0, le=1)
    relation_f1: float = Field(ge=0, le=1)
    p3_gate_passed: bool
    p3_gate_reason: str = Field(min_length=1)


class LiteratureBenchmark(StrictModel):
    schema_version: Literal["2.2.0"] = "2.2.0"
    id: StableId
    captured_at: datetime
    source_api_version: str = Field(min_length=1)
    capture_cutoff: date
    query_routes: list[LiteratureQueryRoute] = Field(min_length=4)
    documents: list[LiteratureDocumentVersion] = Field(min_length=1)
    paragraphs: list[LiteratureParagraph] = Field(min_length=1)
    provisional_gold_claims: list[LiteratureClaim]
    provisional_gold_relations: list[LiteratureClaimRelation]
    double_review_tasks: list[DoubleReviewTask]
    extracted_claims: list[LiteratureClaim]
    extracted_relations: list[LiteratureClaimRelation]
    extraction_metrics: ExtractionMetrics

    @model_validator(mode="after")
    def validate_benchmark(self) -> "LiteratureBenchmark":
        document_ids = [item.id for item in self.documents]
        paragraph_ids = [item.id for item in self.paragraphs]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("literature document version IDs must be unique")
        if len(paragraph_ids) != len(set(paragraph_ids)):
            raise ValueError("literature paragraph IDs must be unique")
        paragraphs = {item.id: item for item in self.paragraphs}
        if {item.document_version_id for item in self.paragraphs} - set(document_ids):
            raise ValueError("paragraph references a missing document version")
        for collection in (self.provisional_gold_claims, self.extracted_claims):
            ids = [item.id for item in collection]
            if len(ids) != len(set(ids)):
                raise ValueError("claim IDs must be unique within each annotation layer")
            for claim in collection:
                paragraph = paragraphs.get(claim.paragraph_id)
                if paragraph is None:
                    raise ValueError(f"claim {claim.id} references a missing paragraph")
                if claim.document_version_id != paragraph.document_version_id:
                    raise ValueError(f"claim {claim.id} references the wrong document version")
                if claim.paragraph_sha256 != paragraph.text_sha256:
                    raise ValueError(f"claim {claim.id} paragraph checksum mismatch")
                if paragraph.text[claim.span_start : claim.span_end] != claim.verbatim_span:
                    raise ValueError(f"claim {claim.id} verbatim span does not match offsets")
                if claim.available_on != paragraph.available_on:
                    raise ValueError(f"claim {claim.id} availability differs from its paragraph")
        gold_ids = {item.id for item in self.provisional_gold_claims}
        extracted_ids = {item.id for item in self.extracted_claims}
        for relations, known in (
            (self.provisional_gold_relations, gold_ids),
            (self.extracted_relations, extracted_ids),
        ):
            relation_ids = [item.id for item in relations]
            if len(relation_ids) != len(set(relation_ids)):
                raise ValueError("literature relation IDs must be unique")
            for relation in relations:
                if relation.source_claim_id not in known or relation.target_claim_id not in known:
                    raise ValueError(f"relation {relation.id} references a missing claim")
                if relation.source_claim_id == relation.target_claim_id:
                    raise ValueError(f"relation {relation.id} cannot be a self edge")
                source = next(item for item in (*self.provisional_gold_claims, *self.extracted_claims) if item.id == relation.source_claim_id)
                target = next(item for item in (*self.provisional_gold_claims, *self.extracted_claims) if item.id == relation.target_claim_id)
                if source.document_version_id == target.document_version_id:
                    raise ValueError(f"relation {relation.id} must compare independent documents")
                if relation.relation_type == ClaimRelationType.REPLICATES and not relation.relation_cue:
                    raise ValueError(f"replication relation {relation.id} requires an explicit cue")
        task_claims = [item.claim_id for item in self.double_review_tasks]
        if len(task_claims) != len(set(task_claims)) or set(task_claims) - gold_ids:
            raise ValueError("double-review tasks must reference distinct provisional-gold claims")
        return self


class LiteratureManifest(StrictModel):
    schema_version: Literal["2.2.0"] = "2.2.0"
    snapshot_id: StableId
    raw_path: str = Field(min_length=1)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_path: str = Field(min_length=1)
    normalized_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    provisional_gold_claim_count: int = Field(ge=0)
    extracted_claim_count: int = Field(ge=0)
    extractor_version: str = Field(min_length=1)
