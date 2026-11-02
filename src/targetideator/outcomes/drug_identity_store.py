"""Build P5.5 exact-name molecule-family resolution without target inference."""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import stable_id
from targetideator.io import write_json
from targetideator.outcomes.drug_identity_models import (
    DrugIdentityManifest,
    DrugIdentityQuality,
    DrugIdentitySnapshot,
)
from targetideator.outcomes.identity_store import (
    _read_gzip_json,
    _write_jsonl_gzip,
    normalize_drug_name,
)
from targetideator.outcomes.mapping_audit_store import (
    default_mapping_audit_manifest_path,
    load_default_mapping_audit_store,
)

BUILDER_VERSION = "p5.5-versioned-drug-family-resolution-v1"
SNAPSHOT_ID = "ti:drug-identity-resolution:opentargets-25-09-v1"
CREATED_AT = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)


def default_full_drug_dictionary_raw_path() -> Path:
    return fixture_path("opentargets_25_09_full_drug_dictionary_raw.json.gz")


def default_drug_identity_snapshot_path() -> Path:
    return fixture_path("p5_5_drug_identity_snapshot.json")


def default_drug_identity_manifest_path() -> Path:
    return fixture_path("p5_5_drug_identity_manifest.json")


def _hierarchy(rows: dict[str, dict]) -> tuple[dict[str, str], dict[str, str], int]:
    roots = {}
    statuses = {}
    cycles: set[tuple[str, ...]] = set()
    for drug_id in rows:
        current = drug_id
        path = []
        positions = {}
        while current in rows and rows[current].get("parentId"):
            if current in positions:
                cycle = tuple(sorted(path[positions[current] :]))
                cycles.add(cycle)
                current = min(cycle)
                statuses[drug_id] = "cycle_canonicalized"
                break
            positions[current] = len(path)
            path.append(current)
            current = rows[current]["parentId"]
        if drug_id not in statuses:
            statuses[drug_id] = (
                "source_parent_root"
                if current in rows
                else "dangling_source_parent_root"
            )
        roots[drug_id] = current
    return roots, statuses, len(cycles)


def _name_index(rows: dict[str, dict]) -> tuple[dict, int]:
    index: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: {"source_fields": set(), "source_values": set()})
    )
    for drug_id, row in rows.items():
        fields = {
            "preferred_name": [row.get("name")],
            "trade_name": row.get("tradeNames") or [],
            "synonym": row.get("synonyms") or [],
        }
        for field, values in fields.items():
            for value in values:
                normalized = normalize_drug_name(value)
                if normalized:
                    index[normalized][drug_id]["source_fields"].add(field)
                    index[normalized][drug_id]["source_values"].add(value)
    return index, len(index)


def _status(
    therapeutic_present: bool,
    matched_names: set[str],
    unmatched_names: set[str],
    ambiguous_names: set[str],
) -> str:
    if not therapeutic_present:
        return "non_therapeutic_interventions_only"
    if not matched_names:
        return "no_exact_full_dictionary_match"
    if ambiguous_names:
        return "ambiguous_exact_name_to_multiple_families"
    if unmatched_names:
        return "partial_exact_family_resolution"
    return "complete_exact_family_resolution"


def build_drug_identity_records(
    dictionary_path: Path | None = None,
) -> tuple[list[dict], dict]:
    dictionary_capture = _read_gzip_json(
        dictionary_path or default_full_drug_dictionary_raw_path()
    )
    molecule_rows = {row["id"]: row for row in dictionary_capture["rows"]}
    roots, hierarchy_statuses, cycle_count = _hierarchy(molecule_rows)
    name_index, normalized_name_count = _name_index(molecule_rows)
    audit_store = load_default_mapping_audit_store()
    unresolved_rows = audit_store.sample_triage(audit_store.manifest.triage_record_count)
    unresolved_rows = [
        row for row in unresolved_rows if row["mapping_status"] == "unresolved"
    ]

    records = []
    for audit in unresolved_rows:
        normalized_names = {
            name
            for snapshot in audit["intervention_snapshots"]
            for name in snapshot["normalized_therapeutic_names"]
        }
        therapeutic_present = any(
            snapshot["intervention_profile"] == "therapeutic_intervention_present"
            for snapshot in audit["intervention_snapshots"]
        )
        bindings = []
        matched_names = set()
        unmatched_names = set()
        ambiguous_names = set()
        candidate_ids = set()
        family_ids = set()
        for name in sorted(normalized_names):
            matches = name_index.get(name, {})
            matched_drug_ids = sorted(matches)
            matched_family_ids = sorted({roots[item] for item in matches})
            if not matched_drug_ids:
                match_status = "unmatched"
                unmatched_names.add(name)
            elif len(matched_family_ids) == 1:
                match_status = "unique_family_exact_match"
                matched_names.add(name)
            else:
                match_status = "ambiguous_family_exact_match"
                matched_names.add(name)
                ambiguous_names.add(name)
            candidate_ids.update(matched_drug_ids)
            family_ids.update(matched_family_ids)
            bindings.append(
                {
                    "normalized_trial_name": name,
                    "match_status": match_status,
                    "matched_chembl_ids": matched_drug_ids,
                    "matched_molecule_family_ids": matched_family_ids,
                    "dictionary_matches": [
                        {
                            "drug_chembl_id": drug_id,
                            "molecule_family_id": roots[drug_id],
                            "hierarchy_status": hierarchy_statuses[drug_id],
                            "source_fields": sorted(matches[drug_id]["source_fields"]),
                            "source_values": sorted(matches[drug_id]["source_values"]),
                        }
                        for drug_id in matched_drug_ids
                    ],
                }
            )
        resolution_status = _status(
            therapeutic_present, matched_names, unmatched_names, ambiguous_names
        )
        family_summaries = []
        for family_id in sorted(family_ids):
            root_row = molecule_rows.get(family_id)
            family_summaries.append(
                {
                    "molecule_family_id": family_id,
                    "root_record_available": root_row is not None,
                    "root_preferred_name": root_row.get("name") if root_row else None,
                    "root_drug_type": root_row.get("drugType") if root_row else None,
                    "matched_candidate_ids": sorted(
                        item for item in candidate_ids if roots[item] == family_id
                    ),
                }
            )
        matched_coverage = (
            len(matched_names) / len(normalized_names) if normalized_names else 0.0
        )
        records.append(
            {
                "id": stable_id("drug-identity-resolution", audit["nct_id"]),
                "nct_id": audit["nct_id"],
                "source_mapping_status": "unresolved_no_trial_target_assertion",
                "p5_4_unresolved_reason": audit["unresolved_reason"],
                "resolution_status": resolution_status,
                "normalized_therapeutic_name_count": len(normalized_names),
                "matched_normalized_name_count": len(matched_names),
                "matched_name_coverage": matched_coverage,
                "unmatched_normalized_names": sorted(unmatched_names),
                "ambiguous_normalized_names": sorted(ambiguous_names),
                "name_bindings": bindings,
                "candidate_chembl_ids": sorted(candidate_ids),
                "candidate_molecule_family_ids": sorted(family_ids),
                "candidate_molecule_family_count": len(family_ids),
                "family_summaries": family_summaries,
                "multi_drug_trial_possible": (
                    len(family_ids) > 1 and not ambiguous_names
                ),
                "drug_identity_resolution_level": (
                    "exact_name_family_candidate"
                    if matched_names
                    else "unresolved_drug_identity"
                ),
                "target_assertion_status": "missing_source_asserted_trial_target",
                "drug_identity_candidate_is_target_evidence": False,
                "automatic_trial_drug_mapping_permitted": False,
                "automatic_trial_target_mapping_permitted": False,
                "fuzzy_matching_used": False,
                "temporal_model_feature_use_allowed": False,
            }
        )
    metadata = {
        "dictionary_capture": dictionary_capture,
        "molecule_rows": molecule_rows,
        "roots": roots,
        "normalized_name_count": normalized_name_count,
        "cycle_count": cycle_count,
    }
    return records, metadata


def _quality(records: list[dict], metadata: dict) -> DrugIdentityQuality:
    molecule_rows = metadata["molecule_rows"]
    roots = metadata["roots"]
    statuses = Counter(row["resolution_status"] for row in records)
    exact_matched = sum(bool(row["candidate_chembl_ids"]) for row in records)
    therapeutic_count = len(records) - statuses["non_therapeutic_interventions_only"]
    nonambiguous = [
        row
        for row in records
        if row["resolution_status"]
        in {"complete_exact_family_resolution", "partial_exact_family_resolution"}
    ]
    return DrugIdentityQuality(
        full_dictionary_row_count=len(molecule_rows),
        normalized_dictionary_name_count=metadata["normalized_name_count"],
        molecule_family_count=len(set(roots.values())),
        parent_link_count=sum(bool(row.get("parentId")) for row in molecule_rows.values()),
        dangling_parent_link_count=sum(
            bool(row.get("parentId")) and row["parentId"] not in molecule_rows
            for row in molecule_rows.values()
        ),
        hierarchy_cycle_count=metadata["cycle_count"],
        unresolved_trial_count=len(records),
        therapeutic_unresolved_trial_count=therapeutic_count,
        resolution_status_counts=dict(sorted(statuses.items())),
        exact_name_matched_trial_count=exact_matched,
        exact_name_match_coverage_of_therapeutic_unresolved=(
            exact_matched / therapeutic_count if therapeutic_count else 0.0
        ),
        single_family_nonambiguous_trial_count=sum(
            row["candidate_molecule_family_count"] == 1 for row in nonambiguous
        ),
        multi_family_nonambiguous_trial_count=sum(
            row["candidate_molecule_family_count"] > 1 for row in nonambiguous
        ),
        ambiguous_name_trial_count=statuses[
            "ambiguous_exact_name_to_multiple_families"
        ],
        target_assertion_gap_count=exact_matched,
        engineering_gate_passed=(
            metadata["dictionary_capture"]["complete_for_query"]
            and len(molecule_rows) == 18119
            and len(records) == 21694
            and sum(statuses.values()) == len(records)
            and metadata["cycle_count"] == 0
        ),
        blocking_limitations=[
            "Exact normalized names resolve identity candidates, not source-asserted trial-drug mappings.",
            "A unique molecule family does not provide a trial-specific target assertion.",
            "Multiple nonambiguous families may represent a legitimate combination trial rather than identity ambiguity.",
            "Thirty-one source parent links point outside the captured molecule table and remain explicitly dangling.",
            "Open Targets 25.09 identity is post-cutoff enrichment and remains forbidden as a temporal model feature.",
        ],
    )


def render_drug_identity_report(snapshot: DrugIdentitySnapshot) -> str:
    q = snapshot.quality
    lines = [
        "# TargetIdeator P5.5 versioned drug identity resolution",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Full dictionary rows: {q.full_dictionary_row_count}",
        f"- Normalized dictionary names: {q.normalized_dictionary_name_count}",
        f"- Molecule families: {q.molecule_family_count}",
        f"- Unresolved trials audited: {q.unresolved_trial_count}",
        f"- Exact-name matched trials: {q.exact_name_matched_trial_count}",
        f"- Target assertion gaps after identity match: {q.target_assertion_gap_count}",
        "",
        "## Resolution status",
        "",
    ]
    lines.extend(
        f"- `{status}`: {count}"
        for status, count in q.resolution_status_counts.items()
    )
    lines.extend(["", "## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in q.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def write_drug_identity_artifacts(
    output_dir: Path, dictionary_path: Path | None = None
) -> tuple[DrugIdentitySnapshot, DrugIdentityManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = dictionary_path or default_full_drug_dictionary_raw_path()
    records, metadata = build_drug_identity_records(source)
    resolution_path = output_dir / "p5_5_drug_identity_resolutions.jsonl.gz"
    _write_jsonl_gzip(resolution_path, records)
    quality = _quality(records, metadata)
    snapshot = DrugIdentitySnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        resolution_path=resolution_path.name,
        resolution_sha256=file_sha256(resolution_path),
        quality=quality,
        warning=(
            "IDENTITY-CANDIDATE AUDIT ONLY. Exact names and molecule families never "
            "supply a missing trial-specific target assertion."
        ),
    )
    snapshot_path = output_dir / "p5_5_drug_identity_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_5_drug_identity_report.md").write_text(
        render_drug_identity_report(snapshot), encoding="utf-8"
    )
    audit_store = load_default_mapping_audit_store()
    audit_path = artifact_path(audit_store.root, audit_store.manifest.triage_path)
    source_checksums = {
        source.name: file_sha256(source),
        audit_path.name: file_sha256(audit_path),
        default_mapping_audit_manifest_path().name: file_sha256(
            default_mapping_audit_manifest_path()
        ),
    }
    manifest = DrugIdentityManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=source_checksums,
        resolution_path=resolution_path.name,
        resolution_sha256=file_sha256(resolution_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
        resolution_record_count=len(records),
    )
    write_json(
        output_dir / "p5_5_drug_identity_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class DrugIdentityStore:
    def __init__(
        self, snapshot: DrugIdentitySnapshot, manifest: DrugIdentityManifest, root: Path
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "DrugIdentityStore":
        return cls(
            DrugIdentitySnapshot.model_validate(_load_json(snapshot_path)),
            DrugIdentityManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def sample(self, limit: int = 20, status: str | None = None) -> list[dict]:
        result = []
        with gzip.open(
            artifact_path(self.root, self.manifest.resolution_path), "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if status is None or row["resolution_status"] == status:
                    result.append(row)
                    if len(result) >= limit:
                        break
        return result

    def trial(self, nct_id: str) -> dict | None:
        with gzip.open(
            artifact_path(self.root, self.manifest.resolution_path), "rt", encoding="utf-8"
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if row["nct_id"] == nct_id:
                    return row
        return None

    def quality_report(self) -> dict:
        audit_store = load_default_mapping_audit_store()
        audit_path = artifact_path(audit_store.root, audit_store.manifest.triage_path)
        expected = {
            default_full_drug_dictionary_raw_path().name: file_sha256(
                default_full_drug_dictionary_raw_path()
            ),
            audit_path.name: file_sha256(audit_path),
            default_mapping_audit_manifest_path().name: file_sha256(
                default_mapping_audit_manifest_path()
            ),
        }
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.resolution_path))
                == self.manifest.resolution_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_drug_identity_store() -> DrugIdentityStore:
    return DrugIdentityStore.load(
        default_drug_identity_snapshot_path(), default_drug_identity_manifest_path()
    )
