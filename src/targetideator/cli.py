"""TargetIdeator command-line interface."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from targetideator.claims.store import (
    build_claim_graph_snapshot,
    load_default_claim_graph_store,
)
from targetideator.contracts import ProjectBundle
from targetideator.dossier import export_dossier
from targetideator.evidence.store import build_snapshot, load_default_store
from targetideator.evidence.historical_store import (
    build_historical_snapshot,
    load_default_historical_store,
)
from targetideator.evidence.clinical_store import (
    build_clinical_history_snapshot,
    default_clinical_snapshot_path,
    load_default_clinical_store,
)
from targetideator.ingestion.clinical_sources import (
    AACT_SNAPSHOTS,
    capture_aact_snapshot,
    capture_chembl_evidence_release,
    capture_chembl_molecules,
    capture_chembl_trial_mapping_release,
    capture_ctgov_current,
    capture_opentargets_drug_dictionary_release,
    capture_opentargets_full_drug_dictionary_release,
)
from targetideator.ingestion.opentargets import capture_live
from targetideator.ingestion.opentargets_archive import RELEASES, capture_archived_release
from targetideator.ingestion.independent_sources import (
    capture_drugcentral_independent_source,
)
from targetideator.ingestion.identity_sources import (
    capture_aact_interventions,
    write_identity_capture,
)
from targetideator.ingestion.outcome_sources import (
    LANDMARK_PAIRS,
    capture_broad_landmark_pair,
    capture_landmark_pair,
    write_gzip_capture,
)
from targetideator.io import default_seed_path, load_bundle, write_json
from targetideator.ideation.store import (
    load_default_ideation_store,
    write_ideation_artifacts,
)
from targetideator.falsification.store import (
    load_default_falsification_store,
    write_falsification_artifacts,
)
from targetideator.revision.store import (
    load_default_revision_store,
    write_revision_artifacts,
)
from targetideator.scoring.store import (
    load_default_decision_store,
    write_decision_artifacts,
)
from targetideator.outcomes.store import (
    load_default_outcome_store,
    write_outcome_artifacts,
)
from targetideator.outcomes.broad_store import (
    load_default_broad_outcome_store,
    write_broad_outcome_artifacts,
)
from targetideator.outcomes.identity_store import (
    default_trial_mapping_raw_path,
    load_default_identity_store,
    write_identity_artifacts,
)
from targetideator.outcomes.mapping_audit_store import (
    load_default_mapping_audit_store,
    write_mapping_audit_artifacts,
)
from targetideator.outcomes.drug_identity_store import (
    load_default_drug_identity_store,
    write_drug_identity_artifacts,
)
from targetideator.outcomes.assertion_history_store import (
    load_default_assertion_history_store,
    write_assertion_history_artifacts,
)
from targetideator.outcomes.independent_assertion_store import (
    load_default_independent_assertion_store,
    write_independent_assertion_artifacts,
)
from targetideator.outcomes.support_audit_store import (
    load_default_support_audit_store,
    write_support_audit_artifacts,
)
from targetideator.outcomes.selection_audit_store import (
    load_default_selection_audit_store,
    write_selection_audit_artifacts,
)
from targetideator.evaluation.store import (
    load_default_evaluation_store,
    write_evaluation_artifacts,
)
from targetideator.evaluation.robustness_store import (
    load_default_robustness_store,
    write_robustness_artifacts,
)
from targetideator.evaluation.cohort_stress_store import (
    load_default_cohort_stress_store,
    write_cohort_stress_artifacts,
)
from targetideator.evaluation.paired_control_store import (
    load_default_paired_control_store,
    write_paired_control_artifacts,
)
from targetideator.evaluation.counterevidence_ablation_store import (
    load_default_counterevidence_ablation_store,
    write_counterevidence_ablation_artifacts,
)
from targetideator.evaluation.synthesis_store import (
    load_default_claim_synthesis_store,
    write_claim_synthesis_artifacts,
)
from targetideator.evaluation.paper_bundle_store import (
    load_default_paper_bundle_store,
    write_paper_bundle_artifacts,
)
from targetideator.release.store import (
    load_default_release_audit_store,
    write_release_audit_artifacts,
)
from targetideator.release.data_bundle_store import (
    PackagingSplitStore,
    load_default_packaging_split_store,
    write_packaging_split_artifacts,
)
from targetideator.release.hydration_store import (
    load_default_hydration_store,
    write_hydration_artifacts,
)
from targetideator.release.retained_fixture_store import (
    load_default_retained_fixture_store,
    write_retained_fixture_artifacts,
)
from targetideator.release.disposition_store import (
    load_default_fixture_disposition_store,
    write_fixture_disposition_artifacts,
)
from targetideator.release.execution_plan_store import (
    load_default_execution_plan_store,
    write_execution_plan_artifacts,
)
from targetideator.release.replay_store import (
    ExecutionReplayStore,
    run_execution_replay,
)
from targetideator.release.replay_hardening_store import (
    ReplayHardeningStore,
    run_hardened_execution_replay,
    write_replay_hardening_artifacts,
)
from targetideator.release.canonical_store import (
    CanonicalAcceptanceStore,
    write_canonical_acceptance_artifacts,
)
from targetideator.release.convergence_store import (
    PackageConvergenceStore,
    run_package_convergence,
)
from targetideator.literature.ingestion import capture_europepmc_corpus
from targetideator.literature.human_review import (
    AdjudicationBlockedError,
    assess_human_review_readiness,
    build_adjudication_queue,
    finalize_blind_human_review_submission,
    load_blind_human_review_submission,
    load_human_review_submission,
    validate_blind_human_review_evidence,
    write_blind_review_bundles,
    write_human_review_drafts,
)
from targetideator.literature.comment_resolution import (
    build_comment_resolution,
    comment_resolution_quality_report,
    load_default_comment_resolution,
    write_comment_resolution_artifacts,
)
from targetideator.literature.review import (
    build_model_assisted_review_batch,
    load_default_review_batch,
    review_quality_report,
    write_review_artifacts,
)
from targetideator.literature.store import (
    build_literature_benchmark,
    load_default_literature_store,
)
from targetideator.manifest import write_manifest

app = typer.Typer(
    no_args_is_help=True,
    help="TargetIdeator frozen P0.2 contracts and P1 temporal-evidence tools.",
)


@app.command()
def validate(
    path: Annotated[Path | None, typer.Argument(help="Bundle JSON; defaults to packaged seed.")] = None,
) -> None:
    """Validate schema, IDs, references, and evidence cutoff."""

    bundle = load_bundle(path)
    source = path or default_seed_path()
    typer.echo(
        f"VALID {source} | snapshot={bundle.snapshot_id} | "
        f"hypotheses={len(bundle.hypotheses)} | evidence={len(bundle.evidence_records)}"
    )


@app.command("show-seed")
def show_seed() -> None:
    """Print the location and summary of the packaged seed fixture."""

    bundle = load_bundle()
    typer.echo(str(default_seed_path()))
    for hypothesis in bundle.hypotheses:
        typer.echo(
            f"- {hypothesis.target.entity.label}: {hypothesis.intervention.direction.value} "
            f"({hypothesis.curation_status.value})"
        )


@app.command("export-dossier")
def export_dossier_command(
    output_dir: Annotated[Path, typer.Option(help="Destination directory.")] = Path("outputs/p0"),
    input_path: Annotated[Path | None, typer.Option("--input", help="Bundle JSON.")] = None,
) -> None:
    """Export deterministic JSON, Markdown, and a reproducibility manifest."""

    bundle = load_bundle(input_path)
    artifacts = export_dossier(bundle, output_dir)
    manifest = write_manifest(bundle, artifacts, output_dir)
    for path in [*artifacts, manifest]:
        typer.echo(str(path))


@app.command("export-schema")
def export_schema(
    output_dir: Annotated[Path, typer.Option(help="Destination directory.")] = Path("outputs/schema"),
) -> None:
    """Export the versioned JSON Schema for ProjectBundle."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "project_bundle.schema.json"
    write_json(path, ProjectBundle.model_json_schema())
    typer.echo(str(path))


@app.command("capture-opentargets")
def capture_opentargets(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for raw, normalized, and manifest artifacts.")
    ] = Path("outputs/p1"),
    page_size: Annotated[
        int, typer.Option(min=1, max=500, help="Open Targets cursor page size.")
    ] = 500,
) -> None:
    """Capture and normalize the pinned Open Targets 26.09 subset."""

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "opentargets_26_09_raw.json"
    snapshot_path = output_dir / "opentargets_26_09_snapshot.json"
    manifest_path = output_dir / "opentargets_26_09_manifest.json"
    write_json(raw_path, capture_live(size=page_size))
    snapshot, manifest = build_snapshot(raw_path, snapshot_path, manifest_path)
    typer.echo(
        f"CAPTURED {snapshot.source.id} | records={len(snapshot.records)} | "
        f"complete={snapshot.source.complete_for_query}"
    )
    typer.echo(f"raw_sha256={manifest.raw_sha256}")
    typer.echo(f"normalized_sha256={manifest.normalized_sha256}")


@app.command("build-evidence")
def build_evidence(
    raw_path: Annotated[Path, typer.Argument(help="Saved Open Targets raw capture.")],
    output_dir: Annotated[
        Path, typer.Option(help="Destination for normalized snapshot and manifest.")
    ] = Path("outputs/p1"),
) -> None:
    """Rebuild P1 normalized evidence offline from a frozen raw capture."""

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / "opentargets_26_09_snapshot.json"
    manifest_path = output_dir / "opentargets_26_09_manifest.json"
    snapshot, manifest = build_snapshot(raw_path, snapshot_path, manifest_path)
    typer.echo(
        f"BUILT {snapshot.source.id} | records={len(snapshot.records)} | "
        f"normalized_sha256={manifest.normalized_sha256}"
    )


@app.command("verify-evidence")
def verify_evidence() -> None:
    """Verify packaged P1 checksums, lineage, mappings, and leakage canary."""

    report = load_default_store().quality_report()
    failed = (
        report["seed_panel_mapping_precision"] < 0.95
        or report["lineage_coverage"] < 1.0
        or report["source_url_coverage"] < 1.0
        or report["post_cutoff_leakage_count"] != 0
        or not report["complete_for_query"]
        or not report.get("raw_checksum_matches", False)
        or not report.get("normalized_checksum_matches", False)
        or not report.get("deterministic_rebuild_matches", False)
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-opentargets-archives")
def capture_opentargets_archives(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for archived raw subsets and timeline artifacts.")
    ] = Path("outputs/p1-history"),
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent Parquet downloads per release.")
    ] = 8,
) -> None:
    """Scan configured archived Parquet releases and build the replay timeline."""

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    for release in sorted(RELEASES, key=lambda value: RELEASES[value]):
        path = output_dir / f"opentargets_{release.replace('.', '_')}_associations_raw.json"
        write_json(path, capture_archived_release(release, workers=workers))
        raw_paths.append(path)
        typer.echo(f"CAPTURED Open Targets {release} -> {path}")
    snapshot_path = output_dir / "opentargets_historical_snapshot.json"
    manifest_path = output_dir / "opentargets_historical_manifest.json"
    snapshot, manifest = build_historical_snapshot(
        raw_paths, snapshot_path, manifest_path
    )
    typer.echo(
        f"BUILT {snapshot.id} | releases={len(snapshot.releases)} | "
        f"memberships={len(snapshot.records)} | sha256={manifest.normalized_sha256}"
    )


@app.command("build-history")
def build_history(
    raw_paths: Annotated[
        list[Path], typer.Argument(help="Two or more saved archived-release captures.")
    ],
    output_dir: Annotated[
        Path, typer.Option(help="Destination for historical snapshot and manifest.")
    ] = Path("outputs/p1-history"),
    snapshot_name: Annotated[
        str, typer.Option(help="Normalized snapshot filename within the destination.")
    ] = "opentargets_historical_snapshot.json",
    manifest_name: Annotated[
        str, typer.Option(help="Manifest filename within the destination.")
    ] = "opentargets_historical_manifest.json",
) -> None:
    """Rebuild the release-membership timeline without network access."""

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot, manifest = build_historical_snapshot(
        raw_paths,
        output_dir / snapshot_name,
        output_dir / manifest_name,
    )
    typer.echo(
        f"BUILT {snapshot.id} | releases={len(snapshot.releases)} | "
        f"memberships={len(snapshot.records)} | sha256={manifest.normalized_sha256}"
    )


@app.command("verify-history")
def verify_history() -> None:
    """Verify archived releases, checksums, cutoff canary, and deterministic replay."""

    report = load_default_historical_store().quality_report()
    failed = (
        report["release_count"] < 2
        or not report["all_release_queries_complete"]
        or report["archive_file_manifest_coverage"] < 1.0
        or report["seed_panel_mapping_precision"] < 0.95
        or report["post_cutoff_leakage_count"] != 0
        or not report["retrospective_replay_enabled"]
        or not report.get("raw_checksums_match", False)
        or not report.get("normalized_checksum_matches", False)
        or not report.get("deterministic_rebuild_matches", False)
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-clinical-history")
def capture_clinical_history(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P1.3 raw, normalized, and manifest artifacts.")
    ] = Path("outputs/p1-clinical-history"),
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent Parquet/API downloads.")
    ] = 8,
) -> None:
    """Capture ChEMBL evidence, AACT history, and current API validation records."""

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_paths: list[Path] = []
    evidence_captures: list[dict] = []
    for release in sorted(RELEASES, key=lambda value: RELEASES[value]):
        capture = capture_chembl_evidence_release(release, workers=workers)
        path = output_dir / f"chembl_{release.replace('.', '_')}_evidence_raw.json"
        write_json(path, capture)
        raw_paths.append(path)
        evidence_captures.append(capture)
        typer.echo(f"CAPTURED ChEMBL evidence {release} | rows={len(capture['rows'])}")

    nct_ids = sorted(
        {row["studyId"] for capture in evidence_captures for row in capture["rows"]}
    )
    drug_ids = sorted(
        {row["drugId"] for capture in evidence_captures for row in capture["rows"]}
    )
    for version in sorted(AACT_SNAPSHOTS, key=lambda value: AACT_SNAPSHOTS[value]):
        capture = capture_aact_snapshot(version, nct_ids)
        path = output_dir / f"aact_{version}_trials_raw.json"
        write_json(path, capture)
        raw_paths.append(path)
        typer.echo(
            f"CAPTURED AACT {version} | trials={len(capture['rows'])} | "
            f"dataset_rows={capture['dataset_row_count']}"
        )

    molecule_path = output_dir / "chembl_molecules_current_raw.json"
    write_json(molecule_path, capture_chembl_molecules(drug_ids, workers=workers))
    raw_paths.append(molecule_path)
    ctgov_path = output_dir / "ctgov_trials_current_raw.json"
    write_json(ctgov_path, capture_ctgov_current(nct_ids, workers=workers))
    raw_paths.append(ctgov_path)

    snapshot, manifest = build_clinical_history_snapshot(
        raw_paths,
        output_dir / "clinical_history_snapshot.json",
        output_dir / "clinical_history_manifest.json",
    )
    typer.echo(
        f"BUILT {snapshot.id} | evidence={len(snapshot.evidence_records)} | "
        f"trials={len(snapshot.trial_records)} | sha256={manifest.normalized_sha256}"
    )


@app.command("build-clinical-history")
def build_clinical_history(
    raw_paths: Annotated[
        list[Path], typer.Argument(help="The six saved P1.3 raw artifacts.")
    ],
    output_dir: Annotated[
        Path, typer.Option(help="Destination for normalized P1.3 artifacts.")
    ] = Path("outputs/p1-clinical-history"),
) -> None:
    """Rebuild evidence-string/trial history without network access."""

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot, manifest = build_clinical_history_snapshot(
        raw_paths,
        output_dir / "clinical_history_snapshot.json",
        output_dir / "clinical_history_manifest.json",
    )
    typer.echo(
        f"BUILT {snapshot.id} | evidence={len(snapshot.evidence_records)} | "
        f"trials={len(snapshot.trial_records)} | sha256={manifest.normalized_sha256}"
    )


@app.command("verify-clinical-history")
def verify_clinical_history() -> None:
    """Verify P1.3 source completeness, linkage, checksums, and cutoff isolation."""

    report = load_default_clinical_store().quality_report()
    failed = (
        report["chembl_release_count"] < 2
        or report["aact_release_count"] < 2
        or not report["all_release_queries_complete"]
        or report["evidence_to_historical_trial_coverage"] < 1.0
        or report["ctgov_identifier_validation_coverage"] < 1.0
        or report["chembl_drug_metadata_coverage"] < 1.0
        or report["first_posted_mismatch_count"] != 0
        or report["post_cutoff_leakage_count"] != 0
        or report["current_metadata_used_for_replay"]
        or not report["retrospective_replay_enabled"]
        or not report.get("raw_checksums_match", False)
        or not report.get("normalized_checksum_matches", False)
        or not report.get("deterministic_rebuild_matches", False)
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-claim-graph")
def build_claim_graph(
    clinical_snapshot_path: Annotated[
        Path | None,
        typer.Argument(help="P1.3 clinical-history snapshot; defaults to packaged fixture."),
    ] = None,
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the P2.1 graph and manifest.")
    ] = Path("outputs/p2-claims"),
) -> None:
    """Build the deterministic temporal claim graph without network access."""

    source = clinical_snapshot_path or default_clinical_snapshot_path()
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot, manifest = build_claim_graph_snapshot(
        source,
        output_dir / "claim_graph_snapshot.json",
        output_dir / "claim_graph_manifest.json",
    )
    typer.echo(
        f"BUILT {snapshot.id} | claims={len(snapshot.claims)} | "
        f"relations={len(snapshot.relations)} | families={len(snapshot.evidence_families)} | "
        f"sha256={manifest.normalized_sha256}"
    )


@app.command("verify-claim-graph")
def verify_claim_graph() -> None:
    """Verify P2.1 provenance, dependency correction, replay, and checksums."""

    report = load_default_claim_graph_store().quality_report()
    failed = (
        report["claim_observation_count"] == 0
        or report["evidence_family_count"] == 0
        or report["structured_field_provenance_coverage"] < 1.0
        or report["raw_source_lineage_coverage"] < 1.0
        or report["unsupported_efficacy_claim_count"] != 0
        or report["current_metadata_used_for_claims"]
        or report["post_cutoff_leakage_count"] != 0
        or report["dependency_correction_ratio"] >= 1.0
        or not report["retrospective_replay_enabled"]
        or not report["source_checksum_matches"]
        or not report["normalized_checksum_matches"]
        or not report["deterministic_rebuild_matches"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-literature")
def capture_literature(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P2.2 raw and normalized literature artifacts.")
    ] = Path("outputs/p2-literature"),
) -> None:
    """Capture the balanced Europe PMC corpus and build the P2.2 benchmark."""

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "europepmc_literature_raw.json"
    write_json(raw_path, capture_europepmc_corpus())
    snapshot, manifest = build_literature_benchmark(
        raw_path,
        output_dir / "literature_benchmark.json",
        output_dir / "literature_manifest.json",
    )
    typer.echo(
        f"CAPTURED Europe PMC {snapshot.source_api_version} | "
        f"documents={len(snapshot.documents)} | gold={len(snapshot.provisional_gold_claims)} | "
        f"extracted={len(snapshot.extracted_claims)} | sha256={manifest.normalized_sha256}"
    )


@app.command("build-literature")
def build_literature(
    raw_path: Annotated[Path, typer.Argument(help="Saved Europe PMC raw capture.")],
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the P2.2 benchmark and manifest.")
    ] = Path("outputs/p2-literature"),
) -> None:
    """Rebuild the literature benchmark and extractor evaluation offline."""

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot, manifest = build_literature_benchmark(
        raw_path,
        output_dir / "literature_benchmark.json",
        output_dir / "literature_manifest.json",
    )
    typer.echo(
        f"BUILT {snapshot.id} | documents={len(snapshot.documents)} | "
        f"gold={len(snapshot.provisional_gold_claims)} | extracted={len(snapshot.extracted_claims)} | "
        f"sha256={manifest.normalized_sha256}"
    )


@app.command("verify-literature")
def verify_literature() -> None:
    """Verify P2.2 versions, spans, review queue, relations, and extraction gate."""

    report = load_default_literature_store().quality_report()
    relation_counts = report["provisional_relation_counts"]
    failed = (
        report["document_version_count"] < 50
        or report["paragraph_count"] < 50
        or report["provisional_gold_claim_count"] < 150
        or report["double_review_fraction"] < 0.2
        or report["verbatim_span_coverage"] < 1.0
        or relation_counts["supports"] == 0
        or relation_counts["replicates"] == 0
        or report["negative_claim_count"] == 0
        or report["historical_backfill_allowed"]
        or report["p3_eligible_claim_count"] != 0
        or report["extraction_metrics"]["p3_gate_passed"]
        or not report["raw_checksum_matches"]
        or not report["normalized_checksum_matches"]
        or not report["deterministic_rebuild_matches"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-literature-reviews")
def build_literature_reviews(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the fixed P2.2 review batch and blinded packets.")
    ] = Path("outputs/p2-literature/review"),
) -> None:
    """Build two model-assisted pre-review passes and blank human-review packets."""

    batch = write_review_artifacts(output_dir)
    typer.echo(
        f"BUILT {batch.id} | tasks={batch.summary.task_count} | "
        f"model_passes={batch.summary.model_pass_count} | "
        f"disagreements={batch.summary.disagreement_count} | "
        "human_signed=0 | adjudicated=0"
    )


@app.command("verify-literature-reviews")
def verify_literature_reviews() -> None:
    """Verify fixed task coverage while preserving provisional-gold and P3 gates."""

    batch = load_default_review_batch()
    report = review_quality_report(batch)
    rebuilt = build_model_assisted_review_batch(load_default_literature_store())
    failed = (
        report["task_count"] != 30
        or report["model_pass_count"] != 60
        or not report["all_fixed_tasks_covered"]
        or not report["model_pre_review_complete"]
        or report["human_signed_review_count"] != 0
        or report["adjudicated_count"] != 0
        or report["final_gold_claim_count"] != 0
        or report["eligible_for_adjudication_count"] != 0
        or report["annotation_layer"] != "provisional_gold"
        or report["p3_gate_passed"]
        or rebuilt.model_dump(mode="json") != batch.model_dump(mode="json")
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("resolve-literature-review-comments")
def resolve_literature_review_comments(
    reviewer_a: Annotated[Path, typer.Argument(help="Unstructured reviewer A comments.")],
    reviewer_b: Annotated[Path, typer.Argument(help="Unstructured reviewer B comments.")],
    output_dir: Annotated[
        Path, typer.Option(help="Destination for proposed, non-adjudicated resolutions.")
    ] = Path("outputs/p2-literature/review"),
) -> None:
    """Combine reviewer comments with frozen model pre-review without promoting gold."""

    batch = write_comment_resolution_artifacts(reviewer_a, reviewer_b, output_dir)
    typer.echo(
        f"RESOLVED COMMENTS {batch.id} | accept={batch.proposed_accept_count} | "
        f"reject={batch.proposed_reject_count} | revise={batch.proposed_revise_count} | "
        "formal_human=0 | adjudicated=0 | final_gold=0"
    )


@app.command("verify-literature-review-comments")
def verify_literature_review_comments(
    reviewer_a: Annotated[
        Path, typer.Option(help="Reviewer A source used by the packaged resolution.")
    ] = Path("outputs/p2-literature/review/a_reviewer.md"),
    reviewer_b: Annotated[
        Path, typer.Option(help="Reviewer B source used by the packaged resolution.")
    ] = Path("outputs/p2-literature/review/b_reviewer.md"),
) -> None:
    """Verify comment provenance, deterministic resolution, and unchanged gold gates."""

    batch = load_default_comment_resolution()
    report = comment_resolution_quality_report(batch)
    rebuilt = build_comment_resolution(reviewer_a, reviewer_b)
    failed = (
        report["resolution_count"] != 30
        or not report["all_fixed_tasks_covered"]
        or not report["all_replacements_exist"]
        or report["formal_human_review_count"] != 0
        or report["adjudicated_count"] != 0
        or report["final_gold_claim_count"] != 0
        or report["p3_gate_passed"]
        or rebuilt.model_dump(mode="json") != batch.model_dump(mode="json")
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("prepare-literature-human-review-drafts")
def prepare_literature_human_review_drafts(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for unsigned structured A/B review drafts.")
    ] = Path("outputs/p2-literature/review"),
) -> None:
    """Prepare editable human-review JSON without pre-confirming or signing decisions."""

    reviewer_a, reviewer_b = write_human_review_drafts(output_dir)
    readiness = assess_human_review_readiness(reviewer_a, reviewer_b)
    typer.echo(
        f"PREPARED {len(reviewer_a.decisions) + len(reviewer_b.decisions)} decisions | "
        f"confirmed=0 | signed=0 | adjudication={readiness.status}"
    )


@app.command("prepare-literature-blind-review-bundles")
def prepare_literature_blind_review_bundles(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for isolated model-free reviewer A/B bundles.")
    ] = Path("outputs/p2-literature/review/offline"),
) -> None:
    """Build evidence-complete blind packets and editable JSON submissions."""

    reviewer_a, reviewer_b = write_blind_review_bundles(output_dir)
    typer.echo(
        f"PREPARED BLIND BUNDLES {output_dir} | "
        f"A={len(reviewer_a.decisions)} | B={len(reviewer_b.decisions)} | "
        "model_assistance=false | signed=0"
    )


@app.command("check-literature-blind-review")
def check_literature_blind_review(
    submission_path: Annotated[
        Path, typer.Argument(help="Blind reviewer submission JSON to validate.")
    ],
) -> None:
    """Validate evidence integrity and report completion without exposing model labels."""

    submission = load_blind_human_review_submission(submission_path)
    validate_blind_human_review_evidence(submission)
    confirmed = sum(item.reviewer_confirmed for item in submission.decisions)
    report = {
        "schema_version": submission.schema_version,
        "submission_id": submission.id,
        "reviewer_slot": submission.reviewer_slot,
        "task_count": len(submission.decisions),
        "confirmed_count": confirmed,
        "unconfirmed_task_ids": [
            item.task_id for item in submission.decisions if not item.reviewer_confirmed
        ],
        "human_signed_off": submission.human_signed_off,
        "status": submission.status,
        "model_assistance_exposed_before_signoff": (
            submission.model_assistance_exposed_before_signoff
        ),
        "ready_for_internal_finalization": (
            confirmed == len(submission.decisions)
            and submission.human_signed_off
            and submission.status == "signed"
        ),
    }
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if not report["ready_for_internal_finalization"]:
        raise typer.Exit(code=1)


@app.command("finalize-literature-blind-review")
def finalize_literature_blind_review(
    submission_path: Annotated[
        Path, typer.Argument(help="Signed blind reviewer submission JSON.")
    ],
    output_path: Annotated[
        Path, typer.Option(help="Internal enriched submission written after sign-off.")
    ],
) -> None:
    """Merge internal model/proposed fields only after a blind review is signed."""

    finalized = finalize_blind_human_review_submission(
        load_blind_human_review_submission(submission_path)
    )
    write_json(output_path, finalized.model_dump(mode="json"))
    typer.echo(
        f"FINALIZED {finalized.id} | slot={finalized.reviewer_slot} | "
        f"confirmed={len(finalized.decisions)} | blind=true | signed=true"
    )


@app.command("check-literature-human-review-readiness")
def check_literature_human_review_readiness(
    reviewer_a: Annotated[Path, typer.Argument(help="Structured reviewer A submission JSON.")],
    reviewer_b: Annotated[Path, typer.Argument(help="Structured reviewer B submission JSON.")],
) -> None:
    """Check whether two distinct signed 30/30 submissions may enter adjudication."""

    readiness = assess_human_review_readiness(
        load_human_review_submission(reviewer_a),
        load_human_review_submission(reviewer_b),
    )
    typer.echo(json.dumps(readiness.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
    if not readiness.eligible_for_adjudication:
        raise typer.Exit(code=1)


@app.command("build-literature-adjudication-queue")
def build_literature_adjudication_queue(
    reviewer_a: Annotated[Path, typer.Argument(help="Signed reviewer A submission JSON.")],
    reviewer_b: Annotated[Path, typer.Argument(help="Signed reviewer B submission JSON.")],
    output_path: Annotated[
        Path, typer.Option(help="Destination for the adjudication queue JSON.")
    ] = Path("outputs/p2-literature/review/adjudication_queue.json"),
) -> None:
    """Build an adjudication queue only after both independent human submissions pass."""

    try:
        queue = build_adjudication_queue(
            load_human_review_submission(reviewer_a),
            load_human_review_submission(reviewer_b),
        )
    except AdjudicationBlockedError as exc:
        typer.echo(f"BLOCKED: {exc}")
        raise typer.Exit(code=1) from exc
    write_json(output_path, queue.model_dump(mode="json"))
    typer.echo(
        f"READY {queue.id} | agreements={queue.agreement_count} | "
        f"disagreements={queue.disagreement_count} | adjudicated=0"
    )


@app.command("build-p3-ideation")
def build_p3_ideation(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the development-only P3 portfolio.")
    ] = Path("outputs/p3-ideation"),
) -> None:
    """Build the unranked seed-panel portfolio from model-silver evidence."""

    portfolio, manifest = write_ideation_artifacts(output_dir)
    typer.echo(
        f"BUILT {portfolio.id} | candidates={len(portfolio.candidates)} | "
        f"hypotheses={len(portfolio.hypotheses)} | silver_claims="
        f"{portfolio.silver_layer.selected_claim_count} | engineering_gate="
        f"{str(portfolio.quality.engineering_gate_passed).lower()} | "
        "scientific_gate=false"
    )
    typer.echo(f"sha256={manifest.normalized_sha256}")


@app.command("verify-p3-development")
def verify_p3_development() -> None:
    """Run the explicitly degraded engineering verification for model-silver P3."""

    report = load_default_ideation_store().quality_report()
    failed = (
        not report["engineering_gate_passed"]
        or report["fixed_seed_recall"] != 1.0
        or not report["all_routes_nonzero"]
        or report["mechanism_claim_binding_coverage"] != 1.0
        or report["post_cutoff_leakage_count"] != 0
        or report["selected_claim_count"] != 21
        or report["human_review_count"] != 0
        or report["scientific_validation_gate_passed"]
        or report["formal_p3_gate_passed"]
        or not report["deterministic_rebuild_matches"]
        or not report["normalized_checksum_matches"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p4-falsification")
def build_p4_falsification(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the development-only P4 falsification artifacts.")
    ] = Path("outputs/p4-falsification"),
) -> None:
    """Run the four fixed deterministic falsifiers over every P3 hypothesis."""

    snapshot, manifest = write_falsification_artifacts(output_dir)
    typer.echo(
        f"BUILT {snapshot.id} | hypotheses={len(snapshot.results)} | "
        f"critics={snapshot.quality.critic_assessment_count} | "
        f"engineering_gate={str(snapshot.quality.engineering_gate_passed).lower()} | "
        "scientific_gate=false"
    )
    typer.echo(f"sha256={manifest.normalized_sha256}")


@app.command("verify-p4-development")
def verify_p4_development() -> None:
    """Verify fixed taxonomy, references, conservative outputs, and reproducibility."""

    report = load_default_falsification_store().quality_report()
    failed = (
        not report["engineering_gate_passed"]
        or report["hypothesis_count"] != 5
        or report["critic_assessment_count"] != 20
        or report["taxonomy_coverage"] != 1.0
        or report["claim_reference_integrity"] != 1.0
        or report["fixed_rule_coverage"] != 1.0
        or report["proposer_trace_leakage_count"] != 0
        or report["human_review_count"] != 0
        or report["scientific_validation_gate_passed"]
        or report["formal_p4_gate_passed"]
        or not report["deterministic_rebuild_matches"]
        or not report["normalized_checksum_matches"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p4-revisions")
def build_p4_revisions(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for conservative P4.1 structured revisions.")
    ] = Path("outputs/p4-revision"),
) -> None:
    """Convert unresolved P4 critics into whitelisted constraints and explicit unknowns."""

    snapshot, manifest = write_revision_artifacts(output_dir)
    typer.echo(
        f"BUILT {snapshot.id} | candidates={len(snapshot.candidates)} | "
        f"patches={snapshot.quality.patch_count} | p5_development_eligible="
        f"{snapshot.quality.p5_development_eligible_count} | engineering_gate="
        f"{str(snapshot.quality.engineering_gate_passed).lower()} | scientific_gate=false"
    )
    typer.echo(f"sha256={manifest.normalized_sha256}")


@app.command("verify-p4-revision-development")
def verify_p4_revision_development() -> None:
    """Verify revision whitelist, no-imputation policy, lineage, and reproducibility."""

    report = load_default_revision_store().quality_report()
    failed = (
        not report["engineering_gate_passed"]
        or report["candidate_count"] != 5
        or report["patch_count"] == 0
        or report["source_binding_coverage"] != 1.0
        or report["unresolved_critic_patch_coverage"] != 1.0
        or report["whitelist_violation_count"] != 0
        or report["core_scientific_mutation_count"] != 0
        or report["scientific_value_imputation_count"] != 0
        or report["p5_development_eligible_count"] != 2
        or report["human_review_count"] != 0
        or report["scientific_validation_gate_passed"]
        or report["formal_p4_revision_gate_passed"]
        or not report["deterministic_rebuild_matches"]
        or not report["normalized_checksum_matches"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p5-decision-engine")
def build_p5_decision_engine(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5 development decision artifacts.")
    ] = Path("outputs/p5-decision"),
) -> None:
    """Build five ordinal heads with missingness propagation and no probability claims."""

    snapshot, manifest = write_decision_artifacts(output_dir)
    typer.echo(
        f"BUILT {snapshot.id} | candidates={len(snapshot.decisions)} | "
        f"heads={snapshot.quality.head_count} | observed="
        f"{snapshot.quality.observed_head_score_count} | fully_scorable="
        f"{snapshot.quality.fully_scorable_candidate_count} | calibrated=false | "
        "scientific_gate=false"
    )
    typer.echo(f"sha256={manifest.normalized_sha256}")


@app.command("verify-p5-development")
def verify_p5_development() -> None:
    """Verify heads, abstention, no-probability policy, lineage, and reproducibility."""

    report = load_default_decision_store().quality_report()
    failed = (
        not report["engineering_gate_passed"]
        or report["candidate_count"] != 5
        or report["head_count"] != 25
        or report["expected_head_count"] != 25
        or report["head_score_coverage"] != 0.6
        or report["upstream_blocked_candidate_count"] != 3
        or report["missing_head_abstention_candidate_count"] != 2
        or report["fully_scorable_candidate_count"] != 0
        or report["pareto_frontier_candidate_count"] != 0
        or report["probability_output_count"] != 0
        or report["outcome_label_count"] != 0
        or report["post_cutoff_leakage_count"] != 0
        or report["calibration"]["fitted"]
        or report["risk_coverage"]["available"]
        or report["calibration_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["deterministic_rebuild_matches"]
        or not report["normalized_checksum_matches"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-outcome-landmarks")
def capture_p5_outcome_landmarks(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the three raw AACT landmark pairs.")
    ] = Path("outputs/p5-outcomes/raw"),
) -> None:
    """Capture train, validation, and test monthly AACT landmark pairs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in LANDMARK_PAIRS:
        path = output_dir / f"aact_immune_outcomes_{split}_raw.json"
        capture = capture_landmark_pair(split)
        write_json(path, capture)
        typer.echo(
            f"CAPTURED {split} | baseline={capture['baseline_version']} | "
            f"outcome={capture['outcome_version']} | records={len(capture['baseline_rows'])} | "
            f"complete={str(capture['complete_for_query']).lower()}"
        )


@app.command("build-p5-outcomes")
def build_p5_outcomes(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for dataset, models, report, and manifest.")
    ] = Path("outputs/p5-outcomes"),
) -> None:
    """Build the temporal outcome dataset and validation-only calibrated baselines."""

    dataset, models, manifest = write_outcome_artifacts(output_dir)
    typer.echo(
        f"BUILT {dataset.id} | records={dataset.quality.record_count} | "
        f"right_censored={dataset.quality.right_censored_count} | "
        f"trained={models.quality.trained_head_count}/{models.quality.head_count} | "
        f"validation_only_calibration="
        f"{str(models.quality.calibration_protocol_gate_passed).lower()} | "
        "scientific_gate=false"
    )
    typer.echo(f"dataset_sha256={manifest.dataset_sha256}")
    typer.echo(f"model_sha256={manifest.model_sha256}")


@app.command("verify-p5-outcomes")
def verify_p5_outcomes() -> None:
    """Verify outcome semantics, temporal protocol, checksums, and no test leakage."""

    report = load_default_outcome_store().quality_report()
    dataset = report["dataset"]
    models = report["models"]
    failed = (
        not dataset["engineering_gate_passed"]
        or dataset["record_count"] != 1467
        or dataset["outcome_linkage_coverage"] != 1.0
        or dataset["completed_as_efficacy_success_count"] != 0
        or dataset["post_baseline_feature_leakage_count"] != 0
        or models["trained_head_count"] != 2
        or models["untrainable_head_count"] != 2
        or not models["engineering_gate_passed"]
        or not models["calibration_protocol_gate_passed"]
        or models["test_fit_leakage_count"] != 0
        or models["scientific_validation_gate_passed"]
        or models["formal_p5_gate_passed"]
        or not report["dataset_deterministic_rebuild_matches"]
        or not report["model_deterministic_rebuild_matches"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-broad-outcome-landmarks")
def capture_p5_broad_outcome_landmarks(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for projected all-indication AACT captures.")
    ] = Path("outputs/p5-2-broad-outcomes/raw"),
) -> None:
    """Capture projected all-indication Phase II/III landmark pairs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for split in LANDMARK_PAIRS:
        capture = capture_broad_landmark_pair(split)
        path = output_dir / f"aact_broad_outcomes_{split}_raw.json.gz"
        write_gzip_capture(str(path), capture)
        typer.echo(
            f"CAPTURED {split} | records={len(capture['baseline_rows'])} | "
            f"linked={len(capture['outcome_rows'])} | "
            f"missing={len(capture['missing_outcome_nct_ids'])}"
        )


@app.command("build-p5-broad-outcomes")
def build_p5_broad_outcomes(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.2 dataset, predictions, and reports.")
    ] = Path("outputs/p5-2-broad-outcomes"),
) -> None:
    """Build broad outcome baselines and novel-NCT sensitivity artifacts."""

    snapshot, manifest = write_broad_outcome_artifacts(output_dir)
    typer.echo(
        f"BUILT {snapshot.id} | records={snapshot.quality.record_count} | "
        f"unique_nct={snapshot.quality.unique_nct_count} | "
        f"trained={snapshot.quality.trained_head_count}/4 | "
        f"novel_test={snapshot.quality.novel_nct_test_count} | scientific_gate=false"
    )
    typer.echo(f"dataset_sha256={manifest.normalized_dataset_sha256}")
    typer.echo(f"prediction_sha256={manifest.prediction_sha256}")


@app.command("verify-p5-broad-outcomes")
def verify_p5_broad_outcomes() -> None:
    """Verify broad cohort checksums, leakage gates, and honest untrainable heads."""

    report = load_default_broad_outcome_store().quality_report()
    failed = (
        report["record_count"] != 71947
        or report["trained_head_count"] != 3
        or report["untrainable_head_count"] != 1
        or report["novel_nct_test_count"] != 6227
        or report["missing_outcome_snapshot_count"] != 10
        or report["forbidden_feature_count"] != 0
        or report["post_baseline_feature_leakage_count"] != 0
        or report["test_fit_leakage_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["raw_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-interventions")
def capture_p5_interventions(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for three versioned AACT intervention captures.")
    ] = Path("outputs/p5-4-mapping-audit/raw"),
) -> None:
    """Capture AACT intervention names for each frozen broad-outcome cohort."""

    output_dir.mkdir(parents=True, exist_ok=True)
    store = load_default_broad_outcome_store()
    by_split = {split: set() for split in LANDMARK_PAIRS}
    for row in store.sample_records(store.manifest.record_count):
        by_split[row["split"]].add(row["nct_id"])
    for split in LANDMARK_PAIRS:
        capture = capture_aact_interventions(split, by_split[split])
        path = output_dir / f"aact_broad_interventions_{split}_raw.json.gz"
        write_identity_capture(path, capture)
        typer.echo(
            f"CAPTURED {split} | cohort_nct={capture['cohort_nct_count']} | "
            f"with_intervention={capture['nct_with_intervention_count']} | "
            f"complete={str(capture['complete_for_query']).lower()}"
        )


@app.command("capture-p5-identity-drug-dictionary")
def capture_p5_identity_drug_dictionary(
    output_path: Annotated[
        Path, typer.Option(help="Destination for the scoped Open Targets drug dictionary.")
    ] = Path("outputs/p5-3-identity/opentargets_25_09_drug_dictionary_raw.json.gz"),
    mapping_path: Annotated[
        Path | None,
        typer.Option(help="Saved 25.09 trial-mapping capture; defaults to the resolved fixture."),
    ] = None,
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent Parquet downloads.")
    ] = 4,
) -> None:
    """Capture the version-matched drug subset required by the P5.3 ledger."""

    source = mapping_path or default_trial_mapping_raw_path()
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        mapping = json.load(stream)
    drug_ids = sorted({row["drugId"] for row in mapping["rows"] if row.get("drugId")})
    capture = capture_opentargets_drug_dictionary_release(
        "25.09", drug_ids, workers=workers
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_gzip_capture(str(output_path), capture)
    typer.echo(
        f"CAPTURED Open Targets 25.09 scoped drug dictionary | "
        f"requested={len(drug_ids)} | matched={capture['matched_drug_count']} | "
        f"missing={len(capture['missing_drug_ids'])} | "
        f"complete={str(capture['complete_for_query']).lower()}"
    )


@app.command("build-p5-identity-ledger")
def build_p5_identity_ledger(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.3 mappings and provenance ledger.")
    ] = Path("outputs/p5-3-identity"),
) -> None:
    """Build auditable source-asserted mappings and enriched outcome provenance."""

    snapshot, manifest = write_identity_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | mappings={manifest.mapping_count} | "
        f"mapped_nct={quality.mapped_unique_nct_count}/{quality.broad_unique_nct_count} | "
        f"provenance={manifest.provenance_count} | unresolved={manifest.unresolved_count} | "
        "fuzzy=0 | model_feature_use=0 | scientific_gate=false"
    )
    typer.echo(f"mapping_sha256={manifest.mapping_sha256}")
    typer.echo(f"provenance_sha256={manifest.provenance_sha256}")


@app.command("verify-p5-identity-ledger")
def verify_p5_identity_ledger() -> None:
    """Verify source lineage, mapping policy, coverage, checksums, and leakage gates."""

    report = load_default_identity_store().quality_report()
    failed = (
        report["source_evidence_row_count"] != 97069
        or report["unique_trial_drug_target_mapping_count"] != 86154
        or report["mapped_unique_nct_count"] != 14392
        or report["unmapped_unique_nct_count"] != 21694
        or report["outcome_provenance_record_count"] != 71947
        or report["explicit_cause_event_mapping_coverage"]["mapped_count"] != 60
        or report["fuzzy_auto_mapping_count"] != 0
        or report["current_identity_used_as_temporal_model_feature_count"] != 0
        or report["classification_trace_coverage"] != 1.0
        or not report["source_complete_for_query"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p5-mapping-audit")
def build_p5_mapping_audit(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.4 missingness and triage artifacts.")
    ] = Path("outputs/p5-4-mapping-audit"),
) -> None:
    """Build descriptive coverage strata and a no-inference unresolved queue."""

    snapshot, manifest = write_mapping_audit_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | triage={manifest.triage_record_count} | "
        f"unresolved={quality.unresolved_unique_nct_count} | "
        f"captures={quality.intervention_capture_complete_count}/"
        f"{quality.intervention_capture_count} | disparities="
        f"{quality.material_coverage_disparity_stratum_count} | "
        "auto_mapping=0 | scientific_gate=false"
    )
    typer.echo(f"triage_sha256={manifest.triage_sha256}")


@app.command("verify-p5-mapping-audit")
def verify_p5_mapping_audit() -> None:
    """Verify capture completeness, triage taxonomy, checksums, and no inference."""

    report = load_default_mapping_audit_store().quality_report()
    failed = (
        report["outcome_record_count"] != 71947
        or report["unique_nct_count"] != 36086
        or report["unresolved_unique_nct_count"] != 21694
        or report["intervention_capture_complete_count"] != 3
        or report["nct_with_intervention_coverage"] != 1.0
        or sum(report["unresolved_reason_counts"].values()) != 21694
        or report["automatic_mapping_count"] != 0
        or report["fuzzy_mapping_count"] != 0
        or report["mapping_candidate_used_as_evidence_count"] != 0
        or report["current_identity_used_as_temporal_model_feature_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-drug-dictionary")
def capture_p5_drug_dictionary(
    output_path: Annotated[
        Path, typer.Option(help="Destination for the compressed 25.09 dictionary capture.")
    ] = Path("outputs/p5-5-drug-identity/opentargets_25_09_full_drug_dictionary_raw.json.gz"),
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent Parquet downloads.")
    ] = 4,
) -> None:
    """Capture the complete versioned Open Targets 25.09 molecule dictionary."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = capture_opentargets_full_drug_dictionary_release(
        "25.09", workers=workers
    )
    write_gzip_capture(str(output_path), capture)
    typer.echo(
        f"CAPTURED Open Targets {capture['release_version']} "
        f"{capture['dataset']} | rows={capture['dataset_row_count']} | "
        f"files={capture['archive_file_count']} | complete="
        f"{str(capture['complete_for_query']).lower()}"
    )


@app.command("build-p5-drug-identity")
def build_p5_drug_identity(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.5 drug identity artifacts.")
    ] = Path("outputs/p5-5-drug-identity"),
    dictionary_path: Annotated[
        Path | None,
        typer.Option(help="Saved full drug dictionary; defaults to packaged 25.09 capture."),
    ] = None,
) -> None:
    """Build exact-name molecule-family candidates without target inference."""

    snapshot, manifest = write_drug_identity_artifacts(output_dir, dictionary_path)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | dictionary={quality.full_dictionary_row_count} | "
        f"unresolved={manifest.resolution_record_count} | "
        f"exact_name={quality.exact_name_matched_trial_count} | "
        f"ambiguous={quality.ambiguous_name_trial_count} | "
        f"target_gaps={quality.target_assertion_gap_count} | "
        "auto_target_mapping=0 | scientific_gate=false"
    )
    typer.echo(f"resolution_sha256={manifest.resolution_sha256}")


@app.command("verify-p5-drug-identity")
def verify_p5_drug_identity() -> None:
    """Verify dictionary completeness, family resolution, checksums, and boundaries."""

    report = load_default_drug_identity_store().quality_report()
    expected_statuses = {
        "ambiguous_exact_name_to_multiple_families": 540,
        "complete_exact_family_resolution": 2484,
        "no_exact_full_dictionary_match": 10906,
        "non_therapeutic_interventions_only": 2420,
        "partial_exact_family_resolution": 5344,
    }
    failed = (
        report["full_dictionary_row_count"] != 18119
        or report["normalized_dictionary_name_count"] != 68443
        or report["molecule_family_count"] != 16522
        or report["hierarchy_cycle_count"] != 0
        or report["unresolved_trial_count"] != 21694
        or report["resolution_status_counts"] != expected_statuses
        or report["exact_name_matched_trial_count"] != 8368
        or report["single_family_nonambiguous_trial_count"] != 5319
        or report["multi_family_nonambiguous_trial_count"] != 2509
        or report["ambiguous_name_trial_count"] != 540
        or report["target_assertion_gap_count"] != 8368
        or report["automatic_trial_drug_mapping_count"] != 0
        or report["automatic_trial_target_mapping_count"] != 0
        or report["fuzzy_matching_count"] != 0
        or report["identity_candidate_used_as_target_evidence_count"] != 0
        or report["current_identity_used_as_temporal_model_feature_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-assertion-history")
def capture_p5_assertion_history(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for versioned ChEMBL evidence captures.")
    ] = Path("outputs/p5-6-assertion-history"),
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent Parquet downloads.")
    ] = 8,
) -> None:
    """Capture source-asserted trial-drug-target rows from both frozen releases."""

    output_dir.mkdir(parents=True, exist_ok=True)
    broad_store = load_default_broad_outcome_store()
    nct_ids = {
        row["nct_id"]
        for row in broad_store.sample_records(broad_store.manifest.record_count)
    }
    for release in ("25.03", "25.09"):
        capture = capture_chembl_trial_mapping_release(
            release, nct_ids, workers=workers
        )
        path = output_dir / (
            f"chembl_{release.replace('.', '_')}_broad_trial_mapping_raw.json.gz"
        )
        write_gzip_capture(str(path), capture)
        typer.echo(
            f"CAPTURED ChEMBL {release} | rows={capture['matched_row_count']} | "
            f"mapped_nct={capture['mapped_nct_count']} | "
            f"complete={str(capture['complete_for_query']).lower()}"
        )


@app.command("build-p5-assertion-history")
def build_p5_assertion_history(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.6 assertion-history artifacts.")
    ] = Path("outputs/p5-6-assertion-history"),
) -> None:
    """Build release-aware source evidence and assertion membership ledgers."""

    snapshot, manifest = write_assertion_history_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | evidence={manifest.evidence_history_record_count} | "
        f"assertions={manifest.assertion_record_count} | "
        f"removed={quality.removed_assertion_count} | "
        f"recovered_nct={quality.newly_recovered_nct_count} | "
        f"p5_5_recovery={quality.p5_5_candidate_target_assertion_recovery_count}/"
        f"{quality.p5_5_exact_identity_candidate_nct_count} | "
        "name_inference=0 | scientific_gate=false"
    )
    typer.echo(f"assertion_sha256={manifest.assertion_sha256}")


@app.command("verify-p5-assertion-history")
def verify_p5_assertion_history() -> None:
    """Verify release diffs, field provenance, checksums, and zero inference."""

    report = load_default_assertion_history_store().quality_report()
    failed = (
        report["release_count"] != 2
        or report["release_evidence_row_counts"]
        != {"25.03": 97074, "25.09": 97069}
        or report["release_assertion_counts"]
        != {"25.03": 86157, "25.09": 86154}
        or report["release_mapped_nct_counts"]
        != {"25.03": 14392, "25.09": 14392}
        or report["union_evidence_row_count"] != 97074
        or report["removed_evidence_row_count"] != 5
        or report["content_changed_evidence_row_count"] != 0
        or report["union_assertion_count"] != 86157
        or report["removed_assertion_count"] != 3
        or report["newly_recovered_nct_count"] != 0
        or report["p5_5_exact_identity_candidate_nct_count"] != 8368
        or report["p5_5_candidate_target_assertion_recovery_count"] != 0
        or report["invalid_source_identity_row_count"] != 0
        or report["source_field_provenance_coverage"] != 1.0
        or report["name_inferred_assertion_count"] != 0
        or report["fuzzy_assertion_count"] != 0
        or report["source_assertion_used_as_temporal_model_feature_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("capture-p5-independent-assertions")
def capture_p5_independent_assertions(
    output_path: Annotated[
        Path, typer.Option(help="Destination for the compressed DrugCentral capture.")
    ] = Path("outputs/p5-7-independent-assertions/drugcentral_2027_independent_assertions_raw.json.gz"),
    workers: Annotated[
        int, typer.Option(min=1, max=16, help="Concurrent identity-crosswalk downloads.")
    ] = 8,
) -> None:
    """Capture DrugCentral 2027 and exact non-name identity crosswalks."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = capture_drugcentral_independent_source(workers=workers)
    write_gzip_capture(str(output_path), capture)
    typer.echo(
        f"CAPTURED DrugCentral {capture['independent_source']['release']} | "
        f"interactions={capture['interaction_row_count']} | "
        f"structures={capture['structure_row_count']} | "
        f"complete={str(capture['complete_for_query']).lower()}"
    )


@app.command("build-p5-independent-assertions")
def build_p5_independent_assertions(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.7 corroboration artifacts.")
    ] = Path("outputs/p5-7-independent-assertions"),
    raw_path: Annotated[
        Path | None,
        typer.Option(help="Saved DrugCentral capture; defaults to packaged fixture."),
    ] = None,
) -> None:
    """Build cross-source versus single-source drug-target classifications."""

    snapshot, manifest = write_independent_assertion_artifacts(output_dir, raw_path)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | independent_pairs="
        f"{manifest.independent_pair_record_count} | "
        f"cross_source={quality.cross_source_supported_assertion_count} | "
        f"single_source={quality.single_source_assertion_count} | "
        f"cross_nct={quality.cross_source_supported_nct_count} | "
        "new_mapping=0 | name_matching=0 | scientific_gate=false"
    )
    typer.echo(f"corroboration_sha256={manifest.corroboration_sha256}")


@app.command("verify-p5-independent-assertions")
def verify_p5_independent_assertions() -> None:
    """Verify source admission, exact crosswalks, support strata, and boundaries."""

    report = load_default_independent_assertion_store().quality_report()
    failed = (
        not report["source_admission_passed"]
        or report["raw_interaction_row_count"] != 22364
        or report["human_interaction_row_count"] != 16926
        or report["independently_sourced_human_row_count"] != 7699
        or report["exact_crosswalk_evidence_row_count"] != 6469
        or report["independent_drug_target_pair_count"] != 6455
        or report["current_source_assertion_count"] != 86154
        or report["current_source_pair_count"] != 4469
        or report["cross_source_supported_assertion_count"] != 16450
        or report["single_source_assertion_count"] != 69704
        or report["cross_source_supported_pair_count"] != 813
        or report["single_source_pair_count"] != 3656
        or report["cross_source_supported_nct_count"] != 7968
        or report["all_assertions_cross_source_nct_count"] != 2582
        or report["mixed_support_nct_count"] != 5386
        or report["single_source_only_nct_count"] != 6424
        or report["p5_5_candidate_promoted_to_trial_target_count"] != 0
        or report["newly_mapped_nct_count"] != 0
        or report["remaining_unresolved_nct_count"] != 21694
        or report["name_matching_used_count"] != 0
        or report["ambiguous_identity_admitted_count"] != 0
        or report["independent_source_used_as_temporal_model_feature_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p5-support-audit")
def build_p5_support_audit(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.8 support-stratified provenance.")
    ] = Path("outputs/p5-8-support-audit"),
) -> None:
    """Join frozen support strata to outcomes without comparing outcome rates."""

    snapshot, manifest = write_support_audit_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | outcomes={manifest.enriched_outcome_record_count} | "
        f"nct={quality.unique_nct_count} | explicit_events="
        f"{manifest.explicit_event_record_count} | mapping_changes=0 | "
        "causal_comparisons=0 | model_feature_use=0 | scientific_gate=false"
    )
    typer.echo(f"outcome_sha256={manifest.enriched_outcome_sha256}")


@app.command("verify-p5-support-audit")
def verify_p5_support_audit() -> None:
    """Verify descriptive support strata, lineage, checksums, and hard boundaries."""

    report = load_default_support_audit_store().quality_report()
    failed = (
        report["outcome_provenance_record_count"] != 71947
        or report["unique_nct_count"] != 36086
        or report["mapped_nct_count"] != 14392
        or report["unmapped_nct_count"] != 21694
        or report["nct_counts_by_support_stratum"]
        != {
            "unmapped_no_source_assertion": 21694,
            "mapped_all_cross_source_pairs": 2582,
            "mapped_mixed_pair_support": 5386,
            "mapped_opentargets_chembl_only": 6424,
        }
        or report["explicit_event_record_count"] != 167
        or report["source_assertion_record_count"] != 86154
        or report["support_stratum_coverage"] != 1.0
        or report["mapping_status_change_count"] != 0
        or report["outcome_interpretation_change_count"] != 0
        or report["causal_comparison_count"] != 0
        or report["target_outcome_attribution_count"] != 0
        or report["support_stratum_used_as_model_feature_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p5-selection-audit")
def build_p5_selection_audit(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P5.9 validation-readiness audit.")
    ] = Path("outputs/p5-9-selection-audit"),
) -> None:
    """Diagnose mapping selection without outcomes, weighting, or target estimates."""

    snapshot, manifest = write_selection_audit_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | nct={manifest.cohort_record_count} | "
        f"features={quality.baseline_feature_count} | selection_auc="
        f"{quality.mapping_selection_roc_auc:.4f} | max_abs_smd="
        f"{quality.mapped_vs_unmapped_max_abs_smd:.4f} | "
        "outcome_models=0 | target_estimates=0 | validation_ready=false"
    )
    typer.echo(f"cohort_sha256={manifest.cohort_sha256}")


@app.command("verify-p5-selection-audit")
def verify_p5_selection_audit() -> None:
    """Verify non-random selection diagnostics and the target-validation no-go gate."""

    report = load_default_selection_audit_store().quality_report()
    failed = (
        report["unique_nct_count"] != 36086
        or report["input_landmark_record_count"] != 71947
        or report["repeated_landmark_record_count_collapsed"] != 35861
        or report["baseline_feature_count"] != 32
        or report["balance_contrast_count"] != 5
        or report["balance_diagnostic_record_count"] != 160
        or report["mapped_vs_unmapped_max_abs_smd"] < 0.6
        or report["mapped_vs_unmapped_material_imbalance_count"] != 13
        or not 0.68 < report["mapping_selection_roc_auc"] < 0.70
        or report["unmapped_group_common_support_fraction"] >= 0.95
        or report["outcome_field_used_as_selection_feature_count"] != 0
        or report["identifier_used_as_selection_feature_count"] != 0
        or report["post_baseline_feature_used_count"] != 0
        or report["outcome_comparison_count"] != 0
        or report["causal_adjustment_count"] != 0
        or report["target_outcome_estimate_count"] != 0
        or report["fitted_outcome_model_count"] != 0
        or report["selection_bias_gate_passed"]
        or report["target_validation_ready"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p5_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-evaluation")
def build_p6_evaluation(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.0 claim-audit and replay artifacts.")
    ] = Path("outputs/p6-0-evaluation"),
) -> None:
    """Build the frozen paper-claim registry and P3→P5 decision replay."""

    snapshot, manifest = write_evaluation_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | claims={manifest.claim_registry_count} | "
        f"scientifically_supported={quality.scientifically_supported_claim_count} | "
        f"manifests={manifest.artifact_inventory_count} | "
        f"replay={manifest.decision_replay_count} | future_reveals=0 | "
        "formal_gate=false"
    )
    typer.echo(f"claim_registry_sha256={manifest.claim_registry_sha256}")


@app.command("verify-p6-evaluation")
def verify_p6_evaluation() -> None:
    """Verify claim status, artifact lineage, replay boundaries, and checksums."""

    report = load_default_evaluation_store().quality_report()
    failed = (
        report["paper_claim_count"] != 6
        or report["headline_claim_count"] != 5
        or report["scientifically_supported_claim_count"] != 0
        or report["engineering_evidence_only_claim_count"] != 2
        or report["blocked_claim_count"] != 3
        or report["deferred_claim_count"] != 1
        or report["artifact_inventory_count"] != 16
        or report["artifact_checksum_coverage"] != 1.0
        or report["replay_hypothesis_count"] != 5
        or report["replay_stage_count"] != 4
        or report["future_outcome_reveal_count"] != 0
        or report["unsupported_positive_claim_count"] != 0
        or report["target_level_metric_count"] != 0
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-robustness")
def build_p6_robustness(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.1 graph perturbation artifacts.")
    ] = Path("outputs/p6-1-robustness"),
) -> None:
    """Run fixed claim drop, polarity, context, and dependency perturbations."""

    snapshot, manifest = write_robustness_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | scenarios={manifest.scenario_record_count} | "
        f"targets={manifest.target_propagation_record_count} | p3_bound="
        f"{quality.p3_bound_literature_claim_count} | max_p3_impact="
        f"{quality.maximum_p3_bound_claim_impact_count} | outcomes=0 | refits=0 | "
        "c1=false | c4=false"
    )
    typer.echo(f"scenario_sha256={manifest.scenario_sha256}")


@app.command("verify-p6-robustness")
def verify_p6_robustness() -> None:
    """Verify nested perturbations, structural metrics, and locked claim gates."""

    report = load_default_robustness_store().quality_report()
    failed = (
        report["perturbation_kind_count"] != 4
        or report["severity_level_count"] != 4
        or report["scenario_count"] != 16
        or report["ledger_record_count"] != 16
        or report["target_propagation_record_count"] != 56
        or report["provisional_literature_claim_count"] != 150
        or report["provisional_literature_relation_count"] != 21
        or report["structured_claim_count"] != 258
        or report["structured_relation_count"] != 387
        or report["structured_dependency_edge_count"] != 86
        or report["p3_bound_literature_claim_count"] != 21
        or not report["nested_selection_invariant_passed"]
        or report["maximum_p3_bound_claim_impact_count"] != 6
        or report["maximum_p3_hypothesis_signature_changed_count"] != 5
        or not 0.93 < report["minimum_graph_signature_similarity"] < 0.94
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or report["c2_scientific_claim_unlocked"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-cohort-stress")
def build_p6_cohort_stress(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.2 duplicate-cohort stress artifacts.")
    ] = Path("outputs/p6-2-cohort-stress"),
) -> None:
    """Inject repeated evidence families and compare dependency-aware counts."""

    snapshot, manifest = write_cohort_stress_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | scenarios={manifest.scenario_record_count} | "
        f"baseline={quality.baseline_claim_record_count}/"
        f"{quality.baseline_independent_family_count} | max_naive_inflation="
        f"{quality.maximum_naive_claim_inflation_fraction:.4f} | "
        "corrected_inflation=0 | outcomes=0 | c1=false | c4=false"
    )
    typer.echo(f"scenario_sha256={manifest.scenario_sha256}")


@app.command("verify-p6-cohort-stress")
def verify_p6_cohort_stress() -> None:
    """Verify duplicate-cohort count invariance and locked scientific gates."""

    report = load_default_cohort_stress_store().quality_report()
    failed = (
        report["severity_level_count"] != 4
        or report["scenario_count"] != 4
        or report["ledger_record_count"] != 4
        or report["target_propagation_record_count"] != 8
        or report["baseline_claim_record_count"] != 129
        or report["baseline_independent_family_count"] != 43
        or report["baseline_target_count"] != 2
        or not report["nested_selection_invariant_passed"]
        or not report["active_family_bundle_size_uniform"]
        or report["active_family_bundle_size"] != 3
        or not 0.20 < report["maximum_naive_claim_inflation_fraction"] < 0.21
        or report["maximum_dependency_corrected_inflation_fraction"] != 0
        or not report["dependency_correction_invariant_passed"]
        or not report["lineage_stripped_negative_control_passed"]
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or report["c2_scientific_claim_unlocked"]
        or report["c3_scientific_claim_unlocked"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-paired-control")
def build_p6_paired_control(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.3 paired pipeline-control artifacts.")
    ] = Path("outputs/p6-3-paired-control"),
) -> None:
    """Build the fixed proposer-only versus falsify-revise paired control."""

    snapshot, manifest = write_paired_control_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | pairs={manifest.pair_record_count} | "
        f"critic_cells={manifest.critic_audit_record_count} | unqualified_proxy="
        f"{quality.proposer_only_unqualified_proxy_count}->"
        f"{quality.full_path_unqualified_proxy_count} | counter_retained="
        f"{quality.revised_counterevidence_retained_count}/"
        f"{quality.source_counterevidence_binding_count} | false_rejection_rate=NA"
    )
    typer.echo(f"pair_sha256={manifest.pair_sha256}")


@app.command("verify-p6-paired-control")
def verify_p6_paired_control() -> None:
    """Verify paired proxy reduction, retention, and false-rejection boundaries."""

    report = load_default_paired_control_store().quality_report()
    failed = (
        report["paired_hypothesis_count"] != 5
        or report["critic_cell_count"] != 20
        or report["false_rejection_queue_count"] != 3
        or report["proposer_only_unqualified_proxy_count"] != 16
        or report["full_path_unqualified_proxy_count"] != 0
        or report["unsupported_proxy_reduction_count"] != 16
        or report["unsupported_proxy_reduction_fraction"] != 1
        or report["source_counterevidence_binding_count"] != 4
        or report["critic_counterevidence_retained_count"] != 4
        or report["revised_counterevidence_retained_count"] != 4
        or report["counterevidence_retention_fraction"] != 1
        or report["surviving_critic_count"] != 4
        or report["surviving_critic_patch_leak_count"] != 0
        or report["abstain_critic_count"] != 8
        or report["abstain_to_block_propagation_count"] != 3
        or report["false_rejection_rate_computed"]
        or report["human_adjudicated_false_rejection_count"] != 0
        or report["retired_by_rejection_count"] != 0
        or report["core_scientific_mutation_count"] != 0
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or not report["c3_paired_engineering_control_completed"]
        or report["c3_scientific_claim_unlocked"]
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-counterevidence-ablation")
def build_p6_counterevidence_ablation(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.4 counterevidence-ablation artifacts.")
    ] = Path("outputs/p6-4-counterevidence-ablation"),
) -> None:
    """Mask explicit counter roles and compare fixed critic decisions."""

    snapshot, manifest = write_counterevidence_ablation_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | pairs={manifest.hypothesis_comparison_record_count} | "
        f"cells={manifest.cell_comparison_record_count} | masked="
        f"{quality.mask_ledger_record_count} | cell_changes="
        f"{quality.cell_verdict_changed_count} | combined_changes="
        f"{quality.combined_verdict_changed_count} | decision_value_supported=false"
    )
    typer.echo(f"hypothesis_sha256={manifest.hypothesis_comparison_sha256}")


@app.command("verify-p6-counterevidence-ablation")
def verify_p6_counterevidence_ablation() -> None:
    """Verify local sensitivity and the frozen decision-level negative result."""

    report = load_default_counterevidence_ablation_store().quality_report()
    failed = (
        report["paired_hypothesis_count"] != 5
        or report["critic_cell_count"] != 20
        or report["mask_ledger_record_count"] != 4
        or report["hypotheses_with_masked_counterevidence_count"] != 4
        or report["removed_counterevidence_reference_count"] != 8
        or report["cell_verdict_changed_count"] != 1
        or report["cell_rule_changed_count"] != 2
        or report["cell_evidence_reference_changed_count"] != 7
        or report["combined_verdict_changed_count"] != 0
        or report["binding_critic_set_changed_count"] != 0
        or report["projected_revision_fields_changed_count"] != 1
        or report["full_non_survive_critic_count"] != 16
        or report["masked_non_survive_critic_count"] != 15
        or report["qualification_proxy_lost_count"] != 1
        or report["full_blocked_hypothesis_count"] != 3
        or report["masked_blocked_hypothesis_count"] != 3
        or report["block_decision_changed_count"] != 0
        or not report["counterevidence_local_sensitivity_detected"]
        or report["counterevidence_decision_level_sensitivity_detected"]
        or report["c3_counterevidence_decision_value_supported"]
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-claim-synthesis")
def build_p6_claim_synthesis(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.5 frozen claim-disposition artifacts.")
    ] = Path("outputs/p6-5-claim-synthesis"),
) -> None:
    """Synthesize P6.0-P6.4 into a checksum-bound paper claim table."""

    snapshot, manifest = write_claim_synthesis_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | claims={manifest.claim_disposition_record_count} | "
        f"experiments={manifest.experiment_disposition_record_count} | controls="
        f"{quality.completed_engineering_control_count} | status_changes="
        f"{quality.claim_status_changed_count} | scientific_claims="
        f"{quality.scientifically_supported_claim_count} | formal_gate=false"
    )
    typer.echo(f"paper_table_sha256={manifest.paper_table_sha256}")


@app.command("verify-p6-claim-synthesis")
def verify_p6_claim_synthesis() -> None:
    """Verify frozen claim dispositions and absence of gate promotion."""

    report = load_default_claim_synthesis_store().quality_report()
    failed = (
        report["claim_count"] != 6
        or report["experiment_count"] != 5
        or report["source_manifest_count"] != 5
        or report["source_manifest_checksum_coverage"] != 1
        or report["scientifically_supported_claim_count"] != 0
        or report["engineering_evidence_only_claim_count"] != 2
        or report["blocked_claim_count"] != 3
        or report["deferred_claim_count"] != 1
        or report["claim_status_changed_count"] != 0
        or report["scientifically_decisive_metric_count"] != 0
        or report["completed_engineering_control_count"] != 4
        or report["decision_level_negative_result_count"] != 1
        or report["future_outcome_reveal_count"] != 0
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-p6-paper-bundle")
def build_p6_paper_bundle(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for P6.6 reproducible paper artifacts.")
    ] = Path("outputs/p6-6-paper-bundle"),
) -> None:
    """Build the methods/artifact and negative-results paper bundle."""

    snapshot, manifest = write_paper_bundle_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | manifests={manifest.source_manifest_inventory_record_count} | "
        f"paper_files={manifest.paper_file_inventory_record_count} | artifact_ready="
        f"{str(quality.artifact_release_ready).lower()} | scientific_ready=false | "
        f"supported_claims=0 | negative_preserved="
        f"{str(quality.negative_result_preserved).lower()}"
    )
    typer.echo(f"paper_inventory_sha256={manifest.paper_file_inventory_sha256}")


@app.command("verify-p6-paper-bundle")
def verify_p6_paper_bundle() -> None:
    """Verify bundle checksums and the separation of artifact/scientific gates."""

    report = load_default_paper_bundle_store().quality_report()
    failed = (
        report["source_manifest_count"] != 22
        or report["source_manifest_checksum_coverage"] != 1
        or report["paper_file_count"] != 9
        or report["readiness_gate_count"] != 6
        or report["passed_artifact_gate_count"] != 3
        or report["blocked_scientific_gate_count"] != 3
        or not report["artifact_release_ready"]
        or report["scientific_submission_ready"]
        or report["scientifically_supported_claim_count"] != 0
        or report["claim_status_changed_count"] != 0
        or not report["negative_result_preserved"]
        or report["future_outcome_reveal_count"] != 0
        or report["outcome_field_used_count"] != 0
        or report["model_refit_count"] != 0
        or report["clinical_metric_count"] != 0
        or report["c1_status_changed"]
        or report["c4_status_changed"]
        or not report["engineering_gate_passed"]
        or report["scientific_validation_gate_passed"]
        or report["formal_p6_gate_passed"]
        or not report["artifact_checksums_match"]
        or not report["source_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-release-audit")
def build_release_audit(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the R1 release-candidate audit.")
    ] = Path("outputs/r1-release-audit"),
) -> None:
    """Audit release surfaces and payload without publishing anything."""

    snapshot, manifest = write_release_audit_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | gates={manifest.gate_audit_record_count} | "
        f"passed={quality.passed_gate_count} | blocked={quality.blocked_gate_count} | "
        f"payload_mib={quality.package_payload_byte_count / 1024 / 1024:.1f} | "
        "release_ready=false | upload_authorized=false"
    )
    typer.echo(f"gate_audit_sha256={manifest.gate_audit_sha256}")


@app.command("verify-release-audit")
def verify_release_audit() -> None:
    """Verify the frozen R1 blockers and no-upload boundary."""

    report = load_default_release_audit_store().quality_report()
    failed = (
        report["release_gate_count"] != 11
        or report["passed_gate_count"] != 6
        or report["blocked_gate_count"] != 5
        or report["release_candidate_ready"]
        or not report["safe_automated_hardening_complete"]
        or report["legal_metadata_ready"]
        or report["citation_metadata_ready"]
        or report["data_redistribution_ready"]
        or report["vcs_isolation_ready"]
        or report["package_size_budget_ready"]
        or report["sensitive_local_path_finding_count"] != 0
        or report["package_payload_byte_count"] <= report["package_payload_budget_bytes"]
        or report["package_payload_over_budget_bytes"] <= 0
        or report["redistribution_review_file_count"] <= 0
        or report["oversized_payload_file_count"] <= 0
        or report["license_file_count"] != 0
        or report["citation_file_count"] != 0
        or report["redistribution_ledger_file_count"] != 0
        or not report["engineering_gate_passed"]
        or report["publication_or_upload_authorized"]
        or not report["artifact_checksums_match"]
        or report["historical_snapshot_superseded_by"]
        != "ti:packaging-split:r2-code-data-bundle-v1"
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-data-bundle")
def build_data_bundle(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the checksum-bound R2 local data bundle.")
    ] = Path("outputs/r2-data-bundle"),
) -> None:
    """Materialize the R2 bulk-data artifact separately from the code package."""

    snapshot, manifest = write_packaging_split_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | files={manifest.data_inventory_record_count} | "
        f"data_mib={quality.externalized_byte_count / 1024 / 1024:.1f} | "
        f"projected_code_mib={quality.projected_code_payload_byte_count / 1024 / 1024:.1f} | "
        "split_gate=true | upload_authorized=false"
    )
    typer.echo(f"data_inventory_sha256={manifest.data_inventory_sha256}")


@app.command("verify-packaging-split")
def verify_packaging_split() -> None:
    """Verify the frozen R2 split contract and source-data checksums."""

    report = load_default_packaging_split_store().quality_report()
    failed = (
        report["externalized_file_count"] != 24
        or report["externalized_byte_count"] <= 100 * 1024 * 1024
        or report["projected_code_payload_byte_count"]
        > report["code_payload_budget_bytes"]
        or not report["code_payload_within_budget"]
        or not report["external_data_root_contract_present"]
        or not report["external_data_required"]
        or not report["data_inventory_checksum_complete"]
        or report["redistribution_ledger_complete"]
        or report["data_bundle_publication_authorized"]
        or not report["code_data_split_engineering_gate_passed"]
        or report["scientific_claim_status_changed"]
        or report["c1_unblocked"]
        or report["c4_unblocked"]
        or not report["artifact_checksums_match"]
        or report["historical_snapshot_superseded_by"]
        != "ti:hydration-contract:r2.1-external-payload-v1"
        or not report["source_data_checksums_match"]
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("verify-data-bundle")
def verify_data_bundle(
    bundle_root: Annotated[
        Path, typer.Argument(help="Materialized R2 data-bundle root.")
    ] = Path("outputs/r2-data-bundle"),
) -> None:
    """Verify every materialized bulk file against the R2 inventory."""

    store = PackagingSplitStore.load(
        bundle_root / "r2_packaging_split_snapshot.json",
        bundle_root / "r2_packaging_split_manifest.json",
    )
    report = store.quality_report()
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if not report["artifact_checksums_match"] or not report[
        "materialized_data_checksums_match"
    ]:
        raise typer.Exit(code=1)


@app.command("build-hydration-plan")
def build_hydration_plan(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for R2.1 metadata-only hydration artifacts.")
    ] = Path("outputs/r2-1-hydration-plan"),
) -> None:
    """Build the operator recipe without accessing, copying, or downloading data."""

    snapshot, manifest = write_hydration_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | recipes={manifest.recipe_record_count} | "
        f"source_inputs={quality.user_acquired_source_input_count} | "
        f"derived_outputs={quality.deterministic_derived_output_count} | "
        "network_requests=0 | copies=0 | redistribution=false"
    )
    typer.echo(f"recipe_sha256={manifest.recipe_sha256}")


@app.command("verify-hydration-plan")
def verify_hydration_plan() -> None:
    """Verify the frozen R2.1 operator recipe and no-transfer boundary."""

    report = load_default_hydration_store().quality_report()
    failed = (
        report["artifact_count"] != 24
        or report["user_acquired_source_input_count"] != 10
        or report["deterministic_derived_output_count"] != 14
        or report["deterministic_rebuild_stage_count"] != 11
        or report["acquisition_command_coverage"] != 1.0
        or report["rebuild_command_coverage"] != 1.0
        or report["planning_network_request_count"] != 0
        or report["planning_file_copy_count"] != 0
        or report["redistribution_performed"]
        or report["small_packaged_fixture_redistribution_resolved"]
        or report["full_code_only_distribution_ready"]
        or not report["hydration_contract_engineering_gate_passed"]
        or report["scientific_claim_status_changed"]
        or report["c1_unblocked"]
        or report["c4_unblocked"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("inspect-data-root")
def inspect_data_root(
    data_root: Annotated[
        Path, typer.Argument(help="External data root to audit without modifying it.")
    ],
) -> None:
    """Report ready, missing, and checksum-mismatched hydration artifacts."""

    report = load_default_hydration_store().root_report(data_root)
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if not report["hydration_complete"]:
        raise typer.Exit(code=1)


@app.command("build-retained-fixture-audit")
def build_retained_fixture_audit(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for R2.2 metadata-only governance artifacts.")
    ] = Path("outputs/r2-2-retained-fixture-audit"),
) -> None:
    """Build the retained-fixture owner queue without changing package contents."""

    snapshot, manifest = write_retained_fixture_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | files={manifest.inventory_record_count} | "
        f"sources={quality.source_capture_count} | derived={quality.derived_artifact_count} | "
        "legal_conclusions=0 | mutations=0 | release_authorized=false"
    )
    typer.echo(f"inventory_sha256={manifest.inventory_sha256}")


@app.command("verify-retained-fixture-audit")
def verify_retained_fixture_audit() -> None:
    """Verify R2.2 inventory completeness and its non-authorization boundary."""

    report = load_default_retained_fixture_store().quality_report()
    failed = (
        report["retained_file_count"] != 129
        or report["classified_file_count"] != report["retained_file_count"]
        or report["inventory_coverage"] != 1.0
        or report["package_code_count"] != 1
        or report["source_capture_count"] != 14
        or report["curated_fixture_count"] != 4
        or report["derived_artifact_count"] != 99
        or report["release_metadata_count"] != 11
        or report["unresolved_redistribution_count"] != 129
        or report["legal_conclusion_count"] != 0
        or report["packaging_change_applied_count"] != 0
        or report["public_release_authorized"]
        or report["full_code_only_distribution_ready"]
        or not report["governance_inventory_engineering_gate_passed"]
        or report["scientific_claim_status_changed"]
        or report["c1_unblocked"]
        or report["c4_unblocked"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-fixture-dispositions")
def build_fixture_dispositions(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the R2.3 owner decision ledger.")
    ] = Path("outputs/r2-3-fixture-dispositions"),
) -> None:
    """Record retain/externalize/regenerate decisions without applying them."""

    snapshot, manifest = write_fixture_disposition_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | decisions={manifest.ledger_record_count} | "
        f"retain={quality.retain_count} | externalize={quality.externalize_count} | "
        f"regenerate={quality.regenerate_count} | applied=0 | release_authorized=false"
    )
    typer.echo(f"ledger_sha256={manifest.ledger_sha256}")


@app.command("verify-fixture-dispositions")
def verify_fixture_dispositions() -> None:
    """Verify complete R2.3 decisions and the closed execution boundary."""

    report = load_default_fixture_disposition_store().quality_report()
    failed = (
        report["inventory_record_count"] != 129
        or report["decision_record_count"] != 129
        or report["decision_coverage"] != 1.0
        or report["retain_count"] != 16
        or report["externalize_count"] != 14
        or report["regenerate_count"] != 99
        or report["project_owner_decision_count"] != 115
        or report["data_steward_decision_count"] != 14
        or report["conflicting_decision_count"] != 0
        or report["unresolved_packaging_disposition_count"] != 0
        or report["execution_applied_count"] != 0
        or report["redistribution_authorized_count"] != 0
        or not report["decision_ledger_engineering_gate_passed"]
        or report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or report["scientific_claim_status_changed"]
        or report["c1_unblocked"]
        or report["c4_unblocked"]
        or not report["parent_inventory_link_matches"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-execution-plan")
def build_execution_plan(
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the R2.4 plan and mutation preview.")
    ] = Path("outputs/r2-4-execution-plan"),
) -> None:
    """Build command recipes and an unapplied, non-destructive package preview."""

    snapshot, manifest = write_execution_plan_artifacts(output_dir)
    quality = snapshot.quality
    typer.echo(
        f"BUILT {snapshot.id} | recipes={manifest.execution_recipe_record_count} | "
        f"externalize={quality.externalize_recipe_count} | "
        f"regenerate={quality.regenerate_recipe_count} | "
        f"preview_exclude={quality.projected_exclude_count} | "
        "executed=0 | deleted=0 | config_writes=0"
    )
    typer.echo(f"recipe_sha256={manifest.execution_recipe_sha256}")
    typer.echo(f"preview_sha256={manifest.mutation_preview_sha256}")


@app.command("verify-execution-plan")
def verify_execution_plan() -> None:
    """Verify R2.4 recipe coverage and the non-destructive preview boundary."""

    report = load_default_execution_plan_store().quality_report()
    failed = (
        report["disposition_record_count"] != 129
        or report["execution_target_count"] != 113
        or report["execution_recipe_count"] != 113
        or report["unique_operator_command_count"] != 31
        or report["recipe_coverage"] != 1.0
        or report["externalize_recipe_count"] != 14
        or report["regenerate_recipe_count"] != 99
        or report["projected_retain_count"] != 16
        or report["projected_exclude_count"] != 113
        or report["projected_combined_exclude_count"] != 137
        or report["planning_network_request_count"] != 0
        or report["planning_command_execution_count"] != 0
        or report["source_file_delete_count"] != 0
        or report["configuration_write_count"] != 0
        or report["checksum_replay_count"] != 0
        or not report["execution_plan_engineering_gate_passed"]
        or not report["mutation_preview_engineering_gate_passed"]
        or report["checksum_replay_gate_passed"]
        or report["projected_runtime_smoke_gate_passed"]
        or report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or report["scientific_claim_status_changed"]
        or report["c1_unblocked"]
        or report["c4_unblocked"]
        or not report["parent_disposition_link_matches"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("run-execution-replay")
def run_execution_replay_command(
    staging_root: Annotated[
        Path, typer.Option(help="New isolated staging root; must not already exist.")
    ] = Path("outputs/r2-5-replay-staging"),
    bundle_root: Annotated[
        Path, typer.Option(help="Verified R2 data-bundle root used through read-only symlinks.")
    ] = Path("outputs/r2-data-bundle"),
    command_timeout_seconds: Annotated[
        int, typer.Option(min=60, help="Maximum wall time for each grouped command.")
    ] = 7200,
) -> None:
    """Execute all 31 R2.4 command groups in a new isolated staging root."""

    snapshot, _ = run_execution_replay(
        staging_root,
        bundle_root,
        command_timeout_seconds=command_timeout_seconds,
    )
    quality = snapshot.quality
    typer.echo(
        f"REPLAYED {snapshot.id} | groups={quality.executed_command_group_count}/31 | "
        f"successful={quality.successful_command_group_count} | "
        f"failed={quality.failed_command_group_count} | exact={quality.exact_match_count}/113 | "
        f"mismatch={quality.checksum_mismatch_count} | missing={quality.missing_count} | "
        "deleted=0 | config_writes=0"
    )


@app.command("verify-execution-replay")
def verify_execution_replay(
    replay_root: Annotated[
        Path, typer.Argument(help="Completed R2.5 replay staging root.")
    ] = Path("outputs/r2-5-replay-staging"),
) -> None:
    """Verify replay-ledger integrity without requiring all outputs to match."""

    store = ExecutionReplayStore.load(
        replay_root / "r2_5_execution_replay_snapshot.json",
        replay_root / "r2_5_execution_replay_manifest.json",
    )
    report = store.quality_report()
    failed = (
        report["command_group_count"] != 31
        or report["executed_command_group_count"] != 31
        or report["artifact_count"] != 113
        or report["exact_match_count"]
        + report["checksum_mismatch_count"]
        + report["missing_count"]
        != 113
        or report["bulk_symlink_count"] != 24
        or report["data_file_copy_count"] != 0
        or report["source_file_delete_count"] != 0
        or report["configuration_write_count"] != 0
        or not report["replay_execution_complete"]
        or report["projected_runtime_smoke_gate_passed"]
        or report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or not report["parent_execution_plan_link_matches"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("diagnose-execution-replay")
def diagnose_execution_replay(
    replay_root: Annotated[
        Path, typer.Argument(help="Completed execution-replay staging root.")
    ],
) -> None:
    """Classify byte drift without accepting normalized equality as a gate."""

    snapshot, _ = write_replay_hardening_artifacts(replay_root)
    quality = snapshot.quality
    typer.echo(
        f"DIAGNOSED {snapshot.id} | artifacts={quality.artifact_count} | "
        f"exact={quality.exact_byte_match_count} | "
        f"metadata_only={quality.declared_metadata_only_drift_count} | "
        f"substantive={quality.substantive_content_drift_count} | "
        f"missing_capture={quality.missing_capture_output_count} | "
        f"missing_dependency={quality.missing_dependency_output_count} | "
        f"byte_gate={str(quality.byte_checksum_gate_passed).lower()}"
    )


@app.command("run-hardened-execution-replay")
def run_hardened_execution_replay_command(
    staging_root: Annotated[
        Path, typer.Option(help="New isolated staging root; must not already exist.")
    ] = Path("outputs/r2-6-replay-staging"),
    bundle_root: Annotated[
        Path, typer.Option(help="Verified R2 data-bundle root used through read-only symlinks.")
    ] = Path("outputs/r2-data-bundle"),
    command_timeout_seconds: Annotated[
        int, typer.Option(min=60, help="Maximum wall time for each grouped command.")
    ] = 7200,
) -> None:
    """Replay all groups with bounded clinical-source retries and drift diagnosis."""

    snapshot, _ = run_hardened_execution_replay(
        staging_root,
        bundle_root,
        command_timeout_seconds=command_timeout_seconds,
    )
    quality = snapshot.quality
    typer.echo(
        f"HARDENED {snapshot.id} | artifacts={quality.artifact_count} | "
        f"exact={quality.exact_byte_match_count} | "
        f"metadata_only={quality.declared_metadata_only_drift_count} | "
        f"substantive={quality.substantive_content_drift_count} | "
        f"missing={quality.missing_capture_output_count + quality.missing_dependency_output_count + quality.missing_command_output_count} | "
        f"byte_gate={str(quality.byte_checksum_gate_passed).lower()} | "
        f"normalized_diagnostic={str(quality.metadata_normalized_diagnostic_passed).lower()}"
    )


@app.command("verify-replay-hardening")
def verify_replay_hardening(
    replay_root: Annotated[
        Path, typer.Argument(help="Replay root containing the R2.6 diagnosis artifacts.")
    ],
) -> None:
    """Verify complete R2.6 diagnosis while keeping package gates closed."""

    store = ReplayHardeningStore.load(
        replay_root / "r2_6_replay_hardening_snapshot.json",
        replay_root / "r2_6_replay_hardening_manifest.json",
    )
    report = store.quality_report()
    failed = (
        report["artifact_count"] != 113
        or report["diagnostic_coverage"] != 1.0
        or report["exact_byte_match_count"]
        + report["declared_metadata_only_drift_count"]
        + report["substantive_content_drift_count"]
        + report["missing_capture_output_count"]
        + report["missing_dependency_output_count"]
        + report["missing_command_output_count"]
        != 113
        or report["maximum_download_attempt_count"] != 3
        or report["projected_runtime_smoke_gate_passed"]
        or report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or not report["parent_execution_replay_link_matches"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("approve-canonical-content")
def approve_canonical_content(
    replay_root: Annotated[
        Path, typer.Option(help="Frozen R2.6 replay root to evaluate against canonical-content v1.")
    ] = Path("outputs/r2-6-replay-staging-integrity"),
    output_dir: Annotated[
        Path, typer.Option(help="Destination for the R2.7 acceptance ledger.")
    ] = Path("outputs/r2-7-canonical-acceptance"),
) -> None:
    """Apply the owner-approved, field-level canonical-content v1 contract."""

    snapshot, _ = write_canonical_acceptance_artifacts(replay_root, output_dir)
    quality = snapshot.quality
    typer.echo(
        f"APPROVED {snapshot.id} | byte_identity={quality.byte_identity_acceptance_count} | "
        f"canonical_v1={quality.canonical_content_acceptance_count} | "
        f"rejected={quality.rejected_count} | "
        f"canonical_gate={str(quality.canonical_content_gate_passed).lower()} | "
        "runtime_smoke=false | convergence=false"
    )
    if not quality.canonical_content_gate_passed:
        raise typer.Exit(code=1)


@app.command("verify-canonical-content")
def verify_canonical_content(
    acceptance_root: Annotated[
        Path, typer.Argument(help="Root containing the frozen R2.7 acceptance artifacts.")
    ] = Path("outputs/r2-7-canonical-acceptance"),
) -> None:
    """Verify canonical-content v1 without implying package convergence."""

    store = CanonicalAcceptanceStore.load(
        acceptance_root / "r2_7_canonical_acceptance_snapshot.json",
        acceptance_root / "r2_7_canonical_acceptance_manifest.json",
    )
    report = store.quality_report()
    failed = (
        report["artifact_count"] != 113
        or report["byte_identity_acceptance_count"] != 66
        or report["canonical_content_acceptance_count"] != 47
        or report["rejected_count"] != 0
        or not report["changed_path_map_matches_approved_v1"]
        or report["semantic_guard_failure_count"] != 0
        or report["canonical_mismatch_count"] != 0
        or not report["canonical_content_gate_passed"]
        or report["byte_checksum_gate_passed"]
        or report["projected_runtime_smoke_gate_passed"]
        or report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or not report["parent_replay_hardening_link_matches"]
        or not report["artifact_checksums_match"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command("build-package-convergence")
def build_package_convergence(
    output_dir: Annotated[
        Path, typer.Option(help="New output root for the built wheel and R2.8 smoke evidence.")
    ] = Path("outputs/r2-8-package-convergence"),
    external_data_root: Annotated[
        Path, typer.Option(help="Validated replay/data root used by installed-wheel smoke checks.")
    ] = Path("outputs/r2-6-replay-staging-integrity"),
) -> None:
    """Build the code-only wheel and run its offline installed-runtime smoke."""

    snapshot, _ = run_package_convergence(output_dir, external_data_root)
    quality = snapshot.quality
    typer.echo(
        f"CONVERGED {snapshot.id} | governed_exclusions={quality.governed_data_exclusion_count} | "
        f"self_attestation_exclusions={quality.external_self_attestation_exclusion_count} | "
        f"source_present={quality.source_file_present_count} | "
        f"smoke={quality.runtime_smoke_passed_count}/{quality.runtime_smoke_check_count} | "
        f"external_resolution={quality.external_resolution_smoke_count} | "
        f"runtime_gate={str(quality.projected_runtime_smoke_gate_passed).lower()} | "
        f"package_gate={str(quality.package_convergence_gate_passed).lower()} | "
        "release_authorized=false"
    )
    if not quality.package_convergence_gate_passed:
        raise typer.Exit(code=1)


@app.command("verify-package-convergence")
def verify_package_convergence(
    convergence_root: Annotated[
        Path, typer.Argument(help="Root containing R2.8 package-convergence artifacts.")
    ] = Path("outputs/r2-8-package-convergence"),
) -> None:
    """Verify R2.8 package convergence without authorizing publication."""

    store = PackageConvergenceStore.load(
        convergence_root / "r2_8_package_convergence_snapshot.json",
        convergence_root / "r2_8_package_convergence_manifest.json",
    )
    report = store.quality_report()
    failed = (
        not report["canonical_content_gate_passed"]
        or report["byte_checksum_gate_passed"]
        or report["owner_disposition_exclusion_count"] != 113
        or report["existing_bulk_exclusion_count"] != 24
        or report["external_self_attestation_exclusion_count"] != 4
        or report["governed_data_exclusion_count"] != 137
        or report["combined_exclusion_count"] != 141
        or report["source_file_present_count"] != 141
        or report["source_file_delete_count"] != 0
        or report["wheel_config_exclusion_count"] != 141
        or report["sdist_config_exclusion_count"] != 141
        or not report["configuration_mutation_applied"]
        or report["unexpectedly_packaged_excluded_count"] != 0
        or report["external_resolution_smoke_count"] != 137
        or report["runtime_smoke_check_count"] != 7
        or report["runtime_smoke_passed_count"] != 7
        or report["runtime_smoke_network_request_count"] != 0
        or not report["projected_runtime_smoke_gate_passed"]
        or not report["package_convergence_gate_passed"]
        or report["public_release_authorized"]
        or report["data_bundle_publication_authorized"]
        or not report["parent_canonical_acceptance_link_matches"]
        or not report["metadata_artifact_checksums_match"]
        or report["wheel_checksum_matches"] is False
        or not report["pyproject_checksum_matches"]
        or report["source_checksums_match"] is False
    )
    typer.echo(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    if failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Run the read-only P0.2 dossier and P1 evidence explorer."""

    uvicorn.run("targetideator.demo:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
