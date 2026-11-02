"""Build and load deterministic P4 fixed-taxonomy falsification artifacts."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.claims.models import ClaimPolarity
from targetideator.contracts.models import InterventionDirection, Modality, Verdict
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.models import (
    CriticAssessment,
    FailureTaxonomy,
    FalsifiablePrediction,
    FalsificationManifest,
    FalsificationQuality,
    FalsificationResult,
    FalsificationSnapshot,
)
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ideation.models import ComposedHypothesis, RecallRoute
from targetideator.ideation.store import (
    default_ideation_manifest_path,
    default_ideation_portfolio_path,
    load_default_ideation_store,
)
from targetideator.io import write_json
from targetideator.literature.models import ClaimDirection, LiteratureClaimTheme
from targetideator.literature.store import (
    default_literature_snapshot_path,
    load_default_literature_store,
)

BUILDER_VERSION = "p4-fixed-taxonomy-falsifier-v1"
SNAPSHOT_ID = "ti:falsification-snapshot:crohns-p4-development-v1"
CREATED_AT = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)


def default_falsification_snapshot_path() -> Path:
    return fixture_path("p4_falsification_snapshot.json")


def default_falsification_manifest_path() -> Path:
    return fixture_path("p4_falsification_manifest.json")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _prediction(
    hypothesis: ComposedHypothesis, critic_type: FailureTaxonomy
) -> FalsifiablePrediction:
    target = hypothesis.target.label
    direction = hypothesis.proposed_direction.value
    if critic_type == FailureTaxonomy.CAUSAL:
        return FalsifiablePrediction(
            statement=(
                f"Perturbing {target} changes a disease-relevant phenotype after target engagement, "
                "with the effect abolished by a target-specific rescue or orthogonal perturbation."
            ),
            required_observation=(
                "Concordant phenotypic change in at least two orthogonal perturbations plus a "
                "target-specific rescue in a disease-relevant system."
            ),
            refutation_condition=(
                "Confirmed target engagement produces no concordant phenotype, or the apparent "
                "effect persists after target-specific rescue."
            ),
            assay_boundary="Disease-relevant human primary, organoid, or genetically anchored system.",
        )
    if critic_type == FailureTaxonomy.DIRECTION:
        if hypothesis.proposed_direction == InterventionDirection.UNKNOWN:
            statement = f"A reproducible beneficial direction for {target} can be resolved before modality selection."
            observation = "Bidirectional perturbation produces a consistent, monotonic separation of benefit and harm."
            refutation = "Activation and inhibition are inconsistent across matched disease-relevant contexts."
        elif hypothesis.proposed_direction == InterventionDirection.REPLACE:
            statement = f"Controlled {target} replacement restores barrier or repair biology without inflammatory overshoot."
            observation = "Replacement rescues the prespecified phenotype across a dose range without increasing inflammatory readouts."
            refutation = "Replacement fails to rescue or causes inflammatory over-correction at target-engaging exposure."
        else:
            statement = f"The proposed {direction} direction for {target} improves the prespecified disease phenotype."
            observation = "Dose-dependent target engagement tracks with benefit in the proposed direction across matched contexts."
            refutation = "Benefit is absent, non-monotonic, or reverses direction after confirmed target engagement."
        return FalsifiablePrediction(
            statement=statement,
            required_observation=observation,
            refutation_condition=refutation,
            assay_boundary="Matched disease-relevant contexts with bidirectional and dose-response controls.",
        )
    if critic_type == FailureTaxonomy.TRANSLATION:
        return FalsifiablePrediction(
            statement=(
                f"The {target} mechanism and proposed {direction} intervention transfer from the "
                "source context to the stated Crohn's disease population and cell state."
            ),
            required_observation=(
                "The prespecified target-engagement-to-phenotype chain is reproduced in independent "
                "human Crohn's samples from the intended population."
            ),
            refutation_condition=(
                "The source-context effect disappears or reverses in intended-population human samples "
                "despite comparable target engagement."
            ),
            assay_boundary="Independent human Crohn's cohorts with explicit population and cell-state metadata.",
        )
    return FalsifiablePrediction(
        statement=(
            f"A target-engaging exposure window for {target} is separable from mechanism-based and "
            "modality-specific harm."
        ),
        required_observation=(
            "Benefit-linked target engagement occurs below prespecified cellular, organ, immune, and "
            "systemic safety thresholds with an adequate exposure margin."
        ),
        refutation_condition=(
            "A reproducible serious safety signal occurs at or below the exposure required for target "
            "engagement or phenotypic benefit."
        ),
        assay_boundary="Modality-matched safety panel plus exposure-response and reversibility controls.",
    )


class _Inputs:
    def __init__(
        self, hypothesis: ComposedHypothesis, *, mask_counterevidence: bool = False
    ):
        portfolio = load_default_ideation_store().portfolio
        literature = load_default_literature_store().snapshot
        self.hypothesis = hypothesis
        self.mask_counterevidence = mask_counterevidence
        self.claims = {
            item.id: item
            for item in literature.provisional_gold_claims
            if item.id in hypothesis.mechanism_claim_ids
        }
        self.decisions = {
            item.selected_claim_id: item
            for item in portfolio.silver_layer.decisions
            if item.selected_claim_id in hypothesis.mechanism_claim_ids
        }
        route_by_id = {item.id: item for item in portfolio.route_signals}
        self.routes = [route_by_id[item] for item in hypothesis.candidate_route_ids]

    def claims_with_theme(self, *themes: LiteratureClaimTheme) -> list[str]:
        return [
            claim_id
            for claim_id in self.hypothesis.mechanism_claim_ids
            if self.decisions[claim_id].theme in themes
        ]

    @property
    def counter_claim_ids(self) -> list[str]:
        if self.mask_counterevidence:
            return []
        return [
            claim_id
            for claim_id in self.hypothesis.mechanism_claim_ids
            if self.decisions[claim_id].polarity == ClaimPolarity.REFUTES
        ]

    def route(self, route: RecallRoute):
        return next((item for item in self.routes if item.route == route), None)


def _assessment(
    inputs: _Inputs,
    critic_type: FailureTaxonomy,
    *,
    counter_hypothesis: str,
    fatal_assumption: str,
    evidence_claim_ids: list[str],
    counterevidence_claim_ids: list[str],
    route_evidence_ids: list[str],
    evidence_gaps: list[str],
    verdict: Verdict,
    rationale: str,
    rule_id: str,
) -> CriticAssessment:
    return CriticAssessment(
        id=stable_id(
            "critic-assessment",
            f"{inputs.hypothesis.id}-{critic_type.value}",
        ),
        hypothesis_id=inputs.hypothesis.id,
        critic_type=critic_type,
        strongest_counter_hypothesis=counter_hypothesis,
        fatal_assumption=fatal_assumption,
        evidence_claim_ids=_unique(evidence_claim_ids),
        counterevidence_claim_ids=_unique(counterevidence_claim_ids),
        route_evidence_ids=_unique(route_evidence_ids),
        evidence_gaps=evidence_gaps,
        falsifiable_prediction=_prediction(inputs.hypothesis, critic_type),
        verdict=verdict,
        rationale=rationale,
        rule_id=rule_id,
    )


def _causal_critic(inputs: _Inputs) -> CriticAssessment:
    target = inputs.hypothesis.target.label
    genetic_route = inputs.route(RecallRoute.HUMAN_GENETICS)
    genetic_claims = inputs.claims_with_theme(LiteratureClaimTheme.GENETIC_ASSOCIATION)
    counters = inputs.counter_claim_ids
    if genetic_route and genetic_claims:
        verdict = Verdict.SURVIVE
        gaps: list[str] = []
        rationale = (
            "The fixed development rule found both a human-genetics route and target-grounded "
            "model-silver genetic claims. This survives only the causal critic; it does not prove "
            "therapeutic causality or direction."
        )
        rule_id = "p4.causal.genetics-route-and-claim"
    else:
        verdict = Verdict.ABSTAIN
        gaps = [
            "No conjunction of a human-genetics route and target-grounded model-silver genetic claim.",
            "Mechanistic, expression, or clinical-development association cannot substitute for causal identification.",
        ]
        rationale = (
            "The available structured inputs cannot distinguish a causal dependency from a correlated "
            "pathway marker, downstream response, or development-program association."
        )
        rule_id = "p4.causal.missing-genetic-conjunction"
    evidence = _unique([*genetic_claims, *counters])
    return _assessment(
        inputs,
        FailureTaxonomy.CAUSAL,
        counter_hypothesis=(
            f"{target} marks or follows Crohn's disease biology but is not a causal, therapeutically "
            "reachable dependency."
        ),
        fatal_assumption=(
            f"Changing {target} itself, rather than a correlated pathway state, causally changes the "
            "disease-relevant phenotype."
        ),
        evidence_claim_ids=evidence,
        counterevidence_claim_ids=[item for item in counters if item in evidence],
        route_evidence_ids=genetic_route.evidence_ids if genetic_route else [],
        evidence_gaps=gaps,
        verdict=verdict,
        rationale=rationale,
        rule_id=rule_id,
    )


def _direction_critic(inputs: _Inputs) -> CriticAssessment:
    hypothesis = inputs.hypothesis
    target = hypothesis.target.label
    counters = inputs.counter_claim_ids
    context_dependent = [
        claim_id
        for claim_id in hypothesis.mechanism_claim_ids
        if inputs.decisions[claim_id].direction == ClaimDirection.CONTEXT_DEPENDENT
    ]
    directional = [
        claim_id
        for claim_id in hypothesis.mechanism_claim_ids
        if inputs.decisions[claim_id].direction != ClaimDirection.UNKNOWN
    ]
    therapeutic = inputs.claims_with_theme(LiteratureClaimTheme.THERAPEUTIC_EFFECT)
    evidence = _unique([*directional, *counters, *therapeutic])
    if hypothesis.proposed_direction == InterventionDirection.UNKNOWN:
        verdict = Verdict.ABSTAIN
        gaps = [
            "The source hypothesis intentionally leaves intervention direction unresolved.",
            "No deterministic rule may impute direction from mixed mechanism and association claims.",
        ]
        rationale = "Direction is an explicit unresolved variable, so the critic abstains rather than guessing."
        rule_id = "p4.direction.source-direction-unknown"
    elif counters or context_dependent:
        verdict = Verdict.REVISE
        gaps = [
            "Counter or context-dependent claims prevent an unconditional intervention-direction statement.",
            "The responsive cell state, dose range, and disease context are not experimentally bounded.",
        ]
        rationale = (
            "At least one bound claim refutes or qualifies the direction. The proposed direction may "
            "remain testable, but the hypothesis must state its context boundary."
        )
        rule_id = "p4.direction.counter-or-context-dependent"
    elif hypothesis.proposed_direction == InterventionDirection.REPLACE and not therapeutic:
        verdict = Verdict.REVISE
        gaps = [
            "Mechanism claims do not directly demonstrate that replacement is the beneficial intervention direction.",
            "Dose and inflammatory over-correction boundaries are unspecified.",
        ]
        rationale = "Replacement is mechanistically plausible but is not directly supported as an intervention direction."
        rule_id = "p4.direction.replacement-without-therapeutic-test"
    else:
        verdict = Verdict.SURVIVE
        gaps = []
        rationale = (
            "All direction-informative bound claims are concordant with the proposed direction and no "
            "bound counterclaim is present. This is a development-only survival, not proof of efficacy."
        )
        rule_id = "p4.direction.concordant-without-counterclaim"
    return _assessment(
        inputs,
        FailureTaxonomy.DIRECTION,
        counter_hypothesis=(
            f"The beneficial direction for {target} is opposite, non-monotonic, or restricted to a "
            "different cell state or disease context."
        ),
        fatal_assumption=(
            f"The proposed {hypothesis.proposed_direction.value} direction has a reproducible benefit "
            "window across the stated population and cell state."
        ),
        evidence_claim_ids=evidence,
        counterevidence_claim_ids=[item for item in counters if item in evidence],
        route_evidence_ids=[],
        evidence_gaps=gaps,
        verdict=verdict,
        rationale=rationale,
        rule_id=rule_id,
    )


def _translation_critic(inputs: _Inputs) -> CriticAssessment:
    target = inputs.hypothesis.target.label
    human_claims = [
        claim_id
        for claim_id in inputs.hypothesis.mechanism_claim_ids
        if inputs.claims[claim_id].context.species.casefold() == "human"
    ]
    intervention_claims = inputs.claims_with_theme(
        LiteratureClaimTheme.THERAPEUTIC_EFFECT,
        LiteratureClaimTheme.SAFETY_LIMITATION,
    )
    clinical_route = inputs.route(RecallRoute.CLINICAL_DEVELOPMENT)
    evidence = _unique([*human_claims, *intervention_claims])
    if human_claims or clinical_route:
        verdict = Verdict.REVISE
        gaps = [
            "Available human or clinical-development evidence does not reproduce the complete target-engagement-to-phenotype chain.",
            "Population, cell-state, treatment-history, and source-context transfer boundaries remain untested.",
            "The literature layer is model-silver and not independently human-validated.",
        ]
        rationale = (
            "A human-context or clinical-development anchor exists, but it is insufficient to establish "
            "transfer to the stated Crohn's population, cell state, and intervention."
        )
        rule_id = "p4.translation.anchor-without-chain"
    else:
        verdict = Verdict.ABSTAIN
        gaps = [
            "No bound human-context claim or clinical-development route is available.",
            "Cross-species, model-system, population, and cell-state transfer cannot be assessed.",
        ]
        rationale = "The structured inputs lack a human translational anchor, so the critic abstains."
        rule_id = "p4.translation.missing-human-anchor"
    return _assessment(
        inputs,
        FailureTaxonomy.TRANSLATION,
        counter_hypothesis=(
            f"The {target} effect is specific to the source species, model, population, or cell state "
            "and does not transfer to the intended Crohn's population."
        ),
        fatal_assumption=(
            "The source evidence preserves target engagement, mechanism, and phenotypic consequence "
            "in the intended human population and cell state."
        ),
        evidence_claim_ids=evidence,
        counterevidence_claim_ids=[item for item in inputs.counter_claim_ids if item in evidence],
        route_evidence_ids=clinical_route.evidence_ids if clinical_route else [],
        evidence_gaps=gaps,
        verdict=verdict,
        rationale=rationale,
        rule_id=rule_id,
    )


def _safety_critic(inputs: _Inputs) -> CriticAssessment:
    hypothesis = inputs.hypothesis
    target = hypothesis.target.label
    safety_claims = inputs.claims_with_theme(LiteratureClaimTheme.SAFETY_LIMITATION)
    if safety_claims:
        verdict = Verdict.REVISE
        gaps = [
            "A bound safety/limitation claim exists, but indication, modality, dose, exposure, and reversibility are not resolved.",
            "The therapeutic-to-toxic exposure margin is not quantified.",
        ]
        rationale = (
            "A safety signal cannot be ignored or promoted to a universal rejection from this evidence. "
            "The hypothesis must add an exposure-window and monitoring constraint."
        )
        rule_id = "p4.safety.bound-safety-signal"
    elif hypothesis.proposed_modality == Modality.UNKNOWN:
        verdict = Verdict.ABSTAIN
        gaps = [
            "Modality is unresolved, so modality-specific safety liabilities cannot be evaluated.",
            "No target-engaging exposure window or safety evidence is bound to the hypothesis.",
        ]
        rationale = "Safety assessment is not meaningful before modality and exposure assumptions are specified."
        rule_id = "p4.safety.unknown-modality"
    else:
        verdict = Verdict.ABSTAIN
        gaps = [
            "No safety/limitation claim is bound to the hypothesis.",
            "Absence of a bound safety signal is not evidence of safety.",
            "Mechanism-based, modality-specific, organ, immune, and systemic safety margins are untested.",
        ]
        rationale = "The critic abstains because missing safety evidence must not default to survival."
        rule_id = "p4.safety.missing-safety-evidence"
    return _assessment(
        inputs,
        FailureTaxonomy.SAFETY,
        counter_hypothesis=(
            f"Target engagement for {target} produces mechanism-based or modality-specific harm at or "
            "below the exposure required for benefit."
        ),
        fatal_assumption=(
            "A clinically usable target-engagement window is separable from serious on-target, "
            "off-target, immune, organ, and systemic harm."
        ),
        evidence_claim_ids=safety_claims,
        counterevidence_claim_ids=[
            item for item in inputs.counter_claim_ids if item in safety_claims
        ],
        route_evidence_ids=[],
        evidence_gaps=gaps,
        verdict=verdict,
        rationale=rationale,
        rule_id=rule_id,
    )


def _merge_assessments(
    assessments: list[CriticAssessment],
) -> tuple[Verdict, list[FailureTaxonomy], str]:
    by_verdict: dict[Verdict, list[FailureTaxonomy]] = {}
    for item in assessments:
        by_verdict.setdefault(item.verdict, []).append(item.critic_type)
    if by_verdict.get(Verdict.REJECT):
        verdict = Verdict.REJECT
        binding = by_verdict[Verdict.REJECT]
        rationale = "At least one fixed critic rejected a fatal assumption."
    elif len(by_verdict.get(Verdict.ABSTAIN, [])) >= 2:
        verdict = Verdict.ABSTAIN
        binding = by_verdict[Verdict.ABSTAIN]
        rationale = "Two or more fixed critics lack the evidence required for a directional decision."
    elif by_verdict.get(Verdict.REVISE):
        verdict = Verdict.REVISE
        binding = by_verdict[Verdict.REVISE]
        rationale = "No critic rejected the hypothesis, but at least one requires an explicit bounded revision."
    elif by_verdict.get(Verdict.ABSTAIN):
        verdict = Verdict.ABSTAIN
        binding = by_verdict[Verdict.ABSTAIN]
        rationale = "A remaining evidence gap prevents whole-hypothesis survival."
    else:
        verdict = Verdict.SURVIVE
        binding = list(FailureTaxonomy)
        rationale = "All four fixed critics survived under the frozen development rules."
    return verdict, binding, rationale


_REVISION_FIELDS = {
    FailureTaxonomy.CAUSAL: ["causal_claim", "mechanism_chain"],
    FailureTaxonomy.DIRECTION: ["proposed_direction", "cell_state", "dose_context"],
    FailureTaxonomy.TRANSLATION: ["population", "cell_state", "translation_boundary"],
    FailureTaxonomy.SAFETY: ["proposed_modality", "exposure_window", "safety_constraints"],
}


def _build_result(
    hypothesis: ComposedHypothesis, *, mask_counterevidence: bool = False
) -> FalsificationResult:
    inputs = _Inputs(hypothesis, mask_counterevidence=mask_counterevidence)
    assessments = [
        _causal_critic(inputs),
        _direction_critic(inputs),
        _translation_critic(inputs),
        _safety_critic(inputs),
    ]
    combined, binding, rationale = _merge_assessments(assessments)
    revision_fields = _unique(
        [
            field
            for item in assessments
            if item.verdict != Verdict.SURVIVE
            for field in _REVISION_FIELDS[item.critic_type]
        ]
    )
    return FalsificationResult(
        id=stable_id(
            "falsification-result",
            hypothesis.id
            if not mask_counterevidence
            else f"{hypothesis.id}-counterevidence-masked",
        ),
        hypothesis_id=hypothesis.id,
        assessments=assessments,
        combined_verdict=combined,
        combined_rationale=rationale,
        binding_critic_types=binding,
        revision_fields=revision_fields,
    )


def build_falsification_result(
    hypothesis: ComposedHypothesis, *, mask_counterevidence: bool = False
) -> FalsificationResult:
    """Build one deterministic result, optionally masking explicit counter roles.

    Masking retains the frozen mechanism-chain documents and semantic labels except
    for their explicit counterevidence role. The default path is byte-compatible
    with the P4 artifact.
    """

    return _build_result(hypothesis, mask_counterevidence=mask_counterevidence)


def build_falsification_snapshot() -> FalsificationSnapshot:
    ideation = load_default_ideation_store().portfolio
    results = [_build_result(item) for item in ideation.hypotheses]
    assessments = [item for result in results for item in result.assessments]
    expected = len(results) * len(FailureTaxonomy)
    known_by_hypothesis = {
        item.id: set(item.mechanism_claim_ids) for item in ideation.hypotheses
    }
    references = [
        (assessment.hypothesis_id, claim_id)
        for assessment in assessments
        for claim_id in assessment.evidence_claim_ids
    ]
    reference_integrity = (
        sum(claim_id in known_by_hypothesis[hypothesis_id] for hypothesis_id, claim_id in references)
        / len(references)
        if references
        else 1.0
    )
    taxonomy_coverage = len(assessments) / expected if expected else 0.0
    rule_coverage = sum(bool(item.rule_id) for item in assessments) / len(assessments)
    leakage = sum(item.proposer_trace_used for item in assessments)
    engineering_gate = (
        len(assessments) == expected
        and taxonomy_coverage == 1.0
        and reference_integrity == 1.0
        and rule_coverage == 1.0
        and leakage == 0
        and all(item.verdict != Verdict.UNASSESSED for item in assessments)
    )
    quality = FalsificationQuality(
        hypothesis_count=len(results),
        critic_assessment_count=len(assessments),
        expected_critic_assessment_count=expected,
        taxonomy_counts=dict(Counter(item.critic_type for item in assessments)),
        verdict_counts=dict(Counter(item.verdict for item in assessments)),
        combined_verdict_counts=dict(Counter(item.combined_verdict for item in results)),
        taxonomy_coverage=taxonomy_coverage,
        claim_reference_integrity=reference_integrity,
        fixed_rule_coverage=rule_coverage,
        proposer_trace_leakage_count=leakage,
        engineering_gate_passed=engineering_gate,
        blocking_limitations=[
            "The critics are deterministic development rules, not learned or externally validated scientific judges.",
            "Inputs inherit the P3 four-target seed restriction and model-adjudicated silver literature layer.",
            "No independent expert or human-gold validation is available by design for this slice.",
            "Missing evidence produces abstain/revise; these outputs do not estimate probability of success.",
            "The falsifiable predictions are assay requirements, not completed experimental validation.",
        ],
    )
    return FalsificationSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        as_of_date=ideation.as_of_date,
        source_portfolio_id=ideation.id,
        source_portfolio_sha256=file_sha256(default_ideation_portfolio_path()),
        taxonomy=list(FailureTaxonomy),
        results=results,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY FIXED-TAXONOMY FALSIFICATION. Verdicts are deterministic, model-only, "
            "and inherit P3 model-silver limitations. They must not be used as scientific, clinical, "
            "safety, or investment validation."
        ),
    )


def render_falsification_markdown(snapshot: FalsificationSnapshot) -> str:
    portfolio = load_default_ideation_store().portfolio
    hypotheses = {item.id: item for item in portfolio.hypotheses}
    lines = [
        "# TargetIdeator P4 fixed-taxonomy falsification",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Snapshot: `{snapshot.id}`",
        f"- Source portfolio: `{snapshot.source_portfolio_id}`",
        f"- Hypotheses / critic assessments: {len(snapshot.results)} / {snapshot.quality.critic_assessment_count}",
        f"- Engineering gate: `{snapshot.quality.engineering_gate_passed}`",
        f"- Scientific validation gate: `{snapshot.quality.scientific_validation_gate_passed}`",
        "",
        "## Results",
        "",
    ]
    for result in snapshot.results:
        hypothesis = hypotheses[result.hypothesis_id]
        lines.extend(
            [
                f"### {hypothesis.target.label}: {hypothesis.proposed_direction.value} / {hypothesis.proposed_modality.value}",
                "",
                f"- Hypothesis: `{hypothesis.id}`",
                f"- Combined verdict: **{result.combined_verdict.value}**",
                f"- Binding critics: {', '.join(item.value for item in result.binding_critic_types)}",
                f"- Revision fields: {', '.join(result.revision_fields) or 'none'}",
                "",
            ]
        )
        for item in result.assessments:
            lines.extend(
                [
                    f"#### {item.critic_type.value}: {item.verdict.value}",
                    "",
                    f"- Counter-hypothesis: {item.strongest_counter_hypothesis}",
                    f"- Fatal assumption: {item.fatal_assumption}",
                    f"- Rule: `{item.rule_id}`",
                    f"- Cited claims: {', '.join(f'`{claim_id}`' for claim_id in item.evidence_claim_ids) or 'none'}",
                    f"- Refute if: {item.falsifiable_prediction.refutation_condition}",
                    "",
                ]
            )
    lines.extend(["## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in snapshot.quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums() -> dict[str, str]:
    return {
        "p3_ideation_portfolio": file_sha256(default_ideation_portfolio_path()),
        "p3_ideation_manifest": file_sha256(default_ideation_manifest_path()),
        "literature_benchmark": file_sha256(default_literature_snapshot_path()),
    }


def write_falsification_artifacts(
    output_dir: Path,
) -> tuple[FalsificationSnapshot, FalsificationManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_falsification_snapshot()
    snapshot_path = output_dir / "p4_falsification_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p4_falsification_report.md").write_text(
        render_falsification_markdown(snapshot), encoding="utf-8"
    )
    manifest = FalsificationManifest(
        snapshot_id=snapshot.id,
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        hypothesis_count=len(snapshot.results),
        critic_assessment_count=snapshot.quality.critic_assessment_count,
    )
    write_json(
        output_dir / "p4_falsification_manifest.json", manifest.model_dump(mode="json")
    )
    return snapshot, manifest


class FalsificationStore:
    def __init__(
        self,
        snapshot: FalsificationSnapshot,
        manifest: FalsificationManifest | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.snapshot_path = snapshot_path

    @classmethod
    def load(
        cls, snapshot_path: Path, manifest_path: Path | None = None
    ) -> "FalsificationStore":
        try:
            snapshot = FalsificationSnapshot.model_validate(_load_json(snapshot_path))
            manifest = (
                FalsificationManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P4 falsification artifact: {exc}") from exc
        return cls(snapshot, manifest, snapshot_path)

    def result(self, hypothesis_id: str) -> FalsificationResult | None:
        return next(
            (item for item in self.snapshot.results if item.hypothesis_id == hypothesis_id),
            None,
        )

    def quality_report(self) -> dict:
        deterministic = canonical_json_bytes(
            build_falsification_snapshot().model_dump(mode="json")
        ) == canonical_json_bytes(self.snapshot.model_dump(mode="json"))
        normalized_checksum_matches = bool(
            self.manifest
            and self.snapshot_path
            and file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
        )
        source_checksums_match = bool(
            self.manifest and self.manifest.source_checksums == _source_checksums()
        )
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "source_portfolio_id": self.snapshot.source_portfolio_id,
            "merge_policy": self.snapshot.merge_policy,
            "deterministic_rebuild_matches": deterministic,
            "normalized_checksum_matches": normalized_checksum_matches,
            "source_checksums_match": source_checksums_match,
            "use_policy": self.snapshot.use_policy,
            "warning": self.snapshot.warning,
        }


def load_default_falsification_store() -> FalsificationStore:
    return FalsificationStore.load(
        default_falsification_snapshot_path(), default_falsification_manifest_path()
    )
