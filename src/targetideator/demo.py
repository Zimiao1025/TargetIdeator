"""Read-only FastAPI demo for inspecting the frozen P0.2 hypothesis contract."""

from __future__ import annotations

import html
import re
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from targetideator.claim_demo import claim_graph_page, claim_graph_payload, claim_graph_store
from targetideator.dossier import WARNING, bundle_json
from targetideator.io import load_bundle
from targetideator.p1_demo import evidence_page, evidence_payload, evidence_store
from targetideator.historical_demo import (
    historical_page,
    historical_payload,
    historical_store,
)
from targetideator.clinical_demo import (
    clinical_page,
    clinical_payload,
    clinical_store,
)
from targetideator.literature_demo import literature_page, literature_payload, literature_store
from targetideator.ideation_demo import ideation_page, ideation_payload, ideation_store
from targetideator.falsification_demo import (
    falsification_page,
    falsification_payload,
    falsification_store,
)
from targetideator.revision_demo import revision_page, revision_payload, revision_store
from targetideator.decision_demo import decision_page, decision_payload, decision_store
from targetideator.outcome_demo import outcome_page, outcome_payload, outcome_store
from targetideator.broad_outcome_demo import (
    broad_outcome_page,
    broad_outcome_payload,
    broad_outcome_store,
)
from targetideator.identity_demo import identity_page, identity_payload, identity_store
from targetideator.mapping_audit_demo import (
    DIMENSIONS as MAPPING_AUDIT_DIMENSIONS,
    mapping_audit_page,
    mapping_audit_payload,
    mapping_audit_store,
)
from targetideator.drug_identity_demo import (
    drug_identity_page,
    drug_identity_payload,
    drug_identity_store,
)
from targetideator.assertion_history_demo import (
    assertion_history_page,
    assertion_history_payload,
    assertion_history_store,
)
from targetideator.independent_assertion_demo import (
    independent_assertion_page,
    independent_assertion_payload,
    independent_assertion_store,
)
from targetideator.support_audit_demo import (
    support_audit_page,
    support_audit_payload,
    support_audit_store,
)
from targetideator.selection_audit_demo import (
    selection_audit_page,
    selection_audit_payload,
    selection_audit_store,
)
from targetideator.evaluation_demo import (
    evaluation_page,
    evaluation_payload,
    evaluation_store,
)
from targetideator.robustness_demo import (
    robustness_page,
    robustness_payload,
    robustness_store,
)
from targetideator.cohort_stress_demo import (
    cohort_stress_page,
    cohort_stress_payload,
    cohort_stress_store,
)
from targetideator.paired_control_demo import (
    paired_control_page,
    paired_control_payload,
    paired_control_store,
)
from targetideator.counterevidence_ablation_demo import (
    counterevidence_ablation_page,
    counterevidence_ablation_payload,
    counterevidence_ablation_store,
)
from targetideator.claim_synthesis_demo import (
    claim_synthesis_page,
    claim_synthesis_payload,
    claim_synthesis_store,
)
from targetideator.paper_bundle_demo import (
    paper_bundle_page,
    paper_bundle_payload,
    paper_bundle_store,
)
from targetideator.release_audit_demo import (
    release_audit_page,
    release_audit_payload,
    release_audit_store,
)
from targetideator.packaging_split_demo import (
    packaging_split_page,
    packaging_split_payload,
    packaging_split_store,
)
from targetideator.hydration_demo import (
    hydration_page,
    hydration_payload,
    hydration_status,
    hydration_store,
)
from targetideator.retained_fixture_demo import (
    retained_fixture_page,
    retained_fixture_payload,
    retained_fixture_store,
)
from targetideator.disposition_demo import (
    fixture_disposition_page,
    fixture_disposition_payload,
    fixture_disposition_store,
)
from targetideator.execution_plan_demo import (
    execution_plan_page,
    execution_plan_payload,
    execution_plan_store,
)
from targetideator.execution_replay_demo import (
    execution_replay_page,
    execution_replay_payload,
    execution_replay_store,
)
from targetideator.replay_hardening_demo import (
    replay_hardening_page,
    replay_hardening_payload,
    replay_hardening_store,
)
from targetideator.package_convergence_demo import (
    canonical_acceptance_store,
    package_convergence_page,
    package_convergence_payload,
    package_convergence_snapshot_id_or_status,
    package_convergence_store,
)
from targetideator.scoring.models import DecisionHeadName
from targetideator.literature.review import load_default_review_batch, review_quality_report
from targetideator.literature.comment_resolution import (
    comment_resolution_quality_report,
    load_default_comment_resolution,
)
from targetideator.literature.human_review import (
    assess_human_review_readiness,
    build_human_review_draft,
)


def _page() -> str:
    bundle = load_bundle()
    claims = {claim.id: claim for claim in bundle.claims}
    decisions = {decision.hypothesis_id: decision for decision in bundle.decisions}
    actions: dict[str, list] = {}
    for action in bundle.experiment_actions:
        actions.setdefault(action.hypothesis_id, []).append(action)

    def claim_items(claim_ids: list[str]) -> str:
        return "".join(
            f"<li>{html.escape(claims[item].subject.label)}: "
            f"{html.escape(claims[item].predicate)} "
            f"{html.escape(claims[item].object.text or claims[item].object.entity.label)}"
            f"<small>Evidence: {html.escape(', '.join(claims[item].evidence_ids))} · "
            f"role: {claims[item].context.mechanistic_role.value} · "
            f"uncertainty: {html.escape(claims[item].uncertainty)}</small></li>"
            for item in claim_ids
        )

    def criterion_items(criteria: list) -> str:
        return "".join(
            f"<li><b>{criterion.role.value}: {html.escape(criterion.endpoint)}</b>"
            f"<small>{html.escape(criterion.method)} · {html.escape(criterion.matrix)} · "
            f"{html.escape(criterion.timepoint)}<br>Threshold: "
            f"<span class={'pending' if criterion.threshold is None else 'specified'}>"
            f"{html.escape(criterion.threshold_status.value if criterion.threshold is None else criterion.threshold.description)}</span><br>"
            f"Decision role: {criterion.decision_role.value} · required now: "
            f"{str(criterion.required_for_current_gate).lower()}<br>"
            f"Derivation: {html.escape(criterion.threshold_derivation)}<br>"
            f"Fail: {html.escape(criterion.failure_condition)}<br>"
            f"Inconclusive: {html.escape(criterion.inconclusive_condition)}</small></li>"
            for criterion in criteria
        )

    cards: list[str] = []
    for hypothesis in bundle.hypotheses:
        decision = decisions[hypothesis.id]
        supporting = claim_items(hypothesis.supporting_claim_ids)
        counter = claim_items(hypothesis.counterevidence_claim_ids)
        predictions = "".join(
            f"<li>{html.escape(prediction.statement)}<small><b>Refute if:</b> "
            f"{html.escape(prediction.refutation_condition)}<br>Threshold: "
            f"<span class='pending'>{prediction.decision_criterion.threshold_status.value}</span></small></li>"
            for prediction in hypothesis.falsifiable_predictions
        )
        criteria = criterion_items(
            [
                hypothesis.intervention.target_engagement_criterion,
                *hypothesis.intervention.pharmacodynamic_criteria,
                *hypothesis.intervention.safety_criteria,
                hypothesis.biomarker.cutoff_criterion,
            ]
        )
        experiments = "".join(
            f"<section class='experiment'><h4>{html.escape(action.assay_type)}</h4>"
            f"<p><b>Assumption:</b> {html.escape(action.assumption_tested)}</p>"
            f"<p><b>Model:</b> {html.escape(action.model_system)}</p>"
            f"<p><b>Controls:</b> {html.escape(', '.join(control.name for control in action.controls))}</p>"
            f"<p><b>Sample plan:</b> <span class='pending'>{action.sample_plan.status.value}</span> — "
            f"{html.escape(action.sample_plan.rationale)}</p>"
            f"<p><b>Primary endpoint:</b> {html.escape(action.primary_endpoint.endpoint)} "
            f"(<span class='pending'>{action.primary_endpoint.threshold_status.value}</span>)</p>"
            f"<p><b>Go/no-go:</b> {html.escape(action.go_no_go_rule)}</p></section>"
            for action in actions.get(hypothesis.id, [])
        )
        abstention = (
            f"<p class='fatal'><b>Abstention reason</b><br>{html.escape(decision.abstention_reason)}</p>"
            if decision.abstention_reason
            else ""
        )
        cards.append(
            f"""
            <article class="card">
              <div class="row"><h2>{html.escape(hypothesis.target.entity.label)}</h2><span class="verdict">{decision.verdict.value}</span></div>
              <p class="mono">{html.escape(hypothesis.id)}</p>
              <p><b>Decision scope / gate</b><br>{hypothesis.decision_scope.value} · {hypothesis.current_gate}</p>
              <p><b>Target form</b><br>{hypothesis.target.biological_form.value} · {html.escape(hypothesis.target.molecular_scope)}</p>
              <p><b>Population / state</b><br>{html.escape(hypothesis.population)} · {html.escape(hypothesis.cell_state)}</p>
              <p><b>Intervention</b><br>{hypothesis.intervention.direction.value} · {html.escape(hypothesis.intervention.degree)} · {hypothesis.intervention.modality.value}</p>
              <p><b>Molecular action</b><br>{html.escape(hypothesis.intervention.molecular_action)}</p>
              <p><b>Selectivity / distribution</b><br>{html.escape('; '.join(hypothesis.intervention.selectivity_requirements))}<br>{html.escape(hypothesis.intervention.desired_distribution)}</p>
              <p><b>Mechanism context</b><br>Role: {hypothesis.mechanism_context.mechanistic_role.value}<br>
              Source: {html.escape(', '.join(hypothesis.mechanism_context.source_cells))}<br>
              Responding: {html.escape(', '.join(hypothesis.mechanism_context.responding_cells))}<br>
              Effector: {html.escape(', '.join(hypothesis.mechanism_context.effector_cells))}</p>
              <p><b>Biomarker ({hypothesis.biomarker.role.value})</b><br>{html.escape(hypothesis.biomarker.name)} · {html.escape(hypothesis.biomarker.matrix)}<br>
              Validation: {hypothesis.biomarker.analytical_validation.value} / {hypothesis.biomarker.clinical_validation.value}</p>
              <div class="columns"><div><b>Support</b><ul>{supporting}</ul></div><div><b>Counterevidence</b><ul>{counter}</ul></div></div>
              <p class="fatal"><b>Fatal assumption</b><br>{html.escape(hypothesis.fatal_assumption)}</p>
              <p><b>Explicit non-goals</b><br>{html.escape('; '.join(hypothesis.non_goals))}</p>
              {abstention}
              <details open><summary>Falsifiable predictions</summary><ul>{predictions}</ul></details>
              <details><summary>Target engagement, PD, safety & biomarker criteria</summary><ul>{criteria}</ul></details>
              <details><summary>Next experiment</summary>{experiments}</details>
              <a href="/api/hypotheses/{html.escape(hypothesis.id)}">Inspect JSON →</a>
            </article>
            """
        )
    brief = bundle.disease_brief
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TargetIdeator P0</title>
<style>
:root{{--ink:#17202a;--muted:#59636e;--paper:#f4f1eb;--panel:#fff;--accent:#006c67;--warn:#8a3f16}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 ui-sans-serif,system-ui,sans-serif}}
header,main{{max-width:1180px;margin:auto;padding:28px}} header{{padding-bottom:10px}} h1{{font:700 42px/1.1 Georgia,serif;margin:12px 0}}
.warning{{background:#fff0dc;border-left:5px solid var(--warn);padding:14px 18px;color:#622b0f}} .meta,.mono{{color:var(--muted)}} .mono{{font:12px ui-monospace,monospace}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(500px,1fr));gap:20px}} .card{{background:var(--panel);border:1px solid #ddd6ca;border-radius:12px;padding:22px;box-shadow:0 4px 18px #3a2d1a10}}
.row{{display:flex;align-items:center;justify-content:space-between;gap:12px}} h2{{margin:0;font:700 28px Georgia,serif}} .verdict{{background:#e5efed;color:var(--accent);padding:4px 9px;border-radius:20px;font-weight:700}}
.columns{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .fatal{{border-top:1px solid #eee4d8;padding-top:13px}} a{{color:var(--accent);font-weight:700;text-decoration:none}}
small{{display:block;color:var(--muted);margin-top:5px}} details{{border-top:1px solid #eee4d8;padding:12px 0}} summary{{cursor:pointer;font-weight:750;color:var(--accent)}}
.pending{{color:#9a4b00;font-weight:750}} .specified{{color:#176b50;font-weight:750}} .experiment{{background:#f7f8f6;padding:12px;border-radius:8px;margin:10px 0}} .experiment h4{{margin:0 0 8px}}
@media(max-width:600px){{.grid,.columns{{grid-template-columns:1fr}} header,main{{padding:18px}}}}
</style></head>
<body><header><p class="meta">TARGETIDEATOR · FROZEN P0.2 CONTRACT · <a href="/literature">OPEN P2.2 LITERATURE CLAIMS →</a></p><h1>{html.escape(brief.disease.label)} hypothesis dossier</h1>
<p class="warning"><b>{html.escape(WARNING)}</b></p>
<p class="meta">Schema {bundle.schema_version} · scope {bundle.scope_policy.decision_scope.value} · gate {bundle.scope_policy.current_gate}<br>
Snapshot <code>{html.escape(bundle.snapshot_id)}</code> · evidence cutoff {brief.as_of_date.isoformat()} · {len(bundle.hypotheses)} hypotheses · <a href="/api/export">download JSON</a></p></header>
<main><section class="grid">{''.join(cards)}</section></main></body></html>"""


def create_app() -> FastAPI:
    app = FastAPI(
        title="TargetIdeator P0.2 + P1 + P2 + P3 + P4.1 + P5.9 + P6.6 + R2.8",
        version="0.32.0",
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _page()

    @app.get("/health")
    def health() -> dict[str, str]:
        bundle = load_bundle()
        return {
            "status": "ok",
            "snapshot_id": bundle.snapshot_id,
            "evidence_snapshot_id": evidence_store().snapshot.source.id,
            "historical_snapshot_id": historical_store().snapshot.id,
            "clinical_snapshot_id": clinical_store().snapshot.id,
            "claim_graph_snapshot_id": claim_graph_store().snapshot.id,
            "literature_snapshot_id": literature_store().snapshot.id,
            "ideation_portfolio_id": ideation_store().portfolio.id,
            "falsification_snapshot_id": falsification_store().snapshot.id,
            "revision_snapshot_id": revision_store().snapshot.id,
            "decision_snapshot_id": decision_store().snapshot.id,
            "outcome_dataset_id": outcome_store().dataset.id,
            "outcome_model_snapshot_id": outcome_store().models.id,
            "broad_outcome_snapshot_id": broad_outcome_store().snapshot.id,
            "identity_snapshot_id": identity_store().snapshot.id,
            "mapping_audit_snapshot_id": mapping_audit_store().snapshot.id,
            "drug_identity_snapshot_id": drug_identity_store().snapshot.id,
            "assertion_history_snapshot_id": assertion_history_store().snapshot.id,
            "independent_assertion_snapshot_id": independent_assertion_store().snapshot.id,
            "support_audit_snapshot_id": support_audit_store().snapshot.id,
            "selection_audit_snapshot_id": selection_audit_store().snapshot.id,
            "evaluation_snapshot_id": evaluation_store().snapshot.id,
            "robustness_snapshot_id": robustness_store().snapshot.id,
            "cohort_stress_snapshot_id": cohort_stress_store().snapshot.id,
            "paired_control_snapshot_id": paired_control_store().snapshot.id,
            "counterevidence_ablation_snapshot_id": counterevidence_ablation_store().snapshot.id,
            "claim_synthesis_snapshot_id": claim_synthesis_store().snapshot.id,
            "paper_bundle_snapshot_id": paper_bundle_store().snapshot.id,
            "release_audit_snapshot_id": release_audit_store().snapshot.id,
            "packaging_split_snapshot_id": packaging_split_store().snapshot.id,
            "hydration_snapshot_id": hydration_store().snapshot.id,
            "retained_fixture_snapshot_id": retained_fixture_store().snapshot.id,
            "fixture_disposition_snapshot_id": fixture_disposition_store().snapshot.id,
            "execution_plan_snapshot_id": execution_plan_store().snapshot.id,
            "execution_replay_snapshot_id": execution_replay_store().snapshot.id,
            "replay_hardening_snapshot_id": replay_hardening_store().snapshot.id,
            "canonical_acceptance_snapshot_id": canonical_acceptance_store().snapshot.id,
            "package_convergence_snapshot_id": package_convergence_snapshot_id_or_status(),
        }

    @app.get("/evidence", response_class=HTMLResponse)
    def evidence_explorer(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2026, 11, 1),
        compare_to: date = date(2026, 9, 23),
    ) -> str:
        return evidence_page(disease_id, target_id, as_of_date, compare_to)

    @app.get("/evidence/history", response_class=HTMLResponse)
    def historical_evidence_explorer(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000167207",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date = date(2025, 3, 19),
    ) -> str:
        return historical_page(disease_id, target_id, as_of_date, compare_to)

    @app.get("/evidence/clinical", response_class=HTMLResponse)
    def clinical_evidence_explorer(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date = date(2025, 3, 19),
    ) -> str:
        return clinical_page(disease_id, target_id, as_of_date, compare_to)

    @app.get("/claims", response_class=HTMLResponse)
    def claim_graph_inspector(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date = date(2025, 3, 19),
        dependency_correction: bool = True,
    ) -> str:
        return claim_graph_page(
            disease_id,
            target_id,
            as_of_date,
            compare_to,
            dependency_correction,
        )

    @app.get("/literature", response_class=HTMLResponse)
    def literature_claim_inspector(
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2026, 11, 1),
        layer: str = "provisional_gold",
    ) -> str:
        return literature_page(target_id, as_of_date, layer)

    @app.get("/ideation", response_class=HTMLResponse)
    def hypothesis_ideation_portfolio() -> str:
        return ideation_page()

    @app.get("/falsification", response_class=HTMLResponse)
    def fixed_taxonomy_falsification() -> str:
        return falsification_page()

    @app.get("/revision", response_class=HTMLResponse)
    def conservative_structured_revisions() -> str:
        return revision_page()

    @app.get("/decision", response_class=HTMLResponse)
    def multi_head_decision_board(
        causal_weight: float = 0.2,
        direction_weight: float = 0.2,
        translation_weight: float = 0.2,
        feasibility_weight: float = 0.2,
        safety_weight: float = 0.2,
    ) -> str:
        return decision_page(
            causal_weight,
            direction_weight,
            translation_weight,
            feasibility_weight,
            safety_weight,
        )

    @app.get("/outcomes", response_class=HTMLResponse)
    def temporal_outcome_dashboard() -> str:
        return outcome_page()

    @app.get("/outcomes/broad", response_class=HTMLResponse)
    def broad_temporal_outcome_dashboard() -> str:
        return broad_outcome_page()

    @app.get("/identity", response_class=HTMLResponse)
    def auditable_identity_ledger() -> str:
        return identity_page()

    @app.get("/identity/audit", response_class=HTMLResponse)
    def mapping_missingness_audit(
        dimension: str = "intervention_profile", min_count: int = 100
    ) -> str:
        return mapping_audit_page(dimension, min_count)

    @app.get("/identity/resolution", response_class=HTMLResponse)
    def versioned_drug_identity_resolution() -> str:
        return drug_identity_page()

    @app.get("/identity/assertions", response_class=HTMLResponse)
    def versioned_source_assertion_history() -> str:
        return assertion_history_page()

    @app.get("/identity/corroboration", response_class=HTMLResponse)
    def independent_drug_target_corroboration() -> str:
        return independent_assertion_page()

    @app.get("/identity/outcome-audit", response_class=HTMLResponse)
    def corroboration_aware_outcome_audit() -> str:
        return support_audit_page()

    @app.get("/identity/selection-audit", response_class=HTMLResponse)
    def target_validation_selection_audit() -> str:
        return selection_audit_page()

    @app.get("/evaluation", response_class=HTMLResponse)
    def reproducible_evaluation_audit() -> str:
        return evaluation_page()

    @app.get("/evaluation/robustness", response_class=HTMLResponse)
    def claim_graph_robustness() -> str:
        return robustness_page()

    @app.get("/evaluation/dependency-stress", response_class=HTMLResponse)
    def duplicate_cohort_dependency_stress() -> str:
        return cohort_stress_page()

    @app.get("/evaluation/paired-control", response_class=HTMLResponse)
    def proposer_falsify_revision_paired_control() -> str:
        return paired_control_page()

    @app.get("/evaluation/counterevidence-ablation", response_class=HTMLResponse)
    def explicit_counterevidence_ablation() -> str:
        return counterevidence_ablation_page()

    @app.get("/evaluation/claim-synthesis", response_class=HTMLResponse)
    def frozen_claim_disposition_synthesis() -> str:
        return claim_synthesis_page()

    @app.get("/evaluation/paper-bundle", response_class=HTMLResponse)
    def reproducible_paper_artifact_bundle() -> str:
        return paper_bundle_page()

    @app.get("/release", response_class=HTMLResponse)
    def artifact_release_candidate_audit() -> str:
        return release_audit_page()

    @app.get("/release/data-bundle", response_class=HTMLResponse)
    def code_data_packaging_split() -> str:
        return packaging_split_page()

    @app.get("/release/hydration", response_class=HTMLResponse)
    def external_payload_hydration() -> str:
        return hydration_page()

    @app.get("/release/retained-fixtures", response_class=HTMLResponse)
    def retained_fixture_governance() -> str:
        return retained_fixture_page()

    @app.get("/release/fixture-dispositions", response_class=HTMLResponse)
    def fixture_dispositions() -> str:
        return fixture_disposition_page()

    @app.get("/release/execution-plan", response_class=HTMLResponse)
    def package_execution_plan() -> str:
        return execution_plan_page()

    @app.get("/release/execution-replay", response_class=HTMLResponse)
    def isolated_execution_replay() -> str:
        return execution_replay_page()

    @app.get("/release/replay-hardening", response_class=HTMLResponse)
    def bounded_retry_replay_hardening() -> str:
        return replay_hardening_page()

    @app.get("/release/package-convergence", response_class=HTMLResponse)
    def applied_package_convergence() -> str:
        return package_convergence_page()

    @app.get("/api/bundle")
    def get_bundle() -> dict:
        return load_bundle().model_dump(mode="json")

    @app.get("/api/hypotheses/{hypothesis_id}")
    def get_hypothesis(hypothesis_id: str) -> dict:
        bundle = load_bundle()
        for hypothesis in bundle.hypotheses:
            if hypothesis.id == hypothesis_id:
                return hypothesis.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="Hypothesis not found")

    @app.get("/api/export")
    def export() -> Response:
        content = bundle_json(load_bundle())
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="targetideator-p0-dossier.json"'},
        )

    @app.get("/api/p1/evidence")
    def get_temporal_evidence(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2026, 11, 1),
        compare_to: date | None = None,
    ) -> dict:
        return evidence_payload(disease_id, target_id, as_of_date, compare_to)

    @app.get("/api/p1/evidence/{evidence_id}")
    def get_evidence_lineage(evidence_id: str) -> dict:
        store = evidence_store()
        record = next((item for item in store.snapshot.records if item.id == evidence_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        return {
            "normalized": record.model_dump(mode="json"),
            "raw": store.raw_record(evidence_id),
        }

    @app.get("/api/p1/quality")
    def get_evidence_quality() -> dict:
        return evidence_store().quality_report()

    @app.get("/api/p1/unresolved")
    def get_unresolved_entities() -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in evidence_store().snapshot.unresolved_entities
        ]

    @app.get("/api/p1/history")
    def get_historical_evidence(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000167207",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date | None = None,
    ) -> dict:
        return historical_payload(disease_id, target_id, as_of_date, compare_to)

    @app.get("/api/p1/history/quality")
    def get_historical_quality() -> dict:
        return historical_store().quality_report()

    @app.get("/api/p1/history/releases")
    def get_historical_releases() -> list[dict]:
        return historical_store().release_summary()

    @app.get("/api/p1/history/records/{record_id}")
    def get_historical_lineage(record_id: str) -> dict:
        store = historical_store()
        record = next((item for item in store.snapshot.records if item.id == record_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Historical association not found")
        return {
            "normalized": record.model_dump(mode="json"),
            "raw": store.raw_record(record_id),
        }

    @app.get("/api/p1/clinical")
    def get_clinical_history(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date | None = None,
    ) -> dict:
        return clinical_payload(disease_id, target_id, as_of_date, compare_to)

    @app.get("/api/p1/clinical/quality")
    def get_clinical_quality() -> dict:
        return clinical_store().quality_report()

    @app.get("/api/p1/clinical/releases")
    def get_clinical_releases() -> dict:
        snapshot = clinical_store().snapshot
        return {
            "chembl": [item.model_dump(mode="json") for item in snapshot.chembl_releases],
            "aact": [item.model_dump(mode="json") for item in snapshot.aact_releases],
        }

    @app.get("/api/p1/clinical/evidence/{record_id}")
    def get_clinical_evidence_lineage(record_id: str) -> dict:
        store = clinical_store()
        record = next((item for item in store.snapshot.evidence_records if item.id == record_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Clinical evidence string not found")
        return {"normalized": record.model_dump(mode="json"), "raw": store.raw_evidence(record_id)}

    @app.get("/api/p1/clinical/trials/{record_id}")
    def get_clinical_trial_lineage(record_id: str) -> dict:
        store = clinical_store()
        record = next((item for item in store.snapshot.trial_records if item.id == record_id), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Historical trial row not found")
        return {"normalized": record.model_dump(mode="json"), "raw": store.raw_trial(record_id)}

    @app.get("/api/p2/claims")
    def get_claim_graph(
        disease_id: str = "MONDO:0005011",
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2025, 9, 17),
        compare_to: date | None = None,
    ) -> dict:
        return claim_graph_payload(disease_id, target_id, as_of_date, compare_to)

    @app.get("/api/p2/claims/quality")
    def get_claim_graph_quality() -> dict:
        return claim_graph_store().quality_report()

    @app.get("/api/p2/claims/{claim_id}")
    def get_claim_lineage(claim_id: str) -> dict:
        lineage = claim_graph_store().claim_lineage(claim_id)
        if lineage is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        return lineage

    @app.get("/api/p2/literature")
    def get_literature_claims(
        target_id: str = "ENSG00000110944",
        as_of_date: date = date(2026, 11, 1),
    ) -> dict:
        return literature_payload(target_id, as_of_date)

    @app.get("/api/p2/literature/quality")
    def get_literature_quality() -> dict:
        return literature_store().quality_report()

    @app.get("/api/p2/literature/review-queue")
    def get_literature_review_queue() -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in literature_store().snapshot.double_review_tasks
        ]

    @app.get("/api/p2/literature/review-batch")
    def get_literature_review_batch() -> dict:
        batch = load_default_review_batch()
        return {
            "batch": batch.model_dump(mode="json"),
            "quality": review_quality_report(batch, literature_store()),
        }

    @app.get("/api/p2/literature/review-comment-resolution")
    def get_literature_review_comment_resolution() -> dict:
        batch = load_default_comment_resolution()
        return {
            "batch": batch.model_dump(mode="json"),
            "quality": comment_resolution_quality_report(batch, literature_store()),
        }

    @app.get("/api/p2/literature/human-review-readiness")
    def get_literature_human_review_readiness() -> dict:
        return assess_human_review_readiness(
            build_human_review_draft("A"),
            build_human_review_draft("B"),
            literature_store(),
        ).model_dump(mode="json")

    @app.get("/api/p2/literature/claims/{claim_id}")
    def get_literature_claim_lineage(claim_id: str) -> dict:
        lineage = literature_store().claim_lineage(claim_id)
        if lineage is None:
            raise HTTPException(status_code=404, detail="Literature claim not found")
        return lineage

    @app.get("/api/p3/ideation")
    def get_ideation_portfolio() -> dict:
        return ideation_payload()

    @app.get("/api/p3/ideation/quality")
    def get_ideation_quality() -> dict:
        return ideation_store().quality_report()

    @app.get("/api/p3/ideation/hypotheses/{hypothesis_id}")
    def get_composed_hypothesis(hypothesis_id: str) -> dict:
        for hypothesis in ideation_store().portfolio.hypotheses:
            if hypothesis.id == hypothesis_id:
                return hypothesis.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="Composed hypothesis not found")

    @app.get("/api/p4/falsification")
    def get_falsification_snapshot() -> dict:
        return falsification_payload()

    @app.get("/api/p4/falsification/quality")
    def get_falsification_quality() -> dict:
        return falsification_store().quality_report()

    @app.get("/api/p4/falsification/hypotheses/{hypothesis_id}")
    def get_falsification_result(hypothesis_id: str) -> dict:
        result = falsification_store().result(hypothesis_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Falsification result not found")
        hypothesis = next(
            item
            for item in ideation_store().portfolio.hypotheses
            if item.id == hypothesis_id
        )
        return {
            "source_hypothesis": hypothesis.model_dump(mode="json"),
            "falsification_result": result.model_dump(mode="json"),
        }

    @app.get("/api/p4/revisions")
    def get_revision_snapshot() -> dict:
        return revision_payload()

    @app.get("/api/p4/revisions/quality")
    def get_revision_quality() -> dict:
        return revision_store().quality_report()

    @app.get("/api/p4/revisions/hypotheses/{hypothesis_id}")
    def get_revision_candidate(hypothesis_id: str) -> dict:
        candidate = revision_store().candidate(hypothesis_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Revision candidate not found")
        return candidate.model_dump(mode="json")

    @app.get("/api/p5/decision-engine")
    def get_decision_snapshot() -> dict:
        return decision_payload()

    @app.get("/api/p5/decision-engine/quality")
    def get_decision_quality() -> dict:
        return decision_store().quality_report()

    @app.get("/api/p5/decision-engine/hypotheses/{hypothesis_id}")
    def get_candidate_decision(hypothesis_id: str) -> dict:
        decision = decision_store().decision(hypothesis_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Candidate decision not found")
        return decision.model_dump(mode="json")

    @app.get("/api/p5/decision-engine/utility")
    def get_utility_scenario(
        causal_weight: float = 0.2,
        direction_weight: float = 0.2,
        translation_weight: float = 0.2,
        feasibility_weight: float = 0.2,
        safety_weight: float = 0.2,
    ) -> dict:
        weights = {
            DecisionHeadName.CAUSAL_RELEVANCE: causal_weight,
            DecisionHeadName.CORRECT_DIRECTION: direction_weight,
            DecisionHeadName.TRANSLATABLE_EFFICACY: translation_weight,
            DecisionHeadName.MODALITY_FEASIBILITY: feasibility_weight,
            DecisionHeadName.SAFETY_WINDOW: safety_weight,
        }
        try:
            return decision_store().utility_scenario(weights)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/p5/outcomes")
    def get_temporal_outcomes() -> dict:
        return outcome_payload()

    @app.get("/api/p5/outcomes/quality")
    def get_temporal_outcome_quality() -> dict:
        return outcome_store().quality_report()

    @app.get("/api/p5/outcomes/models")
    def get_temporal_outcome_models() -> dict:
        return outcome_store().models.model_dump(mode="json")

    @app.get("/api/p5/outcomes/records/{record_id}")
    def get_temporal_outcome_record(record_id: str) -> dict:
        record = next(
            (item for item in outcome_store().dataset.records if item.id == record_id),
            None,
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Temporal outcome record not found")
        return record.model_dump(mode="json")

    @app.get("/api/p5/outcomes/broad")
    def get_broad_temporal_outcomes() -> dict:
        return broad_outcome_payload()

    @app.get("/api/p5/outcomes/broad/quality")
    def get_broad_temporal_outcome_quality() -> dict:
        return broad_outcome_store().quality_report()

    @app.get("/api/p5/outcomes/broad/sample")
    def get_broad_temporal_outcome_sample(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return broad_outcome_store().sample_records(limit)

    @app.get("/api/p5/identity")
    def get_identity_ledger() -> dict:
        return identity_payload()

    @app.get("/api/p5/identity/quality")
    def get_identity_quality() -> dict:
        return identity_store().quality_report()

    @app.get("/api/p5/identity/mappings/sample")
    def get_identity_mapping_sample(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return identity_store().sample_mappings(limit)

    @app.get("/api/p5/identity/provenance/sample")
    def get_identity_provenance_sample(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return identity_store().sample_provenance(limit)

    @app.get("/api/p5/identity/unresolved/sample")
    def get_identity_unresolved_sample(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return identity_store().sample_unresolved(limit)

    @app.get("/api/p5/identity/trials/{nct_id}")
    def get_trial_identity_lineage(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        lineage = identity_store().trial_lineage(nct_id)
        if not any(lineage[key] for key in ("mappings", "outcome_provenance", "unresolved")):
            raise HTTPException(status_code=404, detail="Trial not found in P5.3 ledger")
        return lineage

    @app.get("/api/p5/mapping-audit")
    def get_mapping_audit() -> dict:
        return mapping_audit_payload()

    @app.get("/api/p5/mapping-audit/quality")
    def get_mapping_audit_quality() -> dict:
        return mapping_audit_store().quality_report()

    @app.get("/api/p5/mapping-audit/strata")
    def get_mapping_audit_strata(
        dimension: str | None = None, min_count: int = 0
    ) -> list[dict]:
        if dimension is not None and dimension not in MAPPING_AUDIT_DIMENSIONS:
            raise HTTPException(status_code=422, detail="unknown mapping-audit dimension")
        if min_count < 0:
            raise HTTPException(status_code=422, detail="min_count must be non-negative")
        return mapping_audit_store().strata(dimension, min_count)

    @app.get("/api/p5/mapping-audit/triage/sample")
    def get_mapping_audit_triage_sample(
        limit: int = 20, reason: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return mapping_audit_store().sample_triage(limit, reason)

    @app.get("/api/p5/mapping-audit/trials/{nct_id}")
    def get_mapping_audit_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        record = mapping_audit_store().trial(nct_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Trial not found in P5.4 audit")
        return record

    @app.get("/api/p5/drug-identity")
    def get_drug_identity() -> dict:
        return drug_identity_payload()

    @app.get("/api/p5/drug-identity/quality")
    def get_drug_identity_quality() -> dict:
        return drug_identity_store().quality_report()

    @app.get("/api/p5/drug-identity/sample")
    def get_drug_identity_sample(
        limit: int = 20, status: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = set(drug_identity_store().snapshot.quality.resolution_status_counts)
        if status is not None and status not in allowed:
            raise HTTPException(status_code=422, detail="unknown resolution status")
        return drug_identity_store().sample(limit, status)

    @app.get("/api/p5/drug-identity/trials/{nct_id}")
    def get_drug_identity_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        record = drug_identity_store().trial(nct_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Trial not found in P5.5 ledger")
        return record

    @app.get("/api/p5/assertion-history")
    def get_assertion_history() -> dict:
        return assertion_history_payload()

    @app.get("/api/p5/assertion-history/quality")
    def get_assertion_history_quality() -> dict:
        return assertion_history_store().quality_report()

    @app.get("/api/p5/assertion-history/evidence/sample")
    def get_assertion_history_evidence_sample(
        limit: int = 20, lifecycle: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = {
            "persistent_across_releases",
            "removed_after_25_03",
            "added_in_25_09",
        }
        if lifecycle is not None and lifecycle not in allowed:
            raise HTTPException(status_code=422, detail="unknown lifecycle status")
        return assertion_history_store().sample_evidence(limit, lifecycle)

    @app.get("/api/p5/assertion-history/assertions/sample")
    def get_assertion_history_assertion_sample(
        limit: int = 20, lifecycle: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = {
            "persistent_across_releases",
            "removed_after_25_03",
            "added_in_25_09",
        }
        if lifecycle is not None and lifecycle not in allowed:
            raise HTTPException(status_code=422, detail="unknown lifecycle status")
        return assertion_history_store().sample_assertions(limit, lifecycle)

    @app.get("/api/p5/assertion-history/trials/{nct_id}")
    def get_assertion_history_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        result = assertion_history_store().trial(nct_id)
        if not result["assertions"]:
            raise HTTPException(
                status_code=404, detail="Trial has no source assertion in P5.6"
            )
        return result

    @app.get("/api/p5/independent-assertions")
    def get_independent_assertions() -> dict:
        return independent_assertion_payload()

    @app.get("/api/p5/independent-assertions/quality")
    def get_independent_assertion_quality() -> dict:
        return independent_assertion_store().quality_report()

    @app.get("/api/p5/independent-assertions/pairs/sample")
    def get_independent_pair_sample(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return independent_assertion_store().sample_pairs(limit)

    @app.get("/api/p5/independent-assertions/corroborations/sample")
    def get_independent_corroboration_sample(
        limit: int = 20, status: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = {
            "cross_source_drug_target_supported",
            "opentargets_chembl_only",
        }
        if status is not None and status not in allowed:
            raise HTTPException(status_code=422, detail="unknown corroboration status")
        return independent_assertion_store().sample_corroborations(limit, status)

    @app.get("/api/p5/independent-assertions/trials/{nct_id}")
    def get_independent_assertion_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        result = independent_assertion_store().trial(nct_id)
        if not result["corroborations"]:
            raise HTTPException(
                status_code=404, detail="Trial not found in current source ledger"
            )
        return result

    @app.get("/api/p5/support-audit")
    def get_support_audit() -> dict:
        return support_audit_payload()

    @app.get("/api/p5/support-audit/quality")
    def get_support_audit_quality() -> dict:
        return support_audit_store().quality_report()

    @app.get("/api/p5/support-audit/outcomes/sample")
    def get_support_audit_outcomes(limit: int = 20, stratum: str | None = None) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = set(support_audit_store().snapshot.quality.nct_counts_by_support_stratum)
        if stratum is not None and stratum not in allowed:
            raise HTTPException(status_code=422, detail="unknown support stratum")
        return support_audit_store().sample_outcomes(limit, stratum)

    @app.get("/api/p5/support-audit/explicit-events/sample")
    def get_support_audit_explicit_events(
        limit: int = 20, stratum: str | None = None, category: str | None = None
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed_strata = set(support_audit_store().snapshot.quality.nct_counts_by_support_stratum)
        allowed_categories = set(support_audit_store().snapshot.quality.explicit_event_counts_by_category_and_support_stratum)
        if stratum is not None and stratum not in allowed_strata:
            raise HTTPException(status_code=422, detail="unknown support stratum")
        if category is not None and category not in allowed_categories:
            raise HTTPException(status_code=422, detail="unknown explicit event category")
        return support_audit_store().sample_explicit_events(limit, stratum, category)

    @app.get("/api/p5/support-audit/trials/{nct_id}")
    def get_support_audit_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        result = support_audit_store().trial(nct_id)
        if not result["outcome_provenance"]:
            raise HTTPException(status_code=404, detail="Trial not found in outcome provenance")
        return result

    @app.get("/api/p5/selection-audit")
    def get_selection_audit() -> dict:
        return selection_audit_payload()

    @app.get("/api/p5/selection-audit/quality")
    def get_selection_audit_quality() -> dict:
        return selection_audit_store().quality_report()

    @app.get("/api/p5/selection-audit/cohort/sample")
    def get_selection_audit_cohort(limit: int = 20, stratum: str | None = None) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = set(selection_audit_store().snapshot.quality.support_stratum_counts)
        if stratum is not None and stratum not in allowed:
            raise HTTPException(status_code=422, detail="unknown support stratum")
        return selection_audit_store().sample_cohort(limit, stratum)

    @app.get("/api/p5/selection-audit/balance/sample")
    def get_selection_audit_balance(
        limit: int = 20, contrast: str | None = None, material_only: bool = False
    ) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        allowed = {"mapped_vs_unmapped"} | {
            f"{name}_vs_rest"
            for name in selection_audit_store().snapshot.quality.support_stratum_counts
        }
        if contrast is not None and contrast not in allowed:
            raise HTTPException(status_code=422, detail="unknown balance contrast")
        return selection_audit_store().sample_balance(limit, contrast, material_only)

    @app.get("/api/p5/selection-audit/trials/{nct_id}")
    def get_selection_audit_trial(nct_id: str) -> dict:
        if not re.fullmatch(r"NCT\d{8}", nct_id):
            raise HTTPException(status_code=422, detail="invalid NCT identifier")
        result = selection_audit_store().trial(nct_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Trial not found in selection cohort")
        return result

    @app.get("/api/p6/evaluation")
    def get_evaluation() -> dict:
        return evaluation_payload()

    @app.get("/api/p6/evaluation/quality")
    def get_evaluation_quality() -> dict:
        return evaluation_store().quality_report()

    @app.get("/api/p6/evaluation/claims")
    def get_evaluation_claims() -> list[dict]:
        return evaluation_store().claims()

    @app.get("/api/p6/evaluation/artifacts")
    def get_evaluation_artifacts() -> list[dict]:
        return evaluation_store().artifacts()

    @app.get("/api/p6/evaluation/replay")
    def get_evaluation_replay(limit: int = 20) -> list[dict]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        return evaluation_store().replay(limit)

    @app.get("/api/p6/evaluation/replay/{hypothesis_id:path}")
    def get_evaluation_hypothesis_replay(hypothesis_id: str) -> dict:
        result = evaluation_store().hypothesis_replay(hypothesis_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Hypothesis not found in replay")
        return result

    @app.get("/api/p6/robustness")
    def get_robustness() -> dict:
        return robustness_payload()

    @app.get("/api/p6/robustness/quality")
    def get_robustness_quality() -> dict:
        return robustness_store().quality_report()

    @app.get("/api/p6/robustness/scenarios")
    def get_robustness_scenarios(kind: str | None = None) -> list[dict]:
        allowed = {
            "claim_drop", "polarity_flip", "context_corruption", "dependency_edge_removal"
        }
        if kind is not None and kind not in allowed:
            raise HTTPException(status_code=422, detail="unknown perturbation kind")
        return robustness_store().scenarios(kind)

    @app.get("/api/p6/robustness/ledger")
    def get_robustness_ledger(kind: str | None = None) -> list[dict]:
        allowed = {
            "claim_drop", "polarity_flip", "context_corruption", "dependency_edge_removal"
        }
        if kind is not None and kind not in allowed:
            raise HTTPException(status_code=422, detail="unknown perturbation kind")
        return robustness_store().ledger(kind)

    @app.get("/api/p6/robustness/targets")
    def get_robustness_targets(
        scenario_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        if limit < 1 or limit > 200:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
        return robustness_store().target_propagation(scenario_id, limit)

    @app.get("/api/p6/cohort-stress")
    def get_cohort_stress() -> dict:
        return cohort_stress_payload()

    @app.get("/api/p6/cohort-stress/quality")
    def get_cohort_stress_quality() -> dict:
        return cohort_stress_store().quality_report()

    @app.get("/api/p6/cohort-stress/scenarios")
    def get_cohort_stress_scenarios() -> list[dict]:
        return cohort_stress_store().scenarios()

    @app.get("/api/p6/cohort-stress/ledger")
    def get_cohort_stress_ledger() -> list[dict]:
        return cohort_stress_store().ledger()

    @app.get("/api/p6/cohort-stress/targets")
    def get_cohort_stress_targets(scenario_id: str | None = None) -> list[dict]:
        return cohort_stress_store().targets(scenario_id)

    @app.get("/api/p6/paired-control")
    def get_paired_control() -> dict:
        return paired_control_payload()

    @app.get("/api/p6/paired-control/quality")
    def get_paired_control_quality() -> dict:
        return paired_control_store().quality_report()

    @app.get("/api/p6/paired-control/pairs")
    def get_paired_control_pairs() -> list[dict]:
        return paired_control_store().pairs()

    @app.get("/api/p6/paired-control/critic-cells")
    def get_paired_control_critic_cells(hypothesis_id: str | None = None) -> list[dict]:
        return paired_control_store().critic_cells(hypothesis_id)

    @app.get("/api/p6/paired-control/false-rejection-queue")
    def get_paired_control_false_rejection_queue() -> list[dict]:
        return paired_control_store().false_rejection_queue()

    @app.get("/api/p6/counterevidence-ablation")
    def get_counterevidence_ablation() -> dict:
        return counterevidence_ablation_payload()

    @app.get("/api/p6/counterevidence-ablation/quality")
    def get_counterevidence_ablation_quality() -> dict:
        return counterevidence_ablation_store().quality_report()

    @app.get("/api/p6/counterevidence-ablation/ledger")
    def get_counterevidence_ablation_ledger() -> list[dict]:
        return counterevidence_ablation_store().ledger()

    @app.get("/api/p6/counterevidence-ablation/cells")
    def get_counterevidence_ablation_cells(changed_only: bool = False) -> list[dict]:
        return counterevidence_ablation_store().cells(changed_only)

    @app.get("/api/p6/counterevidence-ablation/hypotheses")
    def get_counterevidence_ablation_hypotheses() -> list[dict]:
        return counterevidence_ablation_store().hypotheses()

    @app.get("/api/p6/claim-synthesis")
    def get_claim_synthesis() -> dict:
        return claim_synthesis_payload()

    @app.get("/api/p6/claim-synthesis/quality")
    def get_claim_synthesis_quality() -> dict:
        return claim_synthesis_store().quality_report()

    @app.get("/api/p6/claim-synthesis/claims")
    def get_claim_synthesis_claims() -> list[dict]:
        return claim_synthesis_store().claims()

    @app.get("/api/p6/claim-synthesis/experiments")
    def get_claim_synthesis_experiments() -> list[dict]:
        return claim_synthesis_store().experiments()

    @app.get("/api/p6/claim-synthesis/paper-table", response_class=Response)
    def get_claim_synthesis_paper_table() -> Response:
        return Response(
            content=claim_synthesis_store().paper_table(),
            media_type="text/markdown",
        )

    @app.get("/api/p6/paper-bundle")
    def get_paper_bundle() -> dict:
        return paper_bundle_payload()

    @app.get("/api/p6/paper-bundle/quality")
    def get_paper_bundle_quality() -> dict:
        return paper_bundle_store().quality_report()

    @app.get("/api/p6/paper-bundle/sources")
    def get_paper_bundle_sources() -> list[dict]:
        return paper_bundle_store().sources()

    @app.get("/api/p6/paper-bundle/gates")
    def get_paper_bundle_gates() -> list[dict]:
        return paper_bundle_store().gates()

    @app.get("/api/p6/paper-bundle/files")
    def get_paper_bundle_files() -> list[dict]:
        return paper_bundle_store().paper_files()

    @app.get("/api/p6/paper-bundle/file", response_class=Response)
    def get_paper_bundle_file(path: str) -> Response:
        content = paper_bundle_store().paper_file(path)
        if content is None:
            raise HTTPException(status_code=404, detail="Paper file not found")
        return Response(content=content, media_type="text/markdown")

    @app.get("/api/release/audit")
    def get_release_audit() -> dict:
        return release_audit_payload()

    @app.get("/api/release/audit/quality")
    def get_release_audit_quality() -> dict:
        return release_audit_store().quality_report()

    @app.get("/api/release/audit/gates")
    def get_release_audit_gates() -> list[dict]:
        return release_audit_store().gates()

    @app.get("/api/release/audit/largest-files")
    def get_release_audit_largest_files(limit: int = 20) -> list[dict]:
        return release_audit_store().largest_payload_files(limit)

    @app.get("/api/release/data-bundle")
    def get_packaging_split() -> dict:
        return packaging_split_payload()

    @app.get("/api/release/data-bundle/quality")
    def get_packaging_split_quality() -> dict:
        return packaging_split_store().quality_report()

    @app.get("/api/release/data-bundle/inventory")
    def get_packaging_split_inventory() -> list[dict]:
        return packaging_split_store().inventory()

    @app.get("/api/release/hydration")
    def get_hydration_contract() -> dict:
        return hydration_payload()

    @app.get("/api/release/hydration/quality")
    def get_hydration_quality() -> dict:
        return hydration_store().quality_report()

    @app.get("/api/release/hydration/recipe")
    def get_hydration_recipe() -> list[dict]:
        return [row.model_dump(mode="json") for row in hydration_store().recipe()]

    @app.get("/api/release/hydration/status")
    def get_hydration_status() -> dict:
        return hydration_status()

    @app.get("/api/release/retained-fixtures")
    def get_retained_fixture_governance() -> dict:
        return retained_fixture_payload()

    @app.get("/api/release/retained-fixtures/quality")
    def get_retained_fixture_quality() -> dict:
        return retained_fixture_store().quality_report()

    @app.get("/api/release/retained-fixtures/inventory")
    def get_retained_fixture_inventory() -> list[dict]:
        return [
            row.model_dump(mode="json") for row in retained_fixture_store().inventory()
        ]

    @app.get("/api/release/fixture-dispositions")
    def get_fixture_dispositions() -> dict:
        return fixture_disposition_payload()

    @app.get("/api/release/fixture-dispositions/quality")
    def get_fixture_disposition_quality() -> dict:
        return fixture_disposition_store().quality_report()

    @app.get("/api/release/fixture-dispositions/ledger")
    def get_fixture_disposition_ledger() -> list[dict]:
        return [
            row.model_dump(mode="json") for row in fixture_disposition_store().ledger()
        ]

    @app.get("/api/release/execution-plan")
    def get_execution_plan() -> dict:
        return execution_plan_payload()

    @app.get("/api/release/execution-plan/quality")
    def get_execution_plan_quality() -> dict:
        return execution_plan_store().quality_report()

    @app.get("/api/release/execution-plan/recipe")
    def get_execution_recipe() -> list[dict]:
        return [row.model_dump(mode="json") for row in execution_plan_store().recipe()]

    @app.get("/api/release/execution-plan/preview")
    def get_mutation_preview() -> list[dict]:
        return [row.model_dump(mode="json") for row in execution_plan_store().preview()]

    @app.get("/api/release/execution-replay")
    def get_execution_replay() -> dict:
        return execution_replay_payload()

    @app.get("/api/release/execution-replay/quality")
    def get_execution_replay_quality() -> dict:
        return execution_replay_store().quality_report()

    @app.get("/api/release/execution-replay/groups")
    def get_execution_replay_groups() -> list[dict]:
        return [row.model_dump(mode="json") for row in execution_replay_store().groups()]

    @app.get("/api/release/execution-replay/artifacts")
    def get_execution_replay_artifacts() -> list[dict]:
        return [row.model_dump(mode="json") for row in execution_replay_store().artifacts()]

    @app.get("/api/release/replay-hardening")
    def get_replay_hardening() -> dict:
        return replay_hardening_payload()

    @app.get("/api/release/replay-hardening/quality")
    def get_replay_hardening_quality() -> dict:
        return replay_hardening_store().quality_report()

    @app.get("/api/release/replay-hardening/diagnosis")
    def get_replay_hardening_diagnosis() -> list[dict]:
        return [
            row.model_dump(mode="json") for row in replay_hardening_store().diagnosis()
        ]

    @app.get("/api/release/canonical-acceptance")
    def get_canonical_acceptance() -> dict:
        payload = package_convergence_payload()
        return {
            "snapshot": payload["canonical_snapshot"],
            "quality": payload["canonical_quality"],
            "acceptance": payload["canonical_acceptance"],
        }

    @app.get("/api/release/package-convergence")
    def get_package_convergence() -> dict:
        return package_convergence_payload()

    @app.get("/api/release/package-convergence/quality")
    def get_package_convergence_quality() -> dict:
        return package_convergence_store().quality_report()

    @app.get("/api/release/package-convergence/file-audit")
    def get_package_file_audit() -> list[dict]:
        return [
            row.model_dump(mode="json")
            for row in package_convergence_store().file_audit()
        ]

    @app.get("/api/release/package-convergence/runtime-smoke")
    def get_package_runtime_smoke() -> list[dict]:
        return [
            row.model_dump(mode="json")
            for row in package_convergence_store().runtime_smoke()
        ]

    return app


app = create_app()
