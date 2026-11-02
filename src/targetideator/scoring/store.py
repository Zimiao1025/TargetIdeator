"""Build and load the deterministic, explicitly uncalibrated P5 decision engine."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.contracts.models import Modality, Verdict
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.falsification.models import CriticAssessment, FailureTaxonomy
from targetideator.falsification.store import default_falsification_snapshot_path
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ideation.models import ComposedHypothesis, RecallRoute
from targetideator.ideation.store import (
    default_ideation_portfolio_path,
    load_default_ideation_store,
)
from targetideator.io import write_json
from targetideator.revision.models import RevisionCandidate, RevisionStatus
from targetideator.revision.store import (
    default_revision_manifest_path,
    default_revision_snapshot_path,
    load_default_revision_store,
)
from targetideator.scoring.models import (
    CalibrationSummary,
    CandidateDecision,
    DecisionHead,
    DecisionHeadName,
    DecisionManifest,
    DecisionQuality,
    DecisionSnapshot,
    DecisionStatus,
    FeatureContribution,
    FeatureEffect,
    HeadUncertainty,
    ParetoStatus,
    ParetoSummary,
    RiskCoverageSummary,
)

BUILDER_VERSION = "p5-uncalibrated-multi-head-development-v1"
SNAPSHOT_ID = "ti:decision-snapshot:crohns-p5-development-v1"
CREATED_AT = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
DEFAULT_WEIGHTS = {item: 0.2 for item in DecisionHeadName}

_HEAD_TO_CRITIC = {
    DecisionHeadName.CAUSAL_RELEVANCE: FailureTaxonomy.CAUSAL,
    DecisionHeadName.CORRECT_DIRECTION: FailureTaxonomy.DIRECTION,
    DecisionHeadName.TRANSLATABLE_EFFICACY: FailureTaxonomy.TRANSLATION,
    DecisionHeadName.SAFETY_WINDOW: FailureTaxonomy.SAFETY,
}

_VERDICT_SCORE = {
    Verdict.SURVIVE: 0.75,
    Verdict.REVISE: 0.50,
    Verdict.REJECT: 0.0,
    Verdict.ABSTAIN: None,
}


def default_decision_snapshot_path() -> Path:
    return fixture_path("p5_decision_snapshot.json")


def default_decision_manifest_path() -> Path:
    return fixture_path("p5_decision_manifest.json")


def _verdict_effect(verdict: Verdict) -> FeatureEffect:
    if verdict == Verdict.SURVIVE:
        return FeatureEffect.INCREASES_READINESS
    if verdict == Verdict.REVISE:
        return FeatureEffect.DECREASES_READINESS
    return FeatureEffect.BLOCKS


def _critic_head(
    hypothesis: ComposedHypothesis,
    head_name: DecisionHeadName,
    assessment: CriticAssessment,
) -> DecisionHead:
    score = _VERDICT_SCORE[assessment.verdict]
    evidence_ids = list(
        dict.fromkeys(
            [*assessment.evidence_claim_ids, *assessment.route_evidence_ids]
        )
    )
    coverage = 1.0 if evidence_ids else 0.0
    return DecisionHead(
        id=stable_id("decision-head", f"{hypothesis.id}-{head_name.value}"),
        hypothesis_id=hypothesis.id,
        head_name=head_name,
        score=score,
        rule_id=f"p5.{head_name.value}.from-p4-verdict",
        feature_contributions=[
            FeatureContribution(
                feature_id="p4.critic_verdict",
                value=assessment.verdict.value,
                effect=_verdict_effect(assessment.verdict),
                source_ids=[assessment.id],
                rationale=(
                    "Frozen P4 critic verdict mapped to an ordinal development-readiness level: "
                    "survive=0.75, revise=0.50, reject=0.00, abstain=missing."
                ),
            ),
            FeatureContribution(
                feature_id="p4.bound_evidence_count",
                value=len(evidence_ids),
                effect=FeatureEffect.CONTEXT_ONLY,
                source_ids=evidence_ids,
                rationale=(
                    "Evidence count is exposed for audit and does not receive an additive weight or "
                    "convert dependent records into probability."
                ),
            ),
        ],
        evidence_claim_ids=assessment.evidence_claim_ids,
        route_evidence_ids=assessment.route_evidence_ids,
        evidence_coverage=coverage,
        missing_requirements=assessment.evidence_gaps,
        abstained=score is None,
        uncertainty=(
            HeadUncertainty.UNBOUNDED_MISSING
            if score is None
            else HeadUncertainty.HIGH_UNCALIBRATED
        ),
    )


def _tractability_head(
    hypothesis: ComposedHypothesis,
    route_signals,
) -> DecisionHead:
    clinical = next(
        (
            item
            for item in route_signals
            if item.route == RecallRoute.CLINICAL_DEVELOPMENT
        ),
        None,
    )
    modality_known = hypothesis.proposed_modality != Modality.UNKNOWN
    if not modality_known:
        score = None
        rule_id = "p5.modality_feasibility.unknown-modality-abstain"
        missing = [
            "A concrete modality is required before modality feasibility can be assessed.",
            "No binding, delivery, exposure, selectivity, or manufacturability evidence is available.",
        ]
    elif clinical is not None:
        score = 0.75
        rule_id = "p5.modality_feasibility.known-modality-clinical-route"
        missing = [
            "The clinical-development route establishes precedent, not feasibility for this exact direction, population, or product profile."
        ]
    else:
        score = 0.50
        rule_id = "p5.modality_feasibility.known-modality-no-clinical-route"
        missing = [
            "No target-linked clinical-development route is present.",
            "Binding, delivery, exposure, selectivity, and manufacturability remain untested.",
        ]
    route_ids = clinical.evidence_ids if clinical is not None else []
    return DecisionHead(
        id=stable_id(
            "decision-head", f"{hypothesis.id}-{DecisionHeadName.MODALITY_FEASIBILITY.value}"
        ),
        hypothesis_id=hypothesis.id,
        head_name=DecisionHeadName.MODALITY_FEASIBILITY,
        score=score,
        rule_id=rule_id,
        feature_contributions=[
            FeatureContribution(
                feature_id="p3.modality_known",
                value=modality_known,
                effect=(
                    FeatureEffect.INCREASES_READINESS
                    if modality_known
                    else FeatureEffect.BLOCKS
                ),
                source_ids=[hypothesis.id],
                rationale="Unknown modality blocks feasibility scoring; a known modality is necessary but not sufficient.",
            ),
            FeatureContribution(
                feature_id="p3.clinical_development_route_present",
                value=clinical is not None,
                effect=(
                    FeatureEffect.INCREASES_READINESS
                    if clinical is not None
                    else FeatureEffect.DECREASES_READINESS
                ),
                source_ids=([clinical.id, *route_ids] if clinical is not None else []),
                rationale="Clinical route is treated as development precedent, never as efficacy or safety proof.",
            ),
        ],
        evidence_claim_ids=[],
        route_evidence_ids=route_ids,
        evidence_coverage=(1.0 if clinical is not None else (0.5 if modality_known else 0.0)),
        missing_requirements=missing,
        abstained=score is None,
        uncertainty=(
            HeadUncertainty.UNBOUNDED_MISSING
            if score is None
            else HeadUncertainty.HIGH_UNCALIBRATED
        ),
    )


def _build_heads(
    hypothesis: ComposedHypothesis,
    assessments: list[CriticAssessment],
    route_signals,
) -> list[DecisionHead]:
    by_critic = {item.critic_type: item for item in assessments}
    heads: list[DecisionHead] = []
    for head_name in DecisionHeadName:
        if head_name == DecisionHeadName.MODALITY_FEASIBILITY:
            heads.append(_tractability_head(hypothesis, route_signals))
        else:
            heads.append(
                _critic_head(
                    hypothesis,
                    head_name,
                    by_critic[_HEAD_TO_CRITIC[head_name]],
                )
            )
    return heads


def _decision_status(
    revision: RevisionCandidate, missing: list[DecisionHeadName]
) -> tuple[DecisionStatus, ParetoStatus]:
    if not revision.eligible_for_p5_development:
        return DecisionStatus.BLOCKED_UPSTREAM, ParetoStatus.EXCLUDED_UPSTREAM
    if missing:
        return (
            DecisionStatus.ABSTAIN_MISSING_REQUIRED_HEADS,
            ParetoStatus.INCOMPARABLE_MISSING_HEADS,
        )
    return DecisionStatus.ELIGIBLE_UNRANKED, ParetoStatus.FRONTIER


def _build_decision(
    hypothesis: ComposedHypothesis,
    revision: RevisionCandidate,
    assessments: list[CriticAssessment],
    route_signals,
) -> CandidateDecision:
    heads = _build_heads(hypothesis, assessments, route_signals)
    missing = [item.head_name for item in heads if item.abstained]
    status, pareto_status = _decision_status(revision, missing)
    reasons: list[str] = []
    if status == DecisionStatus.BLOCKED_UPSTREAM:
        reasons.append(
            f"P4.1 revision status is {revision.revision_status.value}; upstream evidence gaps remain binding."
        )
    if missing:
        reasons.extend(
            f"Required head {item.head_name.value} abstained: {'; '.join(item.missing_requirements)}"
            for item in heads
            if item.abstained
        )
    utility = (
        sum((item.score or 0.0) * DEFAULT_WEIGHTS[item.head_name] for item in heads)
        if status == DecisionStatus.ELIGIBLE_UNRANKED
        else None
    )
    return CandidateDecision(
        id=stable_id("candidate-decision", hypothesis.id),
        hypothesis_id=hypothesis.id,
        revision_candidate_id=revision.id,
        upstream_revision_status=revision.revision_status,
        heads=heads,
        missing_required_heads=missing,
        decision_status=status,
        abstention_reasons=reasons,
        weighted_utility=utility,
        default_weights=DEFAULT_WEIGHTS,
        pareto_status=pareto_status,
    )


def _dominates(left: CandidateDecision, right: CandidateDecision) -> bool:
    left_scores = {item.head_name: item.score for item in left.heads}
    right_scores = {item.head_name: item.score for item in right.heads}
    return all(left_scores[item] >= right_scores[item] for item in DecisionHeadName) and any(
        left_scores[item] > right_scores[item] for item in DecisionHeadName
    )


def _assign_pareto(decisions: list[CandidateDecision]) -> list[CandidateDecision]:
    complete = [
        item
        for item in decisions
        if item.decision_status == DecisionStatus.ELIGIBLE_UNRANKED
    ]
    updated: list[CandidateDecision] = []
    for decision in decisions:
        if decision not in complete:
            updated.append(decision)
            continue
        dominated = any(
            other.id != decision.id and _dominates(other, decision)
            for other in complete
        )
        updated.append(
            decision.model_copy(
                update={
                    "pareto_status": (
                        ParetoStatus.DOMINATED if dominated else ParetoStatus.FRONTIER
                    )
                }
            )
        )
    return updated


def build_decision_snapshot() -> DecisionSnapshot:
    portfolio = load_default_ideation_store().portfolio
    revisions = load_default_revision_store().snapshot
    from targetideator.falsification.store import load_default_falsification_store

    falsification = load_default_falsification_store().snapshot
    hypotheses = {item.id: item for item in portfolio.hypotheses}
    results = {item.hypothesis_id: item for item in falsification.results}
    route_by_id = {item.id: item for item in portfolio.route_signals}
    decisions = []
    for revision in revisions.candidates:
        hypothesis = hypotheses[revision.source_hypothesis_id]
        result = results[hypothesis.id]
        routes = [route_by_id[item] for item in hypothesis.candidate_route_ids]
        decisions.append(
            _build_decision(hypothesis, revision, result.assessments, routes)
        )
    decisions = _assign_pareto(decisions)
    complete = [
        item for item in decisions if item.decision_status == DecisionStatus.ELIGIBLE_UNRANKED
    ]
    frontier = [item for item in complete if item.pareto_status == ParetoStatus.FRONTIER]
    dominated = [item for item in complete if item.pareto_status == ParetoStatus.DOMINATED]
    incomparable = [
        item
        for item in decisions
        if item.pareto_status == ParetoStatus.INCOMPARABLE_MISSING_HEADS
    ]
    excluded = [
        item for item in decisions if item.pareto_status == ParetoStatus.EXCLUDED_UPSTREAM
    ]
    pareto = ParetoSummary(
        head_order=list(DecisionHeadName),
        fully_scorable_candidate_ids=[item.id for item in complete],
        frontier_candidate_ids=[item.id for item in frontier],
        dominated_candidate_ids=[item.id for item in dominated],
        incomparable_missing_head_candidate_ids=[item.id for item in incomparable],
        excluded_upstream_candidate_ids=[item.id for item in excluded],
        default_weights=DEFAULT_WEIGHTS,
    )
    heads = [head for item in decisions for head in item.heads]
    observed = sum(item.score is not None for item in heads)
    expected = len(decisions) * len(DecisionHeadName)
    probability_outputs = sum(item.probability_interpretation_allowed for item in heads)
    engineering_gate = (
        len(heads) == expected
        and all(item.calibration_status == "not_calibrated_no_outcome_labels" for item in heads)
        and probability_outputs == 0
        and all(item.rank is None and item.not_ranked for item in decisions)
        and portfolio.quality.post_cutoff_leakage_count == 0
    )
    quality = DecisionQuality(
        candidate_count=len(decisions),
        head_count=len(heads),
        expected_head_count=expected,
        head_counts=dict(Counter(item.head_name for item in heads)),
        observed_head_score_count=observed,
        abstained_head_count=len(heads) - observed,
        head_score_coverage=observed / expected if expected else 0.0,
        upstream_blocked_candidate_count=sum(
            item.decision_status == DecisionStatus.BLOCKED_UPSTREAM for item in decisions
        ),
        missing_head_abstention_candidate_count=sum(
            item.decision_status == DecisionStatus.ABSTAIN_MISSING_REQUIRED_HEADS
            for item in decisions
        ),
        fully_scorable_candidate_count=len(complete),
        pareto_frontier_candidate_count=len(frontier),
        probability_output_count=probability_outputs,
        post_cutoff_leakage_count=portfolio.quality.post_cutoff_leakage_count,
        engineering_gate_passed=engineering_gate,
        blocking_limitations=[
            "No temporal outcome labels exist, so scores are ordinal development-readiness levels rather than probabilities.",
            "Calibration, confidence intervals, Brier/ECE, PR-AUC, and risk-coverage metrics are unavailable by construction.",
            "Required-head missingness propagates to abstention; no candidate is currently fully scorable.",
            "The five-candidate universe is restricted to the P3 frozen seed panel and cannot support model fitting.",
            "P5 inherits model-silver literature, deterministic P4 critics, and unvalidated P4.1 constraints.",
        ],
    )
    return DecisionSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        as_of_date=portfolio.as_of_date,
        source_portfolio_id=portfolio.id,
        source_falsification_snapshot_id=falsification.id,
        source_revision_snapshot_id=revisions.id,
        source_revision_sha256=file_sha256(default_revision_snapshot_path()),
        decisions=decisions,
        calibration=CalibrationSummary(),
        risk_coverage=RiskCoverageSummary(),
        pareto=pareto,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY UNCALIBRATED MULTI-HEAD OUTPUT. Scores are fixed ordinal readiness "
            "levels, not probabilities. Missing heads are not imputed, no candidate is scientifically "
            "ranked, and calibration/risk claims are prohibited until temporal outcomes exist."
        ),
    )


def render_decision_markdown(snapshot: DecisionSnapshot) -> str:
    lines = [
        "# TargetIdeator P5 uncalibrated multi-head decision engine",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Snapshot: `{snapshot.id}`",
        f"- Candidates / heads: {len(snapshot.decisions)} / {snapshot.quality.head_count}",
        f"- Observed head coverage: {snapshot.quality.head_score_coverage:.3f}",
        f"- Fully scorable / Pareto frontier: {snapshot.quality.fully_scorable_candidate_count} / {snapshot.quality.pareto_frontier_candidate_count}",
        f"- Calibration fitted: `{snapshot.calibration.fitted}`",
        f"- Engineering gate: `{snapshot.quality.engineering_gate_passed}`",
        f"- Formal P5 gate: `{snapshot.quality.formal_p5_gate_passed}`",
        "",
        "## Candidate decisions",
        "",
    ]
    for decision in snapshot.decisions:
        lines.extend(
            [
                f"### `{decision.hypothesis_id}`",
                "",
                f"- Status: `{decision.decision_status.value}`",
                f"- Pareto: `{decision.pareto_status.value}`",
                f"- Utility: `{decision.weighted_utility}`",
                f"- Missing heads: {', '.join(item.value for item in decision.missing_required_heads) or 'none'}",
                "",
            ]
        )
        for head in decision.heads:
            lines.extend(
                [
                    f"#### {head.head_name.value}",
                    "",
                    f"- Score: `{head.score}` ({head.score_scale})",
                    f"- Abstained: `{head.abstained}`",
                    f"- Evidence coverage: `{head.evidence_coverage}`",
                    f"- Rule: `{head.rule_id}`",
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
        "p4_falsification_snapshot": file_sha256(default_falsification_snapshot_path()),
        "p4_revision_snapshot": file_sha256(default_revision_snapshot_path()),
        "p4_revision_manifest": file_sha256(default_revision_manifest_path()),
    }


def write_decision_artifacts(
    output_dir: Path,
) -> tuple[DecisionSnapshot, DecisionManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = build_decision_snapshot()
    snapshot_path = output_dir / "p5_decision_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_decision_report.md").write_text(
        render_decision_markdown(snapshot), encoding="utf-8"
    )
    manifest = DecisionManifest(
        snapshot_id=snapshot.id,
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        candidate_count=len(snapshot.decisions),
        head_count=snapshot.quality.head_count,
    )
    write_json(output_dir / "p5_decision_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class DecisionStore:
    def __init__(
        self,
        snapshot: DecisionSnapshot,
        manifest: DecisionManifest | None = None,
        snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.snapshot_path = snapshot_path

    @classmethod
    def load(
        cls, snapshot_path: Path, manifest_path: Path | None = None
    ) -> "DecisionStore":
        try:
            snapshot = DecisionSnapshot.model_validate(_load_json(snapshot_path))
            manifest = (
                DecisionManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P5 decision artifact: {exc}") from exc
        return cls(snapshot, manifest, snapshot_path)

    def decision(self, hypothesis_id: str) -> CandidateDecision | None:
        return next(
            (item for item in self.snapshot.decisions if item.hypothesis_id == hypothesis_id),
            None,
        )

    def utility_scenario(
        self, weights: dict[DecisionHeadName, float]
    ) -> dict:
        if set(weights) != set(DecisionHeadName):
            raise ValueError("utility scenario must provide all five head weights")
        if any(value < 0 for value in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError("utility weights must be non-negative with a positive total")
        total = sum(weights.values())
        normalized = {key: value / total for key, value in weights.items()}
        rows = []
        for decision in self.snapshot.decisions:
            utility = None
            if decision.decision_status == DecisionStatus.ELIGIBLE_UNRANKED:
                utility = sum(
                    item.score * normalized[item.head_name] for item in decision.heads
                )
            rows.append(
                {
                    "hypothesis_id": decision.hypothesis_id,
                    "decision_status": decision.decision_status.value,
                    "utility": utility,
                    "rank": None,
                    "abstention_reasons": decision.abstention_reasons,
                }
            )
        return {
            "weights": {key.value: value for key, value in normalized.items()},
            "results": rows,
            "ranking_performed": False,
            "warning": (
                "Utilities are returned only for complete unblocked candidates. Missing heads are "
                "never renormalized away, and this endpoint does not create a scientific ranking."
            ),
        }

    def quality_report(self) -> dict:
        deterministic = canonical_json_bytes(
            build_decision_snapshot().model_dump(mode="json")
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
            "calibration": self.snapshot.calibration.model_dump(mode="json"),
            "risk_coverage": self.snapshot.risk_coverage.model_dump(mode="json"),
            "pareto": self.snapshot.pareto.model_dump(mode="json"),
            "deterministic_rebuild_matches": deterministic,
            "normalized_checksum_matches": normalized_checksum_matches,
            "source_checksums_match": source_checksums_match,
            "use_policy": self.snapshot.use_policy,
            "warning": self.snapshot.warning,
        }


def load_default_decision_store() -> DecisionStore:
    return DecisionStore.load(
        default_decision_snapshot_path(), default_decision_manifest_path()
    )
