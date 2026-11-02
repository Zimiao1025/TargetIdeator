"""Build P5.4 descriptive mapping-missingness and unresolved triage artifacts."""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.ingestion.identity_sources import THERAPEUTIC_INTERVENTION_TYPES
from targetideator.io import write_json
from targetideator.outcomes.broad_store import load_default_broad_outcome_store
from targetideator.outcomes.identity_store import (
    _read_gzip_json,
    _read_jsonl_gzip,
    _write_jsonl_gzip,
    default_drug_dictionary_raw_path,
    load_default_identity_store,
    normalize_drug_name,
)
from targetideator.outcomes.mapping_audit_models import (
    CoverageStratum,
    MappingAuditManifest,
    MappingAuditQuality,
    MappingAuditSnapshot,
)

BUILDER_VERSION = "p5.4-mapping-missingness-triage-v1"
SNAPSHOT_ID = "ti:mapping-audit:three-aact-baselines-v1"
CREATED_AT = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)
SPLITS = ("train", "validation", "test")


def default_intervention_raw_paths() -> list[Path]:
    return [
        fixture_path(f"aact_broad_interventions_{split}_raw.json.gz")
        for split in SPLITS
    ]


def default_mapping_audit_snapshot_path() -> Path:
    return fixture_path("p5_4_mapping_audit_snapshot.json")


def default_mapping_audit_manifest_path() -> Path:
    return fixture_path("p5_4_mapping_audit_manifest.json")


def _name_dictionary(capture: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in capture["rows"]:
        values = [row.get("name"), *(row.get("tradeNames") or []), *(row.get("synonyms") or [])]
        for value in values:
            normalized = normalize_drug_name(value)
            if normalized:
                result[normalized].add(row["id"])
    return result


def _intervention_indexes(captures: list[dict]) -> tuple[dict, dict]:
    by_split_nct: dict[tuple[str, str], list[dict]] = defaultdict(list)
    versions = {}
    for capture in captures:
        split = capture["split"]
        versions[split] = capture["baseline_version"]
        for row in capture["interventions"]:
            by_split_nct[(split, row["nct_id"])].append(row)
    return by_split_nct, versions


def _snapshot_interventions(
    split: str, nct_id: str, rows: list[dict], baseline_version: str
) -> dict:
    therapeutic = [
        row for row in rows if row["intervention_type"] in THERAPEUTIC_INTERVENTION_TYPES
    ]
    raw_names = sorted(
        {
            value
            for row in therapeutic
            for value in [row.get("name"), *(row.get("aliases") or [])]
            if value
        }
    )
    normalized_names = sorted(
        {value for name in raw_names if (value := normalize_drug_name(name))}
    )
    if not rows:
        profile = "no_aact_intervention_row"
    elif not therapeutic:
        profile = "non_therapeutic_interventions_only"
    else:
        profile = "therapeutic_intervention_present"
    return {
        "split": split,
        "baseline_version": baseline_version,
        "intervention_profile": profile,
        "all_intervention_types": sorted({row["intervention_type"] for row in rows}),
        "therapeutic_intervention_types": sorted(
            {row["intervention_type"] for row in therapeutic}
        ),
        "therapeutic_names_and_aliases": raw_names,
        "normalized_therapeutic_names": normalized_names,
    }


def _name_stability(snapshots: list[dict]) -> str:
    if len(snapshots) == 1:
        return "single_snapshot"
    values = {tuple(item["normalized_therapeutic_names"]) for item in snapshots}
    return (
        "stable_exact_normalized_set"
        if len(values) == 1
        else "changed_across_snapshots"
    )


def _unresolved_reason(snapshots: list[dict], candidate_ids: set[str]) -> str:
    profiles = {item["intervention_profile"] for item in snapshots}
    if profiles == {"no_aact_intervention_row"}:
        return "no_aact_intervention_row"
    if "therapeutic_intervention_present" not in profiles:
        return "non_therapeutic_interventions_only"
    if not candidate_ids:
        return "therapeutic_name_no_exact_captured_mapping_drug_match"
    if len(candidate_ids) == 1:
        return "exact_mapped_drug_candidate_no_trial_target_assertion"
    return "ambiguous_exact_mapped_drug_candidates_no_trial_target_assertion"


def _recommended_action(reason: str | None) -> str:
    return {
        None: "none_source_asserted_mapping_present",
        "no_aact_intervention_row": "inspect_registry_capture_completeness",
        "non_therapeutic_interventions_only": "exclude_or_review_non_drug_trial_scope",
        "therapeutic_name_no_exact_captured_mapping_drug_match": (
            "expand_versioned_drug_identity_coverage_without_inferring_target"
        ),
        "exact_mapped_drug_candidate_no_trial_target_assertion": (
            "seek_versioned_source_asserted_trial_target_evidence"
        ),
        "ambiguous_exact_mapped_drug_candidates_no_trial_target_assertion": (
            "resolve_drug_parent_child_identity_then_seek_target_evidence"
        ),
    }[reason]


def build_mapping_audit_records(
    intervention_paths: list[Path] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    identity_store = load_default_identity_store()
    broad_store = load_default_broad_outcome_store()
    outcome_records = _read_jsonl_gzip(
        artifact_path(broad_store.root, broad_store.manifest.normalized_dataset_path)
    )
    mappings = _read_jsonl_gzip(
        artifact_path(identity_store.root, identity_store.manifest.mapping_path)
    )
    captures = [
        _read_gzip_json(path) for path in (intervention_paths or default_intervention_raw_paths())
    ]
    dictionary_capture = _read_gzip_json(default_drug_dictionary_raw_path())
    name_to_drugs = _name_dictionary(dictionary_capture)
    by_split_nct, versions = _intervention_indexes(captures)

    outcomes_by_nct: dict[str, list[dict]] = defaultdict(list)
    for row in outcome_records:
        outcomes_by_nct[row["nct_id"]].append(row)
    mappings_by_nct: dict[str, list[dict]] = defaultdict(list)
    for row in mappings:
        mappings_by_nct[row["nct_id"]].append(row)

    records = []
    profiles_by_split_nct = {}
    stability_by_nct = {}
    for nct_id, nct_outcomes in sorted(outcomes_by_nct.items()):
        observed_splits = sorted({row["split"] for row in nct_outcomes}, key=SPLITS.index)
        snapshots = []
        for split in observed_splits:
            snapshot = _snapshot_interventions(
                split,
                nct_id,
                by_split_nct.get((split, nct_id), []),
                versions[split],
            )
            snapshots.append(snapshot)
            profiles_by_split_nct[(split, nct_id)] = snapshot["intervention_profile"]
        stability = _name_stability(snapshots)
        stability_by_nct[nct_id] = stability
        normalized_names = {
            name for snapshot in snapshots for name in snapshot["normalized_therapeutic_names"]
        }
        bindings = [
            {"normalized_name": name, "drug_chembl_ids": sorted(name_to_drugs[name])}
            for name in sorted(normalized_names)
            if name in name_to_drugs
        ]
        candidate_ids = {
            drug_id for binding in bindings for drug_id in binding["drug_chembl_ids"]
        }
        nct_mappings = mappings_by_nct.get(nct_id, [])
        mapped_drug_ids = {item["drug_chembl_id"] for item in nct_mappings}
        mapped_drug_name_agreement_ids = sorted(candidate_ids & mapped_drug_ids)
        if not nct_mappings:
            mapping_name_audit_status = "not_applicable_unresolved"
        elif not normalized_names:
            mapping_name_audit_status = "no_therapeutic_name_available"
        elif mapped_drug_name_agreement_ids:
            mapping_name_audit_status = "exact_normalized_mapped_drug_agreement"
        else:
            mapping_name_audit_status = "no_exact_normalized_mapped_drug_agreement"
        reason = None if nct_mappings else _unresolved_reason(snapshots, candidate_ids)
        records.append(
            {
                "id": stable_id("mapping-audit", nct_id),
                "nct_id": nct_id,
                "mapping_status": (
                    "source_asserted_mapping_present" if nct_mappings else "unresolved"
                ),
                "unresolved_reason": reason,
                "recommended_action": _recommended_action(reason),
                "observed_splits": observed_splits,
                "observed_phases": sorted({row["phase"] for row in nct_outcomes}),
                "observed_source_classes": sorted(
                    {row["source_class"] for row in nct_outcomes}
                ),
                "observed_outcome_categories": sorted(
                    {row["outcome_category"] for row in nct_outcomes}
                ),
                "name_stability": stability,
                "intervention_snapshots": snapshots,
                "mapping_ids": sorted(item["id"] for item in nct_mappings),
                "mapped_drug_chembl_ids": sorted(mapped_drug_ids),
                "mapped_target_ensembl_ids": sorted(
                    {item["target_ensembl_id"] for item in nct_mappings}
                ),
                "exact_name_candidate_bindings": bindings if not nct_mappings else [],
                "exact_name_candidate_drug_ids": (
                    sorted(candidate_ids) if not nct_mappings else []
                ),
                "mapping_name_audit_status": mapping_name_audit_status,
                "mapped_drug_exact_name_agreement_ids": mapped_drug_name_agreement_ids,
                "candidate_ids_are_mapping_evidence": False,
                "automatic_mapping_permitted": False,
                "fuzzy_matching_used": False,
            }
        )

    mapped_nct = set(mappings_by_nct)
    overall = sum(row["nct_id"] in mapped_nct for row in outcome_records) / len(outcome_records)
    dimensions = {
        "split": lambda row: row["split"],
        "phase": lambda row: row.get("phase") or "missing",
        "source_class": lambda row: row.get("source_class") or "missing",
        "baseline_status": lambda row: row.get("baseline_status") or "missing",
        "fda_regulated_drug": lambda row: (
            "missing"
            if row.get("is_fda_regulated_drug") is None
            else str(row["is_fda_regulated_drug"]).lower()
        ),
        "outcome_category": lambda row: row["outcome_category"],
        "intervention_profile": lambda row: profiles_by_split_nct[(row["split"], row["nct_id"])],
        "name_stability": lambda row: stability_by_nct[row["nct_id"]],
    }
    strata = []
    for dimension, value_fn in dimensions.items():
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for row in outcome_records:
            value = str(value_fn(row))
            counts[value][0] += 1
            counts[value][1] += row["nct_id"] in mapped_nct
        for value, (total, mapped) in sorted(counts.items()):
            coverage = mapped / total
            strata.append(
                CoverageStratum(
                    dimension=dimension,
                    value=value,
                    total_record_count=total,
                    mapped_record_count=mapped,
                    unmapped_record_count=total - mapped,
                    coverage=coverage,
                    coverage_difference_from_overall=coverage - overall,
                    small_cell=total < 100,
                ).model_dump(mode="json")
            )
    metadata = {
        "captures": captures,
        "outcome_records": outcome_records,
        "mapped_nct": mapped_nct,
        "stability_by_nct": stability_by_nct,
    }
    return records, strata, metadata


def _quality(records: list[dict], strata: list[dict], metadata: dict) -> MappingAuditQuality:
    outcomes = metadata["outcome_records"]
    mapped_nct = metadata["mapped_nct"]
    reasons = Counter(
        row["unresolved_reason"] for row in records if row["unresolved_reason"]
    )
    repeated = [row for row in records if len(row["observed_splits"]) > 1]
    mapped_records = [
        row for row in records if row["mapping_status"] == "source_asserted_mapping_present"
    ]
    all_capture_nct = {
        item["nct_id"]
        for capture in metadata["captures"]
        for item in capture["interventions"]
    }
    return MappingAuditQuality(
        outcome_record_count=len(outcomes),
        unique_nct_count=len(records),
        mapped_unique_nct_count=len(mapped_nct),
        unresolved_unique_nct_count=len(records) - len(mapped_nct),
        mapped_outcome_record_count=sum(row["nct_id"] in mapped_nct for row in outcomes),
        unresolved_reason_counts=dict(sorted(reasons.items())),
        intervention_capture_count=len(metadata["captures"]),
        intervention_capture_complete_count=sum(
            capture["complete_for_query"] for capture in metadata["captures"]
        ),
        nct_with_intervention_coverage=len(all_capture_nct) / len(records),
        repeated_nct_count=len(repeated),
        repeated_nct_stable_name_count=sum(
            row["name_stability"] == "stable_exact_normalized_set" for row in repeated
        ),
        repeated_nct_changed_name_count=sum(
            row["name_stability"] == "changed_across_snapshots" for row in repeated
        ),
        mapped_nct_exact_name_agreement_count=sum(
            row["mapping_name_audit_status"]
            == "exact_normalized_mapped_drug_agreement"
            for row in mapped_records
        ),
        mapped_nct_no_exact_name_agreement_count=sum(
            row["mapping_name_audit_status"]
            == "no_exact_normalized_mapped_drug_agreement"
            for row in mapped_records
        ),
        mapped_nct_without_therapeutic_name_count=sum(
            row["mapping_name_audit_status"] == "no_therapeutic_name_available"
            for row in mapped_records
        ),
        coverage_stratum_count=len(strata),
        material_coverage_disparity_stratum_count=sum(
            row["total_record_count"] >= 100
            and abs(row["coverage_difference_from_overall"]) >= 0.1
            for row in strata
        ),
        engineering_gate_passed=(
            len(records) == 36086
            and len(outcomes) == 71947
            and len(metadata["captures"]) == 3
            and all(capture["complete_for_query"] for capture in metadata["captures"])
            and sum(reasons.values()) == 21694
        ),
        blocking_limitations=[
            "Exact drug-name candidates are triage hints, not trial-target mapping evidence.",
            "The captured drug dictionary contains drugs already present in the 25.09 mapping evidence, not every possible intervention identity.",
            "Coverage strata are descriptive and confounded; no missing-at-random claim or causal adjustment is made.",
            "Open Targets 25.09 identity remains forbidden as a temporal outcome-model feature.",
            "Target-level scientific validation remains blocked by incomplete and systematically varying mapping coverage.",
        ],
    )


def render_mapping_audit_report(snapshot: MappingAuditSnapshot) -> str:
    q = snapshot.quality
    lines = [
        "# TargetIdeator P5.4 mapping missingness and unresolved triage",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Unique NCT: {q.unique_nct_count}",
        f"- Mapped / unresolved: {q.mapped_unique_nct_count} / {q.unresolved_unique_nct_count}",
        f"- Intervention captures complete: {q.intervention_capture_complete_count}/{q.intervention_capture_count}",
        f"- Repeated NCT with changed normalized names: {q.repeated_nct_changed_name_count}/{q.repeated_nct_count}",
        f"- Material descriptive coverage disparities: {q.material_coverage_disparity_stratum_count}",
        "",
        "## Unresolved taxonomy",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in q.unresolved_reason_counts.items())
    lines.extend(["", "## Coverage strata", ""])
    lines.extend(
        f"- `{row.dimension}={row.value}`: {row.mapped_record_count}/{row.total_record_count} "
        f"({row.coverage:.3f}; delta {row.coverage_difference_from_overall:+.3f})"
        for row in snapshot.strata
    )
    lines.extend(["", "## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in q.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def write_mapping_audit_artifacts(
    output_dir: Path, intervention_paths: list[Path] | None = None
) -> tuple[MappingAuditSnapshot, MappingAuditManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = intervention_paths or default_intervention_raw_paths()
    records, strata, metadata = build_mapping_audit_records(paths)
    triage_path = output_dir / "p5_4_mapping_triage.jsonl.gz"
    _write_jsonl_gzip(triage_path, records)
    quality = _quality(records, strata, metadata)
    snapshot = MappingAuditSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        triage_path=triage_path.name,
        triage_sha256=file_sha256(triage_path),
        strata=[CoverageStratum.model_validate(row) for row in strata],
        quality=quality,
        warning=(
            "DESCRIPTIVE DATA-AUDIT ONLY. Exact name candidates never create a mapping, "
            "and coverage differences are not causal or model-validation results."
        ),
    )
    snapshot_path = output_dir / "p5_4_mapping_audit_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_4_mapping_audit_report.md").write_text(
        render_mapping_audit_report(snapshot), encoding="utf-8"
    )
    identity_store = load_default_identity_store()
    broad_store = load_default_broad_outcome_store()
    broad_path = artifact_path(
        broad_store.root, broad_store.manifest.normalized_dataset_path
    )
    mapping_path = artifact_path(identity_store.root, identity_store.manifest.mapping_path)
    source_checksums = {
        path.name: file_sha256(path) for path in paths
    } | {
        default_drug_dictionary_raw_path().name: file_sha256(default_drug_dictionary_raw_path()),
        mapping_path.name: file_sha256(mapping_path),
        broad_path.name: file_sha256(broad_path),
    }
    manifest = MappingAuditManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=source_checksums,
        triage_path=triage_path.name,
        triage_sha256=file_sha256(triage_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
        triage_record_count=len(records),
    )
    write_json(
        output_dir / "p5_4_mapping_audit_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class MappingAuditStore:
    def __init__(
        self, snapshot: MappingAuditSnapshot, manifest: MappingAuditManifest, root: Path
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "MappingAuditStore":
        return cls(
            MappingAuditSnapshot.model_validate(_load_json(snapshot_path)),
            MappingAuditManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def sample_triage(self, limit: int = 20, reason: str | None = None) -> list[dict]:
        result = []
        with gzip.open(
            artifact_path(self.root, self.manifest.triage_path), "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if reason is None or row["unresolved_reason"] == reason:
                    result.append(row)
                    if len(result) >= limit:
                        break
        return result

    def trial(self, nct_id: str) -> dict | None:
        with gzip.open(
            artifact_path(self.root, self.manifest.triage_path), "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if row["nct_id"] == nct_id:
                    return row
        return None

    def strata(self, dimension: str | None = None, min_count: int = 0) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in self.snapshot.strata
            if (dimension is None or item.dimension == dimension)
            and item.total_record_count >= min_count
        ]

    def quality_report(self) -> dict:
        identity_store = load_default_identity_store()
        broad_store = load_default_broad_outcome_store()
        broad_path = artifact_path(
            broad_store.root, broad_store.manifest.normalized_dataset_path
        )
        mapping_path = artifact_path(
            identity_store.root, identity_store.manifest.mapping_path
        )
        expected = {
            path.name: file_sha256(path) for path in default_intervention_raw_paths()
        } | {
            default_drug_dictionary_raw_path().name: file_sha256(default_drug_dictionary_raw_path()),
            mapping_path.name: file_sha256(mapping_path),
            broad_path.name: file_sha256(broad_path),
        }
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.triage_path))
                == self.manifest.triage_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_mapping_audit_store() -> MappingAuditStore:
    return MappingAuditStore.load(
        default_mapping_audit_snapshot_path(), default_mapping_audit_manifest_path()
    )
