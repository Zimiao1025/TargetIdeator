"""Build and load the deterministic P3 model-silver development portfolio."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.claims.models import ClaimKind, ClaimPolarity
from targetideator.claims.store import (
    default_claim_graph_snapshot_path,
    load_default_claim_graph_store,
)
from targetideator.contracts.models import InterventionDirection
from targetideator.evidence.models import CanonicalEntity
from targetideator.evidence.store import (
    _load_json,
    default_snapshot_path,
    file_sha256,
    load_default_store,
)
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ideation.models import (
    CandidateRouteSignal,
    ComposedHypothesis,
    IdeationCandidate,
    IdeationManifest,
    IdeationPortfolio,
    IdeationQuality,
    ModelSilverDecision,
    ModelSilverLiteratureLayer,
    RecallRoute,
    SilverSelectionAction,
)
from targetideator.io import load_bundle, write_json
from targetideator.literature.comment_resolution import (
    default_comment_resolution_path,
    load_default_comment_resolution,
)
from targetideator.literature.review import default_review_batch_path
from targetideator.literature.store import (
    default_literature_snapshot_path,
    load_default_literature_store,
)

BUILDER_VERSION = "p3-model-silver-union-v1"
PORTFOLIO_ID = "ti:ideation-portfolio:crohns-model-silver-development-v1"
SILVER_LAYER_ID = "ti:literature-silver:crohns-fixed-30-model-resolution-v1"
CREATED_AT = datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc)


def default_ideation_portfolio_path() -> Path:
    return fixture_path("p3_ideation_portfolio.json")


def default_ideation_manifest_path() -> Path:
    return fixture_path("p3_ideation_manifest.json")


def build_model_silver_layer() -> ModelSilverLiteratureLayer:
    """Freeze model/comment resolution as silver without claiming human adjudication."""

    literature = load_default_literature_store()
    resolution = load_default_comment_resolution()
    known_claims = {item.id for item in literature.snapshot.provisional_gold_claims}
    decisions: list[ModelSilverDecision] = []
    selected_claim_ids: list[str] = []
    for item in resolution.resolutions:
        if item.proposed_disposition.value == "accept":
            action = SilverSelectionAction.RETAIN_ORIGINAL
            selected_claim_id = item.claim_id
        elif item.proposed_disposition.value == "revise" and item.replacement_claim_id:
            action = SilverSelectionAction.USE_EXISTING_REPLACEMENT
            selected_claim_id = item.replacement_claim_id
        else:
            action = SilverSelectionAction.EXCLUDE
            selected_claim_id = None
        if selected_claim_id and selected_claim_id not in known_claims:
            raise ValueError(f"model-silver selection references unknown claim {selected_claim_id}")
        if selected_claim_id:
            selected_claim_ids.append(selected_claim_id)
        decisions.append(
            ModelSilverDecision(
                task_id=item.task_id,
                original_claim_id=item.claim_id,
                disposition=item.proposed_disposition,
                selection_action=action,
                selected_claim_id=selected_claim_id,
                target_grounding=item.proposed_target_grounding,
                evidence_role=item.proposed_evidence_role,
                theme=item.proposed_theme if selected_claim_id else None,
                polarity=item.proposed_polarity if selected_claim_id else None,
                direction=item.proposed_direction if selected_claim_id else None,
                rationale=item.rationale,
                provenance_sources=[
                    resolution.review_batch_id,
                    resolution.id,
                    "updated-expert-reports:process-qa-only",
                ],
            )
        )
    return ModelSilverLiteratureLayer(
        id=SILVER_LAYER_ID,
        created_at=CREATED_AT,
        source_snapshot_id=literature.snapshot.id,
        source_review_batch_id=resolution.review_batch_id,
        source_comment_resolution_id=resolution.id,
        decisions=decisions,
        selected_claim_ids=selected_claim_ids,
        selected_claim_count=len(selected_claim_ids),
        excluded_claim_count=len(decisions) - len(selected_claim_ids),
        warning=(
            "Model-adjudicated silver for engineering and hypothesis development only. It is not "
            "human gold, has no independent expert verification, and cannot support performance or "
            "scientific-validity claims."
        ),
    )


def _target_panel() -> list[CanonicalEntity]:
    literature = load_default_literature_store()
    targets = {
        item.target.identifier: item.target
        for item in literature.snapshot.provisional_gold_claims
    }
    return [targets[key] for key in sorted(targets, key=lambda item: targets[item].label)]


def _rank_signals(signals: list[CandidateRouteSignal]) -> list[CandidateRouteSignal]:
    ranked: list[CandidateRouteSignal] = []
    for route in RecallRoute:
        route_signals = sorted(
            (item for item in signals if item.route == route),
            key=lambda item: (-item.route_score, item.target.label, item.id),
        )
        ranked.extend(
            item.model_copy(update={"route_rank": rank})
            for rank, item in enumerate(route_signals, start=1)
        )
    return sorted(ranked, key=lambda item: (item.route.value, item.route_rank, item.id))


def _open_targets_signals(
    targets: list[CanonicalEntity], as_of_date, datatype: str, route: RecallRoute
) -> list[CandidateRouteSignal]:
    store = load_default_store()
    signals: list[CandidateRouteSignal] = []
    for target in targets:
        query = store.query("MONDO:0005011", target.identifier, as_of_date)
        records = sorted(
            (item for item in query.records if item.datatype_id == datatype),
            key=lambda item: (-(item.score or 0.0), item.id),
        )
        if not records:
            continue
        signals.append(
            CandidateRouteSignal(
                id=stable_id("candidate-route", f"{route.value}-{target.label}"),
                target=target,
                route=route,
                route_score=max(item.score or 0.0 for item in records),
                route_rank=1,
                evidence_ids=[item.id for item in records[:10]],
                source_snapshot_ids=[store.snapshot.source.id],
                retrospective_valid=query.retrospective_valid,
                limitations=[
                    query.warning,
                    "Route score is the maximum source score within the frozen four-target panel; "
                    "it is not a calibrated probability.",
                ],
            )
        )
    return signals


def _clinical_signals(
    targets: list[CanonicalEntity], as_of_date
) -> list[CandidateRouteSignal]:
    store = load_default_claim_graph_store()
    rows: list[tuple[CanonicalEntity, object, list]] = []
    for target in targets:
        query = store.query("MONDO:0005011", target.identifier, as_of_date)
        claims = [
            item for item in query.claims if item.kind == ClaimKind.CLINICAL_DEVELOPMENT_ASSERTION
        ]
        if claims:
            rows.append((target, query, claims))
    maximum = max((row[1].independent_evidence_count for row in rows), default=1)
    signals = []
    for target, query, claims in rows:
        signals.append(
            CandidateRouteSignal(
                id=stable_id("candidate-route", f"clinical-development-{target.label}"),
                target=target,
                route=RecallRoute.CLINICAL_DEVELOPMENT,
                route_score=query.independent_evidence_count / maximum,
                route_rank=1,
                evidence_ids=[item.id for item in claims],
                supporting_claim_ids=[item.id for item in claims],
                source_snapshot_ids=[store.snapshot.id],
                retrospective_valid=query.retrospective_valid,
                limitations=[
                    query.warning,
                    "Clinical route score reflects dependency-corrected trial-family count, not efficacy.",
                ],
            )
        )
    return signals


def _literature_signals(
    targets: list[CanonicalEntity], silver: ModelSilverLiteratureLayer, as_of_date
) -> list[CandidateRouteSignal]:
    store = load_default_literature_store()
    claims = {item.id: item for item in store.snapshot.provisional_gold_claims}
    decisions = {
        item.selected_claim_id: item for item in silver.decisions if item.selected_claim_id
    }
    rows: list[tuple[CanonicalEntity, list[str]]] = []
    for target in targets:
        selected = [
            claim_id
            for claim_id in silver.selected_claim_ids
            if claims[claim_id].target.identifier == target.identifier
            and claims[claim_id].available_on <= as_of_date
        ]
        if selected:
            rows.append((target, selected))
    maximum = max((len(item[1]) for item in rows), default=1)
    signals = []
    for target, selected in rows:
        counter = [
            claim_id
            for claim_id in selected
            if decisions[claim_id].polarity == ClaimPolarity.REFUTES
        ]
        supporting = [claim_id for claim_id in selected if claim_id not in counter]
        signals.append(
            CandidateRouteSignal(
                id=stable_id("candidate-route", f"literature-mechanism-{target.label}"),
                target=target,
                route=RecallRoute.LITERATURE_MECHANISM,
                route_score=len(selected) / maximum,
                route_rank=1,
                evidence_ids=selected,
                supporting_claim_ids=supporting,
                counterevidence_claim_ids=counter,
                source_snapshot_ids=[store.snapshot.id, silver.id],
                retrospective_valid=True,
                limitations=[
                    silver.warning,
                    "Only 30 fixed review tasks contribute; the remaining 120 provisional claims "
                    "are excluded from this P3 development route.",
                ],
            )
        )
    return signals


def build_ideation_portfolio() -> IdeationPortfolio:
    bundle = load_bundle()
    brief = bundle.disease_brief
    targets = _target_panel()
    silver = build_model_silver_layer()
    signals = [
        *_open_targets_signals(
            targets, brief.as_of_date, "genetic_association", RecallRoute.HUMAN_GENETICS
        ),
        *_clinical_signals(targets, brief.as_of_date),
        *_open_targets_signals(
            targets, brief.as_of_date, "rna_expression", RecallRoute.EXPRESSION_CONTEXT
        ),
        *_literature_signals(targets, silver, brief.as_of_date),
    ]
    signals = _rank_signals(signals)
    signals_by_target: dict[str, list[CandidateRouteSignal]] = {}
    for signal in signals:
        signals_by_target.setdefault(signal.target.identifier, []).append(signal)
    candidates: list[IdeationCandidate] = []
    all_routes = set(RecallRoute)
    for target in targets:
        target_signals = signals_by_target.get(target.identifier, [])
        present = {item.route for item in target_signals}
        gaps = [f"No current signal from route: {route.value}." for route in sorted(all_routes - present)]
        gaps.extend(
            [
                "Candidate universe is restricted to the four frozen seed targets.",
                "No independent human validation is available for the model-silver literature route.",
            ]
        )
        candidates.append(
            IdeationCandidate(
                id=stable_id("ideation-candidate", f"crohns-{target.label}"),
                disease=brief.disease,
                target=target,
                route_signals=target_signals,
                route_count=len(target_signals),
                information_gaps=gaps,
            )
        )
    candidate_by_target = {item.target.identifier: item for item in candidates}
    hypotheses: list[ComposedHypothesis] = []
    for template in sorted(bundle.hypotheses, key=lambda item: (item.target.entity.label, item.id)):
        target = next(item for item in targets if item.label == template.target.entity.label)
        candidate = candidate_by_target[target.identifier]
        literature_signal = next(
            item for item in candidate.route_signals if item.route == RecallRoute.LITERATURE_MECHANISM
        )
        gaps = list(candidate.information_gaps)
        gaps.append("Cell-state specificity is inherited from an illustrative seed template, not inferred.")
        if template.intervention.direction == InterventionDirection.UNKNOWN:
            gaps.append("Intervention direction remains unknown and requires experimental resolution.")
        if template.intervention.modality.value == "unknown":
            gaps.append("Modality remains unknown and is not imputed by the composer.")
        hypotheses.append(
            ComposedHypothesis(
                id=stable_id("composed-hypothesis", f"model-silver-{template.id}"),
                template_source_hypothesis_id=template.id,
                disease=brief.disease,
                target=target,
                population=brief.population,
                cell_state=template.cell_state,
                proposed_direction=template.intervention.direction,
                proposed_modality=template.intervention.modality,
                mechanism_claim_ids=literature_signal.evidence_ids,
                supporting_claim_ids=literature_signal.supporting_claim_ids,
                counterevidence_claim_ids=literature_signal.counterevidence_claim_ids,
                candidate_route_ids=[item.id for item in candidate.route_signals],
                information_gaps=gaps,
            )
        )
    known_claims = set(silver.selected_claim_ids)
    bound_claims = [
        claim_id for item in hypotheses for claim_id in item.mechanism_claim_ids
    ]
    binding_coverage = (
        sum(item in known_claims for item in bound_claims) / len(bound_claims)
        if bound_claims
        else 0.0
    )
    route_counts = dict(Counter(item.route for item in signals))
    all_routes_nonzero = all(route_counts.get(route, 0) > 0 for route in RecallRoute)
    leakage = sum(
        claim.available_on > brief.as_of_date
        for claim in load_default_literature_store().snapshot.provisional_gold_claims
        if claim.id in known_claims
    )
    fixed_recall = len(candidates) / len(targets) if targets else 0.0
    engineering_gate = (
        fixed_recall == 1.0
        and all_routes_nonzero
        and binding_coverage == 1.0
        and leakage == 0
        and silver.selected_claim_count > 0
    )
    quality = IdeationQuality(
        fixed_seed_target_count=len(targets),
        recalled_seed_target_count=len(candidates),
        fixed_seed_recall=fixed_recall,
        candidate_count=len(candidates),
        hypothesis_count=len(hypotheses),
        route_candidate_counts=route_counts,
        all_routes_nonzero=all_routes_nonzero,
        mechanism_claim_binding_coverage=binding_coverage,
        post_cutoff_leakage_count=leakage,
        model_silver_claim_count=silver.selected_claim_count,
        minimum_portfolio_size_met=len(hypotheses) >= 10,
        engineering_gate_passed=engineering_gate,
        blocking_limitations=[
            "No human-reviewed gold or independent expert adjudication is available.",
            "The candidate universe is the frozen four-target seed panel, so this is not open-world discovery.",
            "The portfolio contains fewer than the planned 10-20 hypotheses.",
            "Open Targets 26.09 signals are a frozen current engineering snapshot, not retrospective evidence.",
            "Expression Atlas records are not a disease-relevant single-cell/pathway/network atlas.",
        ],
    )
    return IdeationPortfolio(
        id=PORTFOLIO_ID,
        created_at=CREATED_AT,
        as_of_date=brief.as_of_date,
        disease_brief_id=brief.id,
        source_snapshot_ids=[
            load_default_store().snapshot.source.id,
            load_default_claim_graph_store().snapshot.id,
            load_default_literature_store().snapshot.id,
            silver.id,
        ],
        silver_layer=silver,
        route_signals=signals,
        candidates=candidates,
        hypotheses=hypotheses,
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY MODEL-SILVER PORTFOLIO. Candidate recall and composed hypotheses "
            "are unranked, limited to the seed panel, and not independently validated. Do not use "
            "for scientific, clinical, or investment decisions."
        ),
    )


def render_ideation_portfolio_markdown(portfolio: IdeationPortfolio) -> str:
    lines = [
        "# TargetIdeator P3 model-silver development portfolio",
        "",
        f"> {portfolio.warning}",
        "",
        f"- Portfolio: `{portfolio.id}`",
        f"- As of: `{portfolio.as_of_date.isoformat()}`",
        f"- Candidates / hypotheses: {len(portfolio.candidates)} / {len(portfolio.hypotheses)}",
        f"- Model-silver claims: {portfolio.silver_layer.selected_claim_count}",
        f"- Engineering gate: `{portfolio.quality.engineering_gate_passed}`",
        f"- Scientific validation gate: `{portfolio.quality.scientific_validation_gate_passed}`",
        "",
        "## Route coverage",
        "",
    ]
    for route, count in sorted(
        portfolio.quality.route_candidate_counts.items(), key=lambda item: item[0].value
    ):
        lines.append(f"- `{route.value}`: {count} targets")
    lines.extend(["", "## Unranked hypotheses", ""])
    for item in portfolio.hypotheses:
        lines.extend(
            [
                f"### {item.target.label}: {item.proposed_direction.value} / {item.proposed_modality.value}",
                "",
                f"- ID: `{item.id}`",
                f"- Template: `{item.template_source_hypothesis_id}`",
                f"- Mechanism claims: {len(item.mechanism_claim_ids)}",
                f"- Supporting / counter: {len(item.supporting_claim_ids)} / {len(item.counterevidence_claim_ids)}",
                f"- Cell state: {item.cell_state}",
                "- Information gaps:",
                *[f"  - {gap}" for gap in item.information_gaps],
                "",
            ]
        )
    lines.extend(["## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in portfolio.quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums() -> dict[str, str]:
    paths = {
        "opentargets_snapshot": default_snapshot_path(),
        "claim_graph_snapshot": default_claim_graph_snapshot_path(),
        "literature_snapshot": default_literature_snapshot_path(),
        "literature_review_batch": default_review_batch_path(),
        "literature_comment_resolution": default_comment_resolution_path(),
    }
    return {name: file_sha256(path) for name, path in paths.items()}


def write_ideation_artifacts(
    output_dir: Path,
) -> tuple[IdeationPortfolio, IdeationManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    portfolio = build_ideation_portfolio()
    portfolio_path = output_dir / "p3_ideation_portfolio.json"
    markdown_path = output_dir / "p3_ideation_portfolio.md"
    write_json(portfolio_path, portfolio.model_dump(mode="json"))
    markdown_path.write_text(render_ideation_portfolio_markdown(portfolio), encoding="utf-8")
    manifest = IdeationManifest(
        portfolio_id=portfolio.id,
        normalized_path=portfolio_path.name,
        normalized_sha256=file_sha256(portfolio_path),
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        candidate_count=len(portfolio.candidates),
        hypothesis_count=len(portfolio.hypotheses),
    )
    write_json(output_dir / "p3_ideation_manifest.json", manifest.model_dump(mode="json"))
    return portfolio, manifest


class IdeationStore:
    def __init__(
        self,
        portfolio: IdeationPortfolio,
        manifest: IdeationManifest | None = None,
        portfolio_path: Path | None = None,
    ):
        self.portfolio = portfolio
        self.manifest = manifest
        self.portfolio_path = portfolio_path

    @classmethod
    def load(
        cls, portfolio_path: Path, manifest_path: Path | None = None
    ) -> "IdeationStore":
        try:
            portfolio = IdeationPortfolio.model_validate(_load_json(portfolio_path))
            manifest = (
                IdeationManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid P3 ideation artifact: {exc}") from exc
        return cls(portfolio, manifest, portfolio_path)

    def quality_report(self) -> dict:
        deterministic = canonical_json_bytes(build_ideation_portfolio().model_dump(mode="json")) == canonical_json_bytes(
            self.portfolio.model_dump(mode="json")
        )
        normalized_checksum_matches = bool(
            self.manifest
            and self.portfolio_path
            and file_sha256(self.portfolio_path) == self.manifest.normalized_sha256
        )
        source_checksums_match = bool(
            self.manifest and self.manifest.source_checksums == _source_checksums()
        )
        return {
            **self.portfolio.quality.model_dump(mode="json"),
            "portfolio_id": self.portfolio.id,
            "annotation_layer": self.portfolio.silver_layer.annotation_layer,
            "selected_claim_count": self.portfolio.silver_layer.selected_claim_count,
            "excluded_review_task_count": self.portfolio.silver_layer.excluded_claim_count,
            "human_review_count": self.portfolio.silver_layer.human_review_count,
            "deterministic_rebuild_matches": deterministic,
            "normalized_checksum_matches": normalized_checksum_matches,
            "source_checksums_match": source_checksums_match,
            "use_policy": self.portfolio.use_policy,
            "warning": self.portfolio.warning,
        }


def load_default_ideation_store() -> IdeationStore:
    return IdeationStore.load(
        default_ideation_portfolio_path(), default_ideation_manifest_path()
    )
