"""Resolve unstructured reviewer comments without claiming formal review or adjudication."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from targetideator.claims.models import ClaimPolarity
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.io import write_json
from targetideator.literature.models import ClaimDirection, LiteratureClaimTheme
from targetideator.literature.review import load_default_review_batch
from targetideator.literature.review_models import (
    EvidenceRole,
    ExpertCommentResolutionBatch,
    ExternalCommentRecommendation,
    ProposedCommentResolution,
    ReviewDisposition,
    TargetGrounding,
)
from targetideator.literature.store import LiteratureStore, load_default_literature_store

RESOLUTION_BATCH_ID = "ti:literature-review-resolution:crohns-p2-2-comments-v1"
RESOLUTION_CREATED_AT = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)

COMMENT_A = [
    "accept", "accept", "accept", "reject", "accept", "reject_or_revise",
    "accept", "reject", "accept", "reject", "reject", "accept", "reject",
    "accept", "accept", "reject", "accept", "accept", "accept", "accept",
    "revise", "accept", "revise", "accept", "accept", "reject", "accept",
    "accept", "reject", "accept",
]
COMMENT_B = [
    "accept", "accept", "accept", "reject", "accept", "reject", "accept",
    "reject", "reject", "reject", "reject", "accept", "reject", "accept",
    "accept", "reject", "accept", "accept", "accept_or_revise", "accept",
    "reject", "accept", "revise", "accept", "accept", "reject", "accept",
    "accept", "reject", "accept",
]

# disposition, grounding, evidence role, theme, polarity, direction, replacement claim ID, rationale
PROPOSED: list[tuple[Any, ...]] = [
    ("accept", "explicit", "secondary_or_background", "mechanism", "supports", "increases", None, "IL-23 is explicitly assigned a pathogenic inflammatory role."),
    ("accept", "explicit", "secondary_or_background", "therapeutic_effect", "qualifies", "unknown", None, "A possible IL-23/IL-17 therapeutic target is stated, but the intervention direction is not explicit."),
    ("accept", "explicit", "direct_result", "mechanism", "supports", "increases", None, "The experiments explicitly identify IL-23 as an intestinal effector cytokine."),
    ("reject", "wrong_target", "not_target_evidence", None, None, None, None, "The association is with IL23R rather than IL23A."),
    ("accept", "explicit", "secondary_or_background", "mechanism", "supports", "increases", None, "The first clause reports IL-23-driven IL-17 secretion; uncertainty applies to a narrower differentiation question."),
    ("reject", "explicit", "secondary_or_background", None, None, None, None, "The sentence does not state an atomic IL-23 proposition and primarily discusses unresolved IL-17 function."),
    ("revise", "explicit", "direct_result", "mechanism", "supports", "increases", "ti:literature-claim:il23a-23034650-1543-1663", "Both comments used a later IL-23 result, not the reviewed background span; link the existing exact result claim instead."),
    ("revise", "explicit", "negative_result", "mechanism", "refutes", "unknown", "ti:literature-claim:il23a-23698371-1168-1292", "The reviewed span lacks IL-23; the existing exact independence sentence is the valid negative claim."),
    ("accept", "explicit", "negative_result", "mechanism", "refutes", "context_dependent", None, "A cell-specific negative result is valid evidence and should be accepted with refutes polarity, not rejected for being negative."),
    ("reject", "absent", "not_target_evidence", None, None, None, None, "The sentence reports IL-15 dysregulation without a JAK1 proposition."),
    ("reject", "wrong_target", "not_target_evidence", None, None, None, None, "The inhibitor result concerns Jak3, not JAK1."),
    ("accept", "explicit", "secondary_or_background", "safety_or_limitation", "qualifies", "context_dependent", None, "The JAK1-selective inhibitor response and cross-disease liver-toxicity limitation are both explicit."),
    ("reject", "absent", "not_target_evidence", None, None, None, None, "This is generic IBD background with no JAK1 claim."),
    ("accept", "explicit", "direct_result", "mechanism", "qualifies", "unknown", None, "The repair effect is tentatively related to JAK1 signaling; pathway direction remains unstated."),
    ("accept", "explicit", "direct_result", "therapeutic_effect", "supports", "decreases", None, "The compound explicitly inhibits JAK1/2 phosphorylation."),
    ("reject", "absent", "not_target_evidence", None, None, None, None, "The H. pylori background sentence contains no JAK1 proposition."),
    ("accept", "explicit", "direct_result", "genetic_association", "supports", "unknown", None, "NOD2 is explicitly linked to Crohn susceptibility with a mechanistic hypothesis."),
    ("accept", "explicit", "secondary_or_background", "genetic_association", "supports", "unknown", None, "CARD15 is a NOD2 synonym and the sentence reports Crohn-associated mutations."),
    ("revise", "explicit", "negative_result", "disease_association", "refutes", "unknown", "ti:literature-claim:nod2-15082587-1310-1397", "The reviewed span lacks NOD2; the adjacent existing exact claim states no association with NOD2 status."),
    ("accept", "explicit", "direct_result", "mechanism", "supports", "increases", None, "NOD2 deficiency/Card15 mutation is linked to increased TLR2 and TH1 responses."),
    ("revise", "explicit", "secondary_or_background", "genetic_association", "supports", "unknown", None, "NOD2 is only a previously established background association while replication concerns other loci; retain only as secondary evidence."),
    ("revise", "explicit", "direct_result", "mechanism", "supports", "increases", "ti:literature-claim:nod2-23219392-444-608", "The reviewed CCR2 sentence lacks NOD2; use the existing exact NOD2-upregulation result claim."),
    ("revise", "explicit", "contextual_inference", "genetic_association", "supports", "unknown", "ti:literature-claim:nod2-27802154-682-897", "The conclusion is gene-set level; the existing risk-score composition span explicitly includes NOD2 but remains non-specific."),
    ("accept", "explicit", "direct_result", "disease_association", "supports", "increases", None, "TL1A/TNFSF15 expression is increased in affected Crohn tissue."),
    ("accept", "explicit", "direct_result", "mechanism", "supports", "increases", None, "TL1A/DR3 up-regulation is reported in two intestinal inflammation models."),
    ("reject", "absent", "not_target_evidence", None, None, None, None, "The sentence concerns MHC alleles and does not ground TNFSF15."),
    ("accept", "explicit", "direct_result", "genetic_association", "supports", "unknown", None, "A TNFSF15 variant association with Crohn disease is explicitly confirmed."),
    ("accept", "explicit", "direct_result", "mechanism", "supports", "increases", None, "TL1A/TNFSF15 is explicitly reported to costimulate T cells and promote autoimmune models."),
    ("reject", "absent", "not_target_evidence", None, None, None, None, "This generic trans-ancestry conclusion does not ground TNFSF15."),
    ("accept", "explicit", "direct_result", "mechanism", "supports", "increases", None, "IBD-associated microbiota is explicitly reported to induce TL1A release."),
]


def default_comment_resolution_path() -> Path:
    return fixture_path("literature_comment_resolution.json")


def build_comment_resolution(
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    store: LiteratureStore | None = None,
) -> ExpertCommentResolutionBatch:
    selected_store = store or load_default_literature_store()
    model_batch = load_default_review_batch()
    if len(PROPOSED) != 30 or len(COMMENT_A) != 30 or len(COMMENT_B) != 30:
        raise ValueError("comment resolution must cover the fixed 30-task batch")
    claim_ids = {item.id for item in selected_store.snapshot.provisional_gold_claims}
    resolutions: list[ProposedCommentResolution] = []
    for index, (task, model_result, proposed) in enumerate(
        zip(selected_store.snapshot.double_review_tasks, model_batch.review_results, PROPOSED, strict=True)
    ):
        disposition, grounding, role, theme, polarity, direction, replacement, rationale = proposed
        if replacement is not None and replacement not in claim_ids:
            raise ValueError(f"replacement claim {replacement} is not in provisional gold")
        resolutions.append(
            ProposedCommentResolution(
                task_id=task.id,
                claim_id=task.claim_id,
                external_comments=[
                    ExternalCommentRecommendation(
                        source_file="a_reviewer.md", recommendation=COMMENT_A[index]
                    ),
                    ExternalCommentRecommendation(
                        source_file="b_reviewer.md", recommendation=COMMENT_B[index]
                    ),
                ],
                model_pass_dispositions={
                    review.review_pass: review.disposition for review in model_result.reviews
                },
                proposed_disposition=ReviewDisposition(disposition),
                proposed_target_grounding=TargetGrounding(grounding),
                proposed_evidence_role=EvidenceRole(role),
                proposed_theme=LiteratureClaimTheme(theme) if theme else None,
                proposed_polarity=ClaimPolarity(polarity) if polarity else None,
                proposed_direction=ClaimDirection(direction) if direction else None,
                replacement_claim_id=replacement,
                rationale=rationale,
            )
        )
    return ExpertCommentResolutionBatch(
        id=RESOLUTION_BATCH_ID,
        review_batch_id=model_batch.id,
        source_snapshot_id=selected_store.snapshot.id,
        created_at=RESOLUTION_CREATED_AT,
        source_file_sha256={
            reviewer_a_path.name: file_sha256(reviewer_a_path),
            reviewer_b_path.name: file_sha256(reviewer_b_path),
        },
        resolutions=resolutions,
        proposed_accept_count=sum(item.proposed_disposition == ReviewDisposition.ACCEPT for item in resolutions),
        proposed_reject_count=sum(item.proposed_disposition == ReviewDisposition.REJECT for item in resolutions),
        proposed_revise_count=sum(item.proposed_disposition == ReviewDisposition.REVISE for item in resolutions),
    )


def write_comment_resolution(
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    output_path: Path,
) -> ExpertCommentResolutionBatch:
    batch = build_comment_resolution(reviewer_a_path, reviewer_b_path)
    write_json(output_path, batch.model_dump(mode="json"))
    return batch


def load_default_comment_resolution() -> ExpertCommentResolutionBatch:
    return ExpertCommentResolutionBatch.model_validate(
        _load_json(default_comment_resolution_path())
    )


def render_comment_resolution(batch: ExpertCommentResolutionBatch) -> str:
    lines = [
        "# P2.2 Reviewer comments × model pre-review resolution",
        "",
        "> This is a proposed resolution of unstructured comments, not a signed human review or adjudication.",
        "",
        f"Proposed outcomes: accept {batch.proposed_accept_count}, reject {batch.proposed_reject_count}, "
        f"revise {batch.proposed_revise_count}. Final gold: 0. P3 gate: blocked.",
        "",
        "Applied policies:",
        "",
        "- exact-span semantics win over conclusions found only in adjacent sentences;",
        "- negative target-grounded results are accepted with `refutes`, not rejected merely for being negative;",
        "- receptor/pathway neighbors are not silently collapsed into the assigned gene;",
        "- direct results, secondary/background assertions, contextual inference, and negative results are distinct evidence roles;",
        "- `revise` links an existing exact replacement claim where one is already present, avoiding duplicate claims.",
        "",
        "| # | External A | External B | Model A/B | Proposed | Evidence role | Replacement |",
        "|---:|---|---|---|---|---|---|",
    ]
    for index, item in enumerate(batch.resolutions, start=1):
        external = [entry.recommendation for entry in item.external_comments]
        model = item.model_pass_dispositions
        lines.append(
            f"| {index} | {external[0]} | {external[1]} | "
            f"{model['A'].value}/{model['B'].value} | {item.proposed_disposition.value} | "
            f"{item.proposed_evidence_role.value} | `{item.replacement_claim_id or '-'}` |"
        )
    lines.extend(["", "## Rationale by task", ""])
    for index, item in enumerate(batch.resolutions, start=1):
        lines.extend(
            [
                f"### {index:02}. {item.task_id}",
                "",
                item.rationale,
                "",
            ]
        )
    return "\n".join(lines)


def write_comment_resolution_artifacts(
    reviewer_a_path: Path,
    reviewer_b_path: Path,
    output_dir: Path,
) -> ExpertCommentResolutionBatch:
    output_dir.mkdir(parents=True, exist_ok=True)
    batch = write_comment_resolution(
        reviewer_a_path,
        reviewer_b_path,
        output_dir / "literature_comment_resolution.json",
    )
    (output_dir / "literature_comment_resolution.md").write_text(
        render_comment_resolution(batch), encoding="utf-8"
    )
    return batch


def comment_resolution_quality_report(
    batch: ExpertCommentResolutionBatch,
    store: LiteratureStore | None = None,
) -> dict[str, Any]:
    selected_store = store or load_default_literature_store()
    known_claims = {item.id for item in selected_store.snapshot.provisional_gold_claims}
    known_tasks = {item.id for item in selected_store.snapshot.double_review_tasks}
    return {
        "batch_id": batch.id,
        "resolution_count": len(batch.resolutions),
        "all_fixed_tasks_covered": {item.task_id for item in batch.resolutions} == known_tasks,
        "all_replacements_exist": all(
            item.replacement_claim_id is None or item.replacement_claim_id in known_claims
            for item in batch.resolutions
        ),
        "replacement_claim_count": sum(
            item.replacement_claim_id is not None for item in batch.resolutions
        ),
        "proposed_accept_count": batch.proposed_accept_count,
        "proposed_reject_count": batch.proposed_reject_count,
        "proposed_revise_count": batch.proposed_revise_count,
        "formal_human_review_count": batch.formal_human_review_count,
        "adjudicated_count": batch.adjudicated_count,
        "final_gold_claim_count": batch.final_gold_claim_count,
        "p3_gate_passed": batch.p3_gate_passed,
        "status": batch.status,
    }
