"""Version 1.1 contracts for an expert-reviewable target hypothesis dossier."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from targetideator.ids import ID_PATTERN

StableId = Annotated[str, Field(pattern=ID_PATTERN.pattern)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CurationStatus(StrEnum):
    ILLUSTRATIVE = "illustrative_pending_expert_review"
    AUTOMATED = "automated_unreviewed"
    EXPERT_REVIEWED = "expert_reviewed"


class SourceType(StrEnum):
    LITERATURE = "literature"
    CLINICAL_TRIAL = "clinical_trial"
    DATABASE = "database"
    GENETICS = "genetics"
    PATHWAY = "pathway"
    MANUAL_FIXTURE = "manual_fixture"


class EvidenceLevel(StrEnum):
    ILLUSTRATIVE = "illustrative"
    PRECLINICAL = "preclinical"
    HUMAN_OBSERVATIONAL = "human_observational"
    HUMAN_GENETIC = "human_genetic"
    INTERVENTIONAL = "interventional"
    META_ANALYSIS = "meta_analysis"


class EvidencePolarity(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    QUALIFIES = "qualifies"
    NEUTRAL = "neutral"


class InterventionDirection(StrEnum):
    INHIBIT = "inhibit"
    ACTIVATE = "activate"
    DEGRADE = "degrade"
    REPLACE = "replace"
    EDIT = "edit"
    UNKNOWN = "unknown"


class Modality(StrEnum):
    SMALL_MOLECULE = "small_molecule"
    ANTIBODY = "antibody"
    OLIGO = "oligo"
    CELL_GENE_THERAPY = "cell_gene_therapy"
    OTHER = "other"
    UNKNOWN = "unknown"


class Verdict(StrEnum):
    UNASSESSED = "unassessed"
    SURVIVE = "survive"
    REVISE = "revise"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ClaimRelationType(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    QUALIFIES = "qualifies"
    REPLICATES = "replicates"
    DERIVED_FROM = "derived_from"
    SAME_COHORT_AS = "same_cohort_as"
    SUPERSEDES = "supersedes"


class MechanisticRole(StrEnum):
    REQUIRED = "required"
    CONTRIBUTING = "contributing"
    MARKER = "marker"
    UNKNOWN = "unknown"


class TargetForm(StrEnum):
    PROTEIN_SUBUNIT = "protein_subunit"
    PROTEIN_COMPLEX = "protein_complex"
    SOLUBLE_LIGAND = "soluble_ligand"
    MEMBRANE_AND_SOLUBLE_LIGAND = "membrane_and_soluble_ligand"
    INTRACELLULAR_ENZYME = "intracellular_enzyme"
    INTRACELLULAR_SENSOR = "intracellular_sensor"
    OTHER = "other"
    UNKNOWN = "unknown"


class BiomarkerRole(StrEnum):
    PREDICTIVE = "predictive"
    PROGNOSTIC = "prognostic"
    PHARMACODYNAMIC = "pharmacodynamic"
    SAFETY = "safety"
    DIAGNOSTIC = "diagnostic"


class ValidationStatus(StrEnum):
    CONCEPT = "concept_only"
    ANALYTICAL = "analytically_validated"
    RETROSPECTIVE = "retrospectively_validated"
    EXTERNAL = "externally_validated"
    PROSPECTIVE = "prospectively_validated"
    UNKNOWN = "unknown"


class CriterionStatus(StrEnum):
    SPECIFIED = "specified"
    REQUIRES_PILOT = "requires_pilot_data"
    DEFERRED = "deferred_to_later_stage"


class DevelopmentStage(StrEnum):
    TARGET_IDEATION = "target_ideation"
    TARGET_VALIDATION = "target_validation"
    CANDIDATE_OPTIMIZATION = "candidate_optimization"
    CLINICAL_DEVELOPMENT = "clinical_development"


class DecisionRole(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    SUPPORTIVE = "supportive"
    FATAL_BOUNDARY = "fatal_boundary"


class EndpointRole(StrEnum):
    TARGET_ENGAGEMENT = "target_engagement"
    PHARMACODYNAMIC = "pharmacodynamic"
    EFFICACY = "efficacy"
    SAFETY = "safety"
    BIOMARKER_CUTOFF = "biomarker_cutoff"


class ReviewOutcome(StrEnum):
    ACCEPTED = "accepted"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class EntityRef(StrictModel):
    namespace: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    label: str = Field(min_length=1)
    entity_type: Literal[
        "disease",
        "gene",
        "protein",
        "protein_complex",
        "pathway",
        "phenotype",
        "biomarker",
        "cell_type",
        "anatomy",
    ]


class UnknownItem(StrictModel):
    field: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    resolution_action: str = Field(min_length=1)
    blocking_for_current_gate: bool
    resolution_stage: DevelopmentStage


class TreatmentContext(StrictModel):
    severity: str = Field(min_length=1)
    prior_therapy_requirements: list[str] = Field(min_length=1)
    concomitant_therapy: str = Field(min_length=1)
    infection_constraints: list[str] = Field(default_factory=list)
    comorbidity_constraints: list[str] = Field(default_factory=list)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class AnatomicalContext(StrictModel):
    id: StableId
    organ: str = Field(min_length=1)
    region: str = Field(min_length=1)
    compartment: str = Field(min_length=1)
    sampling_method: str = Field(min_length=1)
    accessibility: str = Field(min_length=1)
    decision_window: str = Field(min_length=1)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class DiseaseBrief(StrictModel):
    id: StableId
    as_of_date: date
    disease: EntityRef
    population: str = Field(min_length=1)
    disease_stage: str = Field(min_length=1)
    treatment_context: TreatmentContext
    anatomical_contexts: list[AnatomicalContext] = Field(min_length=1)
    target_tissues: list[str] = Field(min_length=1)
    key_cell_states: list[str] = Field(min_length=1)
    desired_outcomes: list[str] = Field(min_length=1)
    allowed_modalities: list[Modality] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    curation_status: CurationStatus


class EvidenceRecord(StrictModel):
    id: StableId
    source_type: SourceType
    evidence_level: EvidenceLevel
    source_record_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: HttpUrl | None = None
    locator: str = Field(min_length=1)
    passage: str = Field(min_length=1)
    study_design: str = Field(min_length=1)
    population_or_model: str = Field(min_length=1)
    polarity: EvidencePolarity
    publication_date: date | None = None
    available_on: date
    limitations: list[str] = Field(min_length=1)
    curation_status: CurationStatus
    notes: list[str] = Field(default_factory=list)


class ClaimContext(StrictModel):
    species: str = Field(min_length=1)
    anatomical_region: str = Field(min_length=1)
    compartment: str = Field(min_length=1)
    source_cells: list[str] = Field(min_length=1)
    responding_cells: list[str] = Field(min_length=1)
    effector_cells: list[str] = Field(min_length=1)
    population: str = Field(min_length=1)
    disease_stage: str = Field(min_length=1)
    treatment_context: str = Field(min_length=1)
    model_system: str = Field(min_length=1)
    mechanistic_role: MechanisticRole
    bypass_or_compensation: list[str] = Field(default_factory=list)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class ClaimObject(StrictModel):
    entity: EntityRef | None = None
    text: str | None = None

    @model_validator(mode="after")
    def exactly_one_value(self) -> "ClaimObject":
        if (self.entity is None) == (self.text is None):
            raise ValueError("ClaimObject requires exactly one of entity or text")
        return self


class Claim(StrictModel):
    id: StableId
    subject: EntityRef
    predicate: str = Field(min_length=1)
    object: ClaimObject
    context: ClaimContext
    direction: InterventionDirection | None = None
    polarity: EvidencePolarity
    evidence_ids: list[StableId] = Field(min_length=1)
    effect_size: str | None = None
    effect_size_missing_reason: str | None = None
    uncertainty: str = Field(min_length=1)
    curation_status: CurationStatus

    @model_validator(mode="after")
    def explain_missing_effect_size(self) -> "Claim":
        if self.effect_size is None and not self.effect_size_missing_reason:
            raise ValueError("missing effect_size requires effect_size_missing_reason")
        return self


class ClaimRelation(StrictModel):
    id: StableId
    source_claim_id: StableId
    target_claim_id: StableId
    relation_type: ClaimRelationType
    notes: str | None = None


class TargetSpec(StrictModel):
    entity: EntityRef
    biological_form: TargetForm
    molecular_scope: str = Field(min_length=1)
    partner_entities: list[EntityRef] = Field(default_factory=list)
    localization: list[str] = Field(min_length=1)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class ThresholdSpec(StrictModel):
    operator: Literal[">", ">=", "<", "<=", "between", "qualitative"]
    value: float | None = None
    upper_value: float | None = None
    unit: str | None = None
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_threshold(self) -> "ThresholdSpec":
        if self.operator == "between":
            if self.value is None or self.upper_value is None or self.value > self.upper_value:
                raise ValueError("between threshold requires ordered value and upper_value")
        elif self.operator != "qualitative" and self.value is None:
            raise ValueError("numeric threshold requires value")
        return self


class MeasurementCriterion(StrictModel):
    id: StableId
    role: EndpointRole
    endpoint: str = Field(min_length=1)
    method: str = Field(min_length=1)
    matrix: str = Field(min_length=1)
    timepoint: str = Field(min_length=1)
    expected_direction: str = Field(min_length=1)
    decision_role: DecisionRole
    required_for_current_gate: bool
    threshold_status: CriterionStatus
    threshold: ThresholdSpec | None = None
    threshold_derivation: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    failure_condition: str = Field(min_length=1)
    inconclusive_condition: str = Field(min_length=1)

    @model_validator(mode="after")
    def threshold_matches_status(self) -> "MeasurementCriterion":
        if self.threshold_status == CriterionStatus.SPECIFIED and self.threshold is None:
            raise ValueError("specified criterion requires threshold")
        if self.threshold_status != CriterionStatus.SPECIFIED and self.threshold is not None:
            raise ValueError("non-specified criterion must not invent a threshold")
        if self.threshold_status == CriterionStatus.DEFERRED and self.required_for_current_gate:
            raise ValueError("deferred criterion cannot be required for current gate")
        return self


class Intervention(StrictModel):
    direction: InterventionDirection
    degree: str = Field(min_length=1)
    modality: Modality
    molecular_action: str = Field(min_length=1)
    selectivity_requirements: list[str] = Field(min_length=1)
    desired_distribution: str = Field(min_length=1)
    route: str = Field(min_length=1)
    target_engagement_criterion: MeasurementCriterion
    pharmacodynamic_criteria: list[MeasurementCriterion] = Field(min_length=1)
    safety_criteria: list[MeasurementCriterion] = Field(min_length=1)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class BiomarkerDefinition(StrictModel):
    id: StableId
    name: str = Field(min_length=1)
    role: BiomarkerRole
    features: list[str] = Field(min_length=1)
    matrix: str = Field(min_length=1)
    assay: str = Field(min_length=1)
    sampling_timepoint: str = Field(min_length=1)
    cutoff_criterion: MeasurementCriterion
    decision_window_accessibility: str = Field(min_length=1)
    analytical_validation: ValidationStatus
    clinical_validation: ValidationStatus
    unknowns: list[UnknownItem] = Field(default_factory=list)


class MechanismSummary(StrictModel):
    mechanistic_role: MechanisticRole
    source_cells: list[str] = Field(min_length=1)
    responding_cells: list[str] = Field(min_length=1)
    effector_cells: list[str] = Field(min_length=1)
    anatomical_compartments: list[str] = Field(min_length=1)
    bypass_or_compensation: list[str] = Field(default_factory=list)
    unknowns: list[UnknownItem] = Field(default_factory=list)


class FalsifiablePrediction(StrictModel):
    id: StableId
    statement: str = Field(min_length=1)
    refutation_condition: str = Field(min_length=1)
    decision_criterion: MeasurementCriterion


class HypothesisCard(StrictModel):
    id: StableId
    as_of_date: date
    indication: EntityRef
    population: str = Field(min_length=1)
    cell_state: str = Field(min_length=1)
    decision_scope: DevelopmentStage
    current_gate: Literal["ready_for_target_validation_experiment"]
    non_goals: list[str] = Field(min_length=1)
    target: TargetSpec
    mechanism_context: MechanismSummary
    intervention: Intervention
    mechanism_claim_ids: list[StableId] = Field(min_length=1)
    biomarker: BiomarkerDefinition
    supporting_claim_ids: list[StableId] = Field(default_factory=list)
    counterevidence_claim_ids: list[StableId] = Field(default_factory=list)
    fatal_assumption: str = Field(min_length=1)
    falsifiable_predictions: list[FalsifiablePrediction] = Field(min_length=1)
    curation_status: CurationStatus
    review_notes: list[str] = Field(default_factory=list)


class HeadAssessment(StrictModel):
    status: Literal["not_scored", "estimated", "abstained"] = "not_scored"
    probability: float | None = Field(default=None, ge=0, le=1)
    confidence_interval: tuple[float, float] | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_probability(self) -> "HeadAssessment":
        if self.status == "estimated" and self.probability is None:
            raise ValueError("estimated assessment requires probability")
        if self.status != "estimated" and self.probability is not None:
            raise ValueError("only estimated assessment may contain probability")
        if self.confidence_interval:
            low, high = self.confidence_interval
            if not 0 <= low <= high <= 1:
                raise ValueError("confidence interval must satisfy 0 <= low <= high <= 1")
        return self


class DecisionSnapshot(StrictModel):
    id: StableId
    hypothesis_id: StableId
    as_of_date: date
    verdict: Verdict
    assessments: dict[str, HeadAssessment] = Field(min_length=1)
    novelty_axes: list[str] = Field(default_factory=list)
    abstention_reason: str | None = None
    curation_status: CurationStatus

    @model_validator(mode="after")
    def abstention_is_explained(self) -> "DecisionSnapshot":
        if self.verdict == Verdict.ABSTAIN and not self.abstention_reason:
            raise ValueError("abstain verdict requires abstention_reason")
        return self


class ControlArm(StrictModel):
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class SamplePlan(StrictModel):
    experimental_unit: str = Field(min_length=1)
    inclusion_criteria: list[str] = Field(min_length=1)
    exclusion_criteria: list[str] = Field(min_length=1)
    minimum_biological_replicates: int | None = Field(default=None, ge=2)
    status: CriterionStatus
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def replicate_count_matches_status(self) -> "SamplePlan":
        if self.status == CriterionStatus.SPECIFIED and self.minimum_biological_replicates is None:
            raise ValueError("specified sample plan requires minimum_biological_replicates")
        if self.status != CriterionStatus.SPECIFIED and self.minimum_biological_replicates is not None:
            raise ValueError("non-specified sample plan must not invent replicate count")
        return self


class ExperimentAction(StrictModel):
    id: StableId
    hypothesis_id: StableId
    assumption_tested: str = Field(min_length=1)
    assay_type: str = Field(min_length=1)
    model_system: str = Field(min_length=1)
    design: str = Field(min_length=1)
    controls: list[ControlArm] = Field(min_length=1)
    sample_plan: SamplePlan
    timepoints: list[str] = Field(min_length=1)
    primary_endpoint: MeasurementCriterion
    secondary_endpoints: list[MeasurementCriterion] = Field(default_factory=list)
    decision_criteria: list[MeasurementCriterion] = Field(min_length=1)
    expected_information_gain: str = Field(min_length=1)
    estimated_cost: str | None = None
    go_no_go_rule: str = Field(min_length=1)
    curation_status: CurationStatus


class ReviewRecord(StrictModel):
    id: StableId
    reviewer_label: str = Field(min_length=1)
    review_round: int = Field(ge=1)
    reviewed_on: date
    scope: str = Field(min_length=1)
    outcome: ReviewOutcome
    source_path: str = Field(min_length=1)
    findings: list[str] = Field(min_length=1)
    resolution_status: str = Field(min_length=1)


class ScopePolicy(StrictModel):
    status: Literal["frozen"]
    decision_scope: DevelopmentStage
    current_gate: Literal["ready_for_target_validation_experiment"]
    in_scope: list[str] = Field(min_length=1)
    explicitly_deferred: list[str] = Field(min_length=1)
    acceptance_rule: str = Field(min_length=1)
    change_control_rule: str = Field(min_length=1)


class ProjectBundle(StrictModel):
    schema_version: Literal["1.2.0"]
    snapshot_id: StableId
    scope_policy: ScopePolicy
    disease_brief: DiseaseBrief
    evidence_records: list[EvidenceRecord]
    claims: list[Claim]
    claim_relations: list[ClaimRelation] = Field(default_factory=list)
    hypotheses: list[HypothesisCard]
    decisions: list[DecisionSnapshot]
    experiment_actions: list[ExperimentAction]
    review_records: list[ReviewRecord] = Field(default_factory=list)
