"""Human-review drafts, signature checks, and the adjudication readiness gate."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.literature.comment_resolution import load_default_comment_resolution
from targetideator.literature.review_models import (
    AdjudicationQueueEntry,
    BlindHumanReviewDecision,
    BlindHumanReviewSubmission,
    HumanReviewDecision,
    HumanReviewReadiness,
    HumanReviewSubmission,
    LiteratureAdjudicationQueue,
)
from targetideator.literature.store import LiteratureStore, load_default_literature_store


class AdjudicationBlockedError(RuntimeError):
    """Raised when unsigned or incomplete submissions are sent to adjudication."""


_BLIND_EVIDENCE_FIELDS = (
    "task_id",
    "claim_id",
    "reviewer_slot",
    "assigned_target_label",
    "assigned_target_identifier",
    "source_id",
    "source_title",
    "pmid",
    "pmcid",
    "doi",
    "paragraph_id",
    "paragraph_sha256",
    "paragraph_text",
    "verbatim_span",
    "span_start",
    "span_end",
)


def build_human_review_draft(reviewer_slot: str) -> HumanReviewSubmission:
    if reviewer_slot not in {"A", "B"}:
        raise ValueError("reviewer slot must be A or B")
    resolution = load_default_comment_resolution()
    decisions: list[HumanReviewDecision] = []
    source_index = 0 if reviewer_slot == "A" else 1
    for item in resolution.resolutions:
        decisions.append(
            HumanReviewDecision(
                task_id=item.task_id,
                claim_id=item.claim_id,
                reviewer_slot=reviewer_slot,
                source_recommendation=item.external_comments[source_index].recommendation,
                system_proposed_disposition=item.proposed_disposition,
                system_proposed_target_grounding=item.proposed_target_grounding,
                system_proposed_evidence_role=item.proposed_evidence_role,
                system_proposed_theme=item.proposed_theme,
                system_proposed_polarity=item.proposed_polarity,
                system_proposed_direction=item.proposed_direction,
                system_replacement_claim_id=item.replacement_claim_id,
            )
        )
    return HumanReviewSubmission(
        id=stable_id("human-review-submission", f"p2-2-fixed-30-reviewer-{reviewer_slot.lower()}-draft-v1"),
        source_snapshot_id=resolution.source_snapshot_id,
        review_batch_id=resolution.review_batch_id,
        comment_resolution_id=resolution.id,
        reviewer_slot=reviewer_slot,
        decisions=decisions,
    )


def write_human_review_drafts(output_dir: Path) -> tuple[HumanReviewSubmission, HumanReviewSubmission]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reviewer_a = build_human_review_draft("A")
    reviewer_b = build_human_review_draft("B")
    write_json(output_dir / "human_review_a_draft.json", reviewer_a.model_dump(mode="json"))
    write_json(output_dir / "human_review_b_draft.json", reviewer_b.model_dump(mode="json"))
    return reviewer_a, reviewer_b


def build_blind_human_review_submission(
    reviewer_slot: str, store: LiteratureStore | None = None
) -> BlindHumanReviewSubmission:
    """Build the evidence-complete editable submission without model recommendations."""

    if reviewer_slot not in {"A", "B"}:
        raise ValueError("reviewer slot must be A or B")
    selected_store = store or load_default_literature_store()
    resolution = load_default_comment_resolution()
    claims = {item.id: item for item in selected_store.snapshot.provisional_gold_claims}
    documents = {item.id: item for item in selected_store.snapshot.documents}
    paragraphs = {item.id: item for item in selected_store.snapshot.paragraphs}
    decisions: list[BlindHumanReviewDecision] = []
    for task in selected_store.snapshot.double_review_tasks:
        claim = claims[task.claim_id]
        document = documents[claim.document_version_id]
        paragraph = paragraphs[claim.paragraph_id]
        decisions.append(
            BlindHumanReviewDecision(
                task_id=task.id,
                claim_id=claim.id,
                reviewer_slot=reviewer_slot,
                assigned_target_label=claim.target.label,
                assigned_target_identifier=claim.target.identifier,
                source_id=document.source_id,
                source_title=document.title,
                pmid=document.pmid,
                pmcid=document.pmcid,
                doi=document.doi,
                paragraph_id=paragraph.id,
                paragraph_sha256=paragraph.text_sha256,
                paragraph_text=paragraph.text,
                verbatim_span=claim.verbatim_span,
                span_start=claim.span_start,
                span_end=claim.span_end,
            )
        )
    return BlindHumanReviewSubmission(
        id=stable_id(
            "blind-human-review-submission",
            f"p2-2-fixed-30-reviewer-{reviewer_slot.lower()}-v1",
        ),
        source_snapshot_id=selected_store.snapshot.id,
        review_batch_id=resolution.review_batch_id,
        reviewer_slot=reviewer_slot,
        decisions=decisions,
    )


def render_blind_human_review_packet(submission: BlindHumanReviewSubmission) -> str:
    """Render a human-readable companion; the JSON submission remains authoritative."""

    sections = [
        f"# P2.2 Blind Human Review — reviewer {submission.reviewer_slot}",
        "",
        "> Independent review. No model-assisted labels or other-reviewer decisions are included.",
        "> Fill `review_submission.json`; this Markdown file is an evidence-readable companion.",
        "",
        "Required per item: disposition, target grounding, evidence role, atomicity, rationale, "
        "and `reviewer_confirmed=true`. Accept/revise also require theme, polarity, and direction; "
        "reject requires those three fields to remain null.",
        "",
    ]
    for index, item in enumerate(submission.decisions, start=1):
        identifiers = [item.source_id]
        if item.doi:
            identifiers.append(f"DOI {item.doi}")
        sections.extend(
            [
                f"## {index:02}. {item.task_id}",
                "",
                f"- Claim ID: `{item.claim_id}`",
                f"- Assigned target: `{item.assigned_target_label}` "
                f"(`{item.assigned_target_identifier}`)",
                f"- Source: `{' / '.join(identifiers)}` — {item.source_title}",
                f"- Paragraph: `{item.paragraph_id}` / `{item.paragraph_sha256}`",
                f"- Exact span: **{item.verbatim_span}**",
                f"- Offsets: `{item.span_start}:{item.span_end}`",
                "",
                "<details><summary>Full normalized abstract paragraph</summary>",
                "",
                item.paragraph_text,
                "",
                "</details>",
                "",
                "```yaml",
                f"task_id: {item.task_id}",
                f"claim_id: {item.claim_id}",
                f"reviewer_slot: {submission.reviewer_slot}",
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
            "Complete the top-level reviewer identity, role, signature statement, signed time, "
            "`human_signed_off=true`, and `status=signed` in `review_submission.json` only after "
            "all 30 decisions are confirmed.",
            "",
        ]
    )
    return "\n".join(sections)


def _blind_bundle_readme(slot: str) -> str:
    return f"""# Reviewer {slot} offline bundle

This is an independent, blinded 30-item review. Do not inspect model pre-review,
system-proposed fields, expert-review reports, or the other reviewer's files before signing.

1. Read `review_packet.md` for exact spans and full paragraph context.
2. Edit only reviewer fields in `review_submission.json`.
3. Set every `reviewer_confirmed` to `true` after checking the item.
4. Complete the top-level reviewer identity, role, signature, timestamp, and signed status.
5. Return the signed `review_submission.json`; do not rename task or claim IDs.

Allowed values and decision rules are included in `review_guideline.md`; the exact machine
contract is `review_submission.schema.json`.
The `manifest.json` checksums cover the original blank packet and submission. A changed
submission checksum after annotation is expected; the packet checksum should remain unchanged.
"""


def _blind_bundle_guideline() -> str:
    return """# Literature claim blind-review guideline

Review the bold exact span as the claim. Use the full paragraph only to resolve explicit
context or pronouns; do not import a target, result, or conclusion from an adjacent sentence.

Decision order:

1. Is the span an atomic, truth-evaluable proposition?
2. Is it about the assigned target rather than a related target?
3. Is target grounding explicit, uniquely contextual, absent, or wrong-target?
4. Is this a direct result, background/secondary statement, contextual inference,
   target-grounded negative result, or not-target evidence?
5. Do theme, polarity, and direction match only what the span supports?

Allowed values:

- `reviewer_disposition`: `accept`, `reject`, `revise`.
- `reviewer_target_grounding`: `explicit`, `contextual`, `absent`, `wrong_target`.
- `reviewer_evidence_role`: `direct_result`, `secondary_or_background`,
  `contextual_inference`, `negative_result`, `not_target_evidence`.
- `reviewer_theme`: `genetic_association`, `disease_association`, `mechanism`,
  `therapeutic_effect`, `biomarker`, `safety_or_limitation`.
- `reviewer_polarity`: `supports`, `refutes`, `qualifies`, `neutral`.
- `reviewer_direction`: `increases`, `decreases`, `context_dependent`, `unknown`.

For `reject`, leave theme/polarity/direction null. For `accept` or `revise`, fill all three.
A valid target-grounded negative finding is not automatically rejected: use `negative_result`
and usually `refutes`. Do not silently merge IL23R with IL23A or Jak3 with JAK1.

Use `reviewer_replacement_claim_id` only when a valid exact replacement claim ID is already
known; otherwise explain the required replacement span in the rationale. Confirm an item only
after every required field is complete. Sign the submission only after all 30 items are confirmed.
"""


def write_blind_review_bundles(
    output_dir: Path, store: LiteratureStore | None = None
) -> tuple[BlindHumanReviewSubmission, BlindHumanReviewSubmission]:
    """Write isolated A/B reviewer directories with no model-assisted content."""

    selected_store = store or load_default_literature_store()
    submissions = (
        build_blind_human_review_submission("A", selected_store),
        build_blind_human_review_submission("B", selected_store),
    )
    for submission in submissions:
        reviewer_dir = output_dir / f"Reviewer_{submission.reviewer_slot}"
        reviewer_dir.mkdir(parents=True, exist_ok=True)
        readme_path = reviewer_dir / "README.md"
        guideline_path = reviewer_dir / "review_guideline.md"
        packet_path = reviewer_dir / "review_packet.md"
        submission_path = reviewer_dir / "review_submission.json"
        schema_path = reviewer_dir / "review_submission.schema.json"
        readme_path.write_text(_blind_bundle_readme(submission.reviewer_slot), encoding="utf-8")
        guideline_path.write_text(_blind_bundle_guideline(), encoding="utf-8")
        packet_path.write_text(render_blind_human_review_packet(submission), encoding="utf-8")
        write_json(submission_path, submission.model_dump(mode="json"))
        write_json(schema_path, BlindHumanReviewSubmission.model_json_schema())
        write_json(
            reviewer_dir / "manifest.json",
            {
                "schema_version": "2.2-blind-review-bundle.1",
                "reviewer_slot": submission.reviewer_slot,
                "source_snapshot_id": submission.source_snapshot_id,
                "review_batch_id": submission.review_batch_id,
                "task_count": len(submission.decisions),
                "contains_model_assistance": False,
                "contains_other_reviewer_decisions": False,
                "files": {
                    "README.md": file_sha256(readme_path),
                    "review_guideline.md": file_sha256(guideline_path),
                    "review_packet.md": file_sha256(packet_path),
                    "review_submission.json": file_sha256(submission_path),
                    "review_submission.schema.json": file_sha256(schema_path),
                },
            },
        )
    return submissions


def load_blind_human_review_submission(path: Path) -> BlindHumanReviewSubmission:
    return BlindHumanReviewSubmission.model_validate(_load_json(path))


def validate_blind_human_review_evidence(
    blind: BlindHumanReviewSubmission,
    store: LiteratureStore | None = None,
) -> None:
    """Verify all immutable IDs and evidence against the frozen 30-task snapshot."""

    selected_store = store or load_default_literature_store()
    expected = build_blind_human_review_submission(blind.reviewer_slot, selected_store)
    if (
        blind.source_snapshot_id != expected.source_snapshot_id
        or blind.review_batch_id != expected.review_batch_id
    ):
        raise ValueError("blind review references the wrong snapshot or review batch")
    expected_by_task = {item.task_id: item for item in expected.decisions}
    incoming_by_task = {item.task_id: item for item in blind.decisions}
    if incoming_by_task.keys() != expected_by_task.keys():
        raise ValueError("blind review does not cover the fixed 30-task set")
    for task_id, item in incoming_by_task.items():
        expected_item = expected_by_task[task_id]
        for field in _BLIND_EVIDENCE_FIELDS:
            if getattr(item, field) != getattr(expected_item, field):
                raise ValueError(f"blind review immutable evidence changed: {task_id} / {field}")


def finalize_blind_human_review_submission(
    blind: BlindHumanReviewSubmission,
    store: LiteratureStore | None = None,
) -> HumanReviewSubmission:
    """Validate signed blind evidence and merge internal proposals only after sign-off."""

    if not blind.human_signed_off or blind.status != "signed":
        raise ValueError("blind review must be fully confirmed and signed before finalization")
    selected_store = store or load_default_literature_store()
    validate_blind_human_review_evidence(blind, selected_store)

    resolution = load_default_comment_resolution()
    resolution_by_task = {item.task_id: item for item in resolution.resolutions}
    source_index = 0 if blind.reviewer_slot == "A" else 1
    decisions: list[HumanReviewDecision] = []
    for item in blind.decisions:
        proposed = resolution_by_task[item.task_id]
        decisions.append(
            HumanReviewDecision(
                task_id=item.task_id,
                claim_id=item.claim_id,
                reviewer_slot=item.reviewer_slot,
                source_recommendation=proposed.external_comments[source_index].recommendation,
                system_proposed_disposition=proposed.proposed_disposition,
                system_proposed_target_grounding=proposed.proposed_target_grounding,
                system_proposed_evidence_role=proposed.proposed_evidence_role,
                system_proposed_theme=proposed.proposed_theme,
                system_proposed_polarity=proposed.proposed_polarity,
                system_proposed_direction=proposed.proposed_direction,
                system_replacement_claim_id=proposed.replacement_claim_id,
                reviewer_disposition=item.reviewer_disposition,
                reviewer_target_grounding=item.reviewer_target_grounding,
                reviewer_evidence_role=item.reviewer_evidence_role,
                reviewer_is_atomic_claim=item.reviewer_is_atomic_claim,
                reviewer_theme=item.reviewer_theme,
                reviewer_polarity=item.reviewer_polarity,
                reviewer_direction=item.reviewer_direction,
                reviewer_replacement_claim_id=item.reviewer_replacement_claim_id,
                reviewer_rationale=item.reviewer_rationale,
                reviewer_confirmed=item.reviewer_confirmed,
            )
        )
    blind_sha256 = hashlib.sha256(
        canonical_json_bytes(blind.model_dump(mode="json"))
    ).hexdigest()
    return HumanReviewSubmission(
        id=stable_id(
            "human-review-submission",
            f"p2-2-fixed-30-reviewer-{blind.reviewer_slot.lower()}-signed-v1",
        ),
        source_snapshot_id=blind.source_snapshot_id,
        review_batch_id=blind.review_batch_id,
        comment_resolution_id=resolution.id,
        reviewer_slot=blind.reviewer_slot,
        review_mode="blind_independent",
        model_assistance_exposed_before_signoff=False,
        blind_input_sha256=blind_sha256,
        reviewer_id=blind.reviewer_id,
        reviewer_role=blind.reviewer_role,
        decisions=decisions,
        human_signed_off=True,
        signed_at=blind.signed_at,
        signature_statement=blind.signature_statement,
        status="signed",
    )


def load_human_review_submission(path: Path) -> HumanReviewSubmission:
    return HumanReviewSubmission.model_validate(_load_json(path))


def assess_human_review_readiness(
    reviewer_a: HumanReviewSubmission,
    reviewer_b: HumanReviewSubmission,
    store: LiteratureStore | None = None,
) -> HumanReviewReadiness:
    selected_store = store or load_default_literature_store()
    expected_task_claims = {
        item.id: item.claim_id for item in selected_store.snapshot.double_review_tasks
    }
    expected_tasks = set(expected_task_claims)
    blockers: list[str] = []
    if reviewer_a.reviewer_slot != "A" or reviewer_b.reviewer_slot != "B":
        blockers.append("submissions must occupy reviewer slots A and B")
    if reviewer_a.source_snapshot_id != reviewer_b.source_snapshot_id:
        blockers.append("submissions reference different source snapshots")
    if any(
        item.source_snapshot_id != selected_store.snapshot.id
        for item in (reviewer_a, reviewer_b)
    ):
        blockers.append("submissions do not reference the frozen literature snapshot")
    if reviewer_a.review_batch_id != reviewer_b.review_batch_id:
        blockers.append("submissions reference different review batches")
    expected_review_batch_id = load_default_comment_resolution().review_batch_id
    if any(
        item.review_batch_id != expected_review_batch_id
        for item in (reviewer_a, reviewer_b)
    ):
        blockers.append("submissions do not reference the frozen review batch")
    task_sets = [
        {item.task_id for item in reviewer_a.decisions},
        {item.task_id for item in reviewer_b.decisions},
    ]
    missing = [sorted(expected_tasks - item) for item in task_sets]
    unexpected = [sorted(item - expected_tasks) for item in task_sets]
    if any(missing) or any(unexpected):
        blockers.append("both submissions must cover the fixed 30-task set")
    task_claim_mismatches = sorted(
        {
            decision.task_id
            for submission in (reviewer_a, reviewer_b)
            for decision in submission.decisions
            if expected_task_claims.get(decision.task_id) != decision.claim_id
        }
    )
    if task_claim_mismatches:
        blockers.append("one or more task-to-claim bindings differ from the frozen batch")
    confirmed_a = sum(item.reviewer_confirmed for item in reviewer_a.decisions)
    confirmed_b = sum(item.reviewer_confirmed for item in reviewer_b.decisions)
    unconfirmed_a = sorted(
        item.task_id for item in reviewer_a.decisions if not item.reviewer_confirmed
    )
    unconfirmed_b = sorted(
        item.task_id for item in reviewer_b.decisions if not item.reviewer_confirmed
    )
    if confirmed_a != len(expected_tasks):
        blockers.append("reviewer A has not confirmed all 30 decisions")
    if confirmed_b != len(expected_tasks):
        blockers.append("reviewer B has not confirmed all 30 decisions")
    signed_count = sum(
        item.human_signed_off for item in (reviewer_a, reviewer_b)
    )
    if signed_count != 2:
        blockers.append("both human review submissions must be signed")
    distinct_reviewers = bool(
        reviewer_a.reviewer_id
        and reviewer_b.reviewer_id
        and reviewer_a.reviewer_id != reviewer_b.reviewer_id
    )
    if not distinct_reviewers:
        blockers.append("reviewer A and B must have distinct human identities")
    blind_count = sum(
        item.review_mode == "blind_independent"
        and not item.model_assistance_exposed_before_signoff
        and item.blind_input_sha256 is not None
        for item in (reviewer_a, reviewer_b)
    )
    if blind_count != 2:
        blockers.append("both submissions must originate from blinded pre-signoff inputs")
    ready = not blockers
    return HumanReviewReadiness(
        source_snapshot_id=selected_store.snapshot.id,
        review_batch_id=reviewer_a.review_batch_id,
        submission_ids=[reviewer_a.id, reviewer_b.id],
        task_count=len(expected_tasks),
        reviewer_a_confirmed_count=confirmed_a,
        reviewer_b_confirmed_count=confirmed_b,
        reviewer_a_unconfirmed_task_ids=unconfirmed_a,
        reviewer_b_unconfirmed_task_ids=unconfirmed_b,
        reviewer_a_missing_task_ids=missing[0],
        reviewer_b_missing_task_ids=missing[1],
        reviewer_a_unexpected_task_ids=unexpected[0],
        reviewer_b_unexpected_task_ids=unexpected[1],
        task_claim_mismatch_ids=task_claim_mismatches,
        signed_submission_count=signed_count,
        distinct_human_reviewers=distinct_reviewers,
        blind_independent_submission_count=blind_count,
        blocking_reasons=blockers,
        eligible_for_adjudication=ready,
        status="ready_for_adjudication" if ready else "blocked",
    )


def _review_value_map(decision: HumanReviewDecision) -> dict[str, Any]:
    return {
        "disposition": decision.reviewer_disposition,
        "target_grounding": decision.reviewer_target_grounding,
        "evidence_role": decision.reviewer_evidence_role,
        "is_atomic_claim": decision.reviewer_is_atomic_claim,
        "theme": decision.reviewer_theme,
        "polarity": decision.reviewer_polarity,
        "direction": decision.reviewer_direction,
        "replacement_claim_id": decision.reviewer_replacement_claim_id,
    }


def build_adjudication_queue(
    reviewer_a: HumanReviewSubmission,
    reviewer_b: HumanReviewSubmission,
    store: LiteratureStore | None = None,
) -> LiteratureAdjudicationQueue:
    selected_store = store or load_default_literature_store()
    readiness = assess_human_review_readiness(reviewer_a, reviewer_b, selected_store)
    if not readiness.eligible_for_adjudication:
        raise AdjudicationBlockedError("; ".join(readiness.blocking_reasons))
    decisions_b = {item.task_id: item for item in reviewer_b.decisions}
    entries: list[AdjudicationQueueEntry] = []
    for decision_a in reviewer_a.decisions:
        decision_b = decisions_b[decision_a.task_id]
        values_a = _review_value_map(decision_a)
        values_b = _review_value_map(decision_b)
        disagreements = [
            field for field in values_a if values_a[field] != values_b[field]
        ]
        entries.append(
            AdjudicationQueueEntry(
                task_id=decision_a.task_id,
                claim_id=decision_a.claim_id,
                disagreement_fields=disagreements,
            )
        )
    disagreement_count = sum(bool(item.disagreement_fields) for item in entries)
    return LiteratureAdjudicationQueue(
        id=stable_id("adjudication-queue", "p2-2-fixed-30-v1"),
        source_snapshot_id=selected_store.snapshot.id,
        review_batch_id=reviewer_a.review_batch_id,
        reviewer_a_submission_id=reviewer_a.id,
        reviewer_b_submission_id=reviewer_b.id,
        entries=entries,
        agreement_count=len(entries) - disagreement_count,
        disagreement_count=disagreement_count,
    )


def human_review_gate_report(
    reviewer_a: HumanReviewSubmission,
    reviewer_b: HumanReviewSubmission,
) -> dict[str, Any]:
    return assess_human_review_readiness(reviewer_a, reviewer_b).model_dump(mode="json")
