"""Build a frozen, model-assisted pre-review for the 30 P2.2 double-review tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from targetideator.claims.models import ClaimPolarity
from targetideator.evidence.store import _load_json
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.literature.models import ClaimDirection, LiteratureClaimTheme
from targetideator.literature.review_models import (
    ClaimReview,
    DoubleReviewResult,
    EvidenceRole,
    LiteratureReviewBatch,
    ReviewBatchSummary,
    ReviewDisposition,
    TargetGrounding,
)
from targetideator.literature.store import LiteratureStore, load_default_literature_store

REVIEW_BATCH_ID = "ti:literature-review-batch:crohns-p2-2-fixed-30-v1"
REVIEW_CREATED_AT = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
REVIEWER_IDS = {
    "A": "model-assisted-review-pass-a-v1",
    "B": "model-assisted-review-pass-b-v1",
}

# PMID -> (disposition, grounding, atomic, theme, polarity, direction, rationale)
# These are frozen pre-review decisions. They prioritize false-target rejection and do not
# alter the provisional benchmark. Human reviewers must independently sign the 30 tasks.
PASS_A: dict[str, tuple[Any, ...]] = {
    "16290228": ("accept", "explicit", True, "mechanism", "supports", "increases", "IL-23 is explicitly assigned a pathogenic role in inflammatory disease."),
    "16670765": ("accept", "explicit", True, "therapeutic_effect", "qualifies", "unknown", "The span proposes the IL-23/IL-17 pathway as a possible therapeutic target without an explicit modulation direction."),
    "16919486": ("accept", "explicit", True, "mechanism", "supports", "increases", "The sentence explicitly identifies IL-23 as an intestinal innate effector cytokine."),
    "17068223": ("reject", "wrong_target", False, None, None, None, "The association is with IL23R; mentioning its IL-23 ligand does not make this an IL23A association claim."),
    "18469800": ("accept", "explicit", True, "mechanism", "supports", "increases", "The first clause directly reports IL-23-driven IL-17 secretion; the caveat concerns naive-cell differentiation."),
    "19448631": ("reject", "explicit", False, None, None, None, "The span says only that an unspecified IL-23 function is emerging and does not state an atomic proposition."),
    "23034650": ("reject", "absent", False, None, None, None, "The selected sentence concerns colitis-associated cancer and contains no IL-23 proposition."),
    "23698371": ("reject", "absent", False, None, None, None, "The selected sentence concerns MHCII-positive ILCs and does not ground IL-23."),
    "10358752": ("accept", "explicit", True, "mechanism", "refutes", "unknown", "The span explicitly states that mast-cell IL-15 signaling uses Jak2 rather than Jak1/Jak3."),
    "24326545": ("reject", "absent", False, None, None, None, "IL-15 dysregulation is reported, but JAK1 is absent from the selected proposition."),
    "25552479": ("reject", "wrong_target", False, None, None, None, "The biochemical claim concerns Jak3, not JAK1."),
    "28158411": ("accept", "explicit", True, "safety_or_limitation", "qualifies", "context_dependent", "The sentence jointly reports JAK1-inhibitor response and a liver-toxicity limitation in another disease context."),
    "30930775": ("reject", "absent", False, None, None, None, "This is a generic IBD description with no JAK1 proposition."),
    "31005036": ("accept", "explicit", True, "mechanism", "qualifies", "unknown", "The JAK1 pathway is explicitly but tentatively linked to EV-mediated UC repair."),
    "31569788": ("accept", "explicit", True, "therapeutic_effect", "supports", "decreases", "The compound is reported to inhibit JAK1/2 phosphorylation."),
    "35951774": ("reject", "absent", False, None, None, None, "The span is about H. pylori management and contains no JAK1 proposition."),
    "11385576": ("accept", "explicit", True, "genetic_association", "supports", "unknown", "NOD2 is explicitly proposed to confer Crohn susceptibility with a mechanistic explanation."),
    "11875755": ("accept", "explicit", True, "genetic_association", "supports", "unknown", "CARD15 is a NOD2 synonym and the sentence reports Crohn-associated mutations."),
    "15082587": ("reject", "absent", False, None, None, None, "The span reports Crohn microbiota diversity but does not mention or attribute the result to NOD2."),
    "15220916": ("accept", "explicit", True, "mechanism", "supports", "increases", "NOD2 deficiency/Card15 mutation is explicitly linked to increased TLR2 signaling and TH1 responses."),
    "17435756": ("accept", "explicit", True, "genetic_association", "supports", "unknown", "The sentence explicitly treats CARD15/NOD2 association as previously established, although the new replication concerns other loci."),
    "23219392": ("reject", "absent", False, None, None, None, "The span is a CCR2 monocyte-recruitment claim and does not ground NOD2."),
    "27802154": ("reject", "absent", False, None, None, None, "The conclusion concerns a multi-gene risk score; NOD2 is not identified in this span."),
    "14568967": ("accept", "explicit", True, "disease_association", "supports", "increases", "TL1A/TNFSF15 expression is explicitly increased in affected Crohn tissue."),
    "16698931": ("accept", "explicit", True, "mechanism", "supports", "increases", "TL1A/DR3 up-regulation is explicitly associated with intestinal inflammation in two models."),
    "20176734": ("reject", "absent", False, None, None, None, "The selected sentence is an MHC risk-allele claim and does not mention TNFSF15/TL1A."),
    "23266558": ("accept", "explicit", True, "genetic_association", "supports", "unknown", "The span explicitly confirms a Crohn association for a TNFSF15 variant."),
    "24368564": ("accept", "explicit", True, "mechanism", "supports", "increases", "TL1A/TNFSF15 is explicitly reported to costimulate T cells and promote autoimmune models."),
    "26192919": ("reject", "absent", False, None, None, None, "The span is a generic trans-ancestry conclusion and does not ground TNFSF15."),
    "30552020": ("accept", "explicit", True, "mechanism", "supports", "increases", "IBD-associated microbiota is explicitly reported to induce TL1A release."),
}

PASS_B_OVERRIDES: dict[str, tuple[Any, ...]] = {
    "17068223": ("revise", "wrong_target", True, "genetic_association", "supports", "unknown", "This is an atomic IL23R association claim and should be retargeted to IL23R rather than retained under IL23A."),
    "18469800": ("accept", "explicit", True, "mechanism", "qualifies", "increases", "The driving effect is reported, but the unresolved naive-human-cell differentiation context qualifies generalization."),
    "19448631": ("revise", "explicit", True, "disease_association", "neutral", "unknown", "A weak IL-23 disease-context statement is present, but the object must be narrowed before acceptance."),
    "10358752": ("accept", "explicit", True, "mechanism", "qualifies", "context_dependent", "The sentence qualifies pathway usage by cell type rather than globally refuting JAK1 biology."),
    "31005036": ("accept", "explicit", True, "mechanism", "qualifies", "increases", "The tentative positive repair effect is linked to activation/participation of the JAK1 pathway."),
}


def default_review_batch_path() -> Path:
    return fixture_path("literature_review_batch.json")


def _decision(pass_id: str, pmid: str) -> tuple[Any, ...]:
    if pass_id == "B" and pmid in PASS_B_OVERRIDES:
        return PASS_B_OVERRIDES[pmid]
    return PASS_A[pmid]


def _review(task_id: str, claim_id: str, pass_id: str, pmid: str) -> ClaimReview:
    disposition, grounding, atomic, theme, polarity, direction, rationale = _decision(pass_id, pmid)
    evidence_role = (
        EvidenceRole.NOT_TARGET_EVIDENCE
        if disposition == "reject"
        else EvidenceRole.NEGATIVE_RESULT
        if polarity == "refutes"
        else EvidenceRole.CONTEXTUAL_INFERENCE
        if grounding == "contextual"
        else EvidenceRole.DIRECT_RESULT
    )
    return ClaimReview(
        id=stable_id("claim-review", f"{task_id}-{pass_id.lower()}"),
        task_id=task_id,
        claim_id=claim_id,
        review_pass=pass_id,
        reviewer_id=REVIEWER_IDS[pass_id],
        completed_at=REVIEW_CREATED_AT,
        disposition=ReviewDisposition(disposition),
        target_grounding=TargetGrounding(grounding),
        evidence_role=evidence_role,
        is_atomic_claim=atomic,
        proposed_theme=LiteratureClaimTheme(theme) if theme else None,
        proposed_polarity=ClaimPolarity(polarity) if polarity else None,
        proposed_direction=ClaimDirection(direction) if direction else None,
        rationale=rationale,
    )


def _disagreement_fields(reviews: list[ClaimReview]) -> list[str]:
    first, second = reviews
    fields = (
        "disposition",
        "target_grounding",
        "is_atomic_claim",
        "proposed_theme",
        "proposed_polarity",
        "proposed_direction",
    )
    return [field for field in fields if getattr(first, field) != getattr(second, field)]


def build_model_assisted_review_batch(store: LiteratureStore) -> LiteratureReviewBatch:
    claims = {item.id: item for item in store.snapshot.provisional_gold_claims}
    documents = {item.id: item for item in store.snapshot.documents}
    results: list[DoubleReviewResult] = []
    for task in store.snapshot.double_review_tasks:
        claim = claims[task.claim_id]
        pmid = documents[claim.document_version_id].pmid
        if pmid is None or pmid not in PASS_A:
            raise ValueError(f"frozen review decision missing for {claim.id}")
        reviews = [_review(task.id, claim.id, pass_id, pmid) for pass_id in ("A", "B")]
        disagreements = _disagreement_fields(reviews)
        results.append(
            DoubleReviewResult(
                task_id=task.id,
                claim_id=claim.id,
                reviews=reviews,
                agreement=not disagreements,
                disagreement_fields=disagreements,
            )
        )
    agreement_count = sum(item.agreement for item in results)
    consensus_accept = sum(
        item.agreement and item.reviews[0].disposition == ReviewDisposition.ACCEPT
        for item in results
    )
    consensus_reject = sum(
        item.agreement and item.reviews[0].disposition == ReviewDisposition.REJECT
        for item in results
    )
    disposition_disagreements = sum(
        "disposition" in item.disagreement_fields for item in results
    )
    return LiteratureReviewBatch(
        id=REVIEW_BATCH_ID,
        source_snapshot_id=store.snapshot.id,
        created_at=REVIEW_CREATED_AT,
        review_results=results,
        summary=ReviewBatchSummary(
            task_count=len(results),
            model_pass_count=len(results) * 2,
            agreement_count=agreement_count,
            disagreement_count=len(results) - agreement_count,
            consensus_accept_count=consensus_accept,
            consensus_reject_count=consensus_reject,
            disposition_disagreement_count=disposition_disagreements,
        ),
        warning=(
            "Two model-assisted passes are triage only, not two independent human expert reviews. "
            "All 30 claims remain provisional_gold pending human sign-off and adjudication."
        ),
    )


def write_review_batch(output_path: Path, store: LiteratureStore | None = None) -> LiteratureReviewBatch:
    batch = build_model_assisted_review_batch(store or load_default_literature_store())
    write_json(output_path, batch.model_dump(mode="json"))
    return batch


def load_default_review_batch() -> LiteratureReviewBatch:
    return LiteratureReviewBatch.model_validate(_load_json(default_review_batch_path()))


def render_human_review_packet(store: LiteratureStore, reviewer_slot: str) -> str:
    """Render a blank packet; model suggestions and the other reviewer remain hidden."""

    claims = {item.id: item for item in store.snapshot.provisional_gold_claims}
    documents = {item.id: item for item in store.snapshot.documents}
    paragraphs = {item.id: item for item in store.snapshot.paragraphs}
    sections = [
        f"# P2.2 Human Review Packet — reviewer {reviewer_slot}",
        "",
        "> 30 fixed tasks. Review independently; do not inspect the other packet or model pre-review. "
        "Completing this file does not adjudicate a claim.",
        "",
        "For each task record: disposition, target grounding, evidence role, atomicity, theme, "
        "polarity, direction, optional replacement claim, and rationale. For reject, leave semantic "
        "labels empty. Complete the submission-level identity and signature only after all 30 items.",
        "",
    ]
    for index, task in enumerate(store.snapshot.double_review_tasks, start=1):
        claim = claims[task.claim_id]
        document = documents[claim.document_version_id]
        paragraph = paragraphs[claim.paragraph_id]
        sections.extend(
            [
                f"## {index:02}. {task.id}",
                "",
                f"- Claim ID: `{claim.id}`",
                f"- Assigned target: `{claim.target.label}` (`{claim.target.identifier}`)",
                f"- Source: `{document.source_id}` — {document.title}",
                f"- Paragraph version: `{paragraph.id}` / `{paragraph.text_sha256}`",
                f"- Exact span: **{claim.verbatim_span}**",
                f"- Offsets: `{claim.span_start}:{claim.span_end}`",
                "",
                "<details><summary>Full normalized abstract paragraph</summary>",
                "",
                paragraph.text,
                "",
                "</details>",
                "",
                "```yaml",
                f"task_id: {task.id}",
                f"claim_id: {claim.id}",
                f"reviewer_slot: {reviewer_slot}",
                "reviewer_disposition: null",
                "reviewer_target_grounding: null",
                "reviewer_evidence_role: null",
                "reviewer_is_atomic_claim: null",
                "reviewer_theme: null",
                "reviewer_polarity: null",
                "reviewer_direction: null",
                "reviewer_replacement_claim_id: null",
                "reviewer_rationale: null",
                "reviewer_confirmed: false",
                "```",
                "",
            ]
        )
    sections.extend(
        [
            "## Submission sign-off",
            "",
            "Record reviewer ID, role, signed time, signature statement, `human_signed_off=true`, "
            "and `status=signed` at submission level after confirming all 30 tasks.",
            "",
        ]
    )
    return "\n".join(sections)


def render_model_discrepancy_report(
    batch: LiteratureReviewBatch, store: LiteratureStore
) -> str:
    claims = {item.id: item for item in store.snapshot.provisional_gold_claims}
    sections = [
        "# P2.2 Model-assisted pre-review discrepancies",
        "",
        "> Triage only. These are not human reviews and are not eligible for adjudication.",
        "",
        f"Agreement: {batch.summary.agreement_count}/{batch.summary.task_count}; "
        f"disagreements: {batch.summary.disagreement_count}.",
        "",
    ]
    for result in batch.review_results:
        if result.agreement:
            continue
        claim = claims[result.claim_id]
        sections.extend(
            [
                f"## {result.task_id}",
                "",
                f"> {claim.verbatim_span}",
                "",
                f"Disagreement fields: `{', '.join(result.disagreement_fields)}`",
                "",
            ]
        )
        for review in result.reviews:
            sections.extend(
                [
                    f"- Pass {review.review_pass}: `{review.disposition.value}` / "
                    f"`{review.proposed_theme.value if review.proposed_theme else 'none'}` / "
                    f"`{review.proposed_polarity.value if review.proposed_polarity else 'none'}` / "
                    f"`{review.proposed_direction.value if review.proposed_direction else 'none'}`",
                    f"  - {review.rationale}",
                ]
            )
        sections.append("")
    return "\n".join(sections)


def write_review_artifacts(
    output_dir: Path, store: LiteratureStore | None = None
) -> LiteratureReviewBatch:
    selected_store = store or load_default_literature_store()
    output_dir.mkdir(parents=True, exist_ok=True)
    batch = write_review_batch(output_dir / "literature_review_batch.json", selected_store)
    (output_dir / "human_reviewer_a.md").write_text(
        render_human_review_packet(selected_store, "A"), encoding="utf-8"
    )
    (output_dir / "human_reviewer_b.md").write_text(
        render_human_review_packet(selected_store, "B"), encoding="utf-8"
    )
    (output_dir / "model_pre_review_discrepancies.md").write_text(
        render_model_discrepancy_report(batch, selected_store), encoding="utf-8"
    )
    return batch


def review_quality_report(
    batch: LiteratureReviewBatch, store: LiteratureStore | None = None
) -> dict[str, Any]:
    selected_store = store or load_default_literature_store()
    expected_tasks = {item.id for item in selected_store.snapshot.double_review_tasks}
    actual_tasks = {item.task_id for item in batch.review_results}
    return {
        **batch.summary.model_dump(mode="json"),
        "batch_id": batch.id,
        "source_snapshot_id": batch.source_snapshot_id,
        "all_fixed_tasks_covered": actual_tasks == expected_tasks,
        "model_pre_review_complete": batch.summary.model_pass_count == 60,
        "human_double_review_complete": False,
        "eligible_for_adjudication_count": sum(
            item.eligible_for_adjudication for item in batch.review_results
        ),
        "annotation_layer": batch.annotation_layer,
        "p3_gate_passed": batch.p3_gate_passed,
        "warning": batch.warning,
    }
