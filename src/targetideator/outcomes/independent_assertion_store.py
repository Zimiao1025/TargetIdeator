"""Build independent DrugCentral corroboration for source-asserted mappings."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.outcomes.assertion_history_store import (
    default_assertion_history_manifest_path,
    load_default_assertion_history_store,
)
from targetideator.outcomes.identity_store import _read_gzip_json, _write_jsonl_gzip
from targetideator.outcomes.independent_assertion_models import (
    IndependentAssertionManifest,
    IndependentAssertionQuality,
    IndependentAssertionSnapshot,
)

BUILDER_VERSION = "p5.7-independent-drugcentral-corroboration-v1"
SNAPSHOT_ID = "ti:independent-corroboration:drugcentral-2027-v1"
CREATED_AT = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)
EXCLUDED_ASSERTION_SOURCES = {"CHEMBL", "UNKNOWN"}


def default_independent_assertion_raw_path() -> Path:
    return fixture_path("drugcentral_2027_independent_assertions_raw.json.gz")


def default_independent_assertion_snapshot_path() -> Path:
    return fixture_path("p5_7_independent_assertion_snapshot.json")


def default_independent_assertion_manifest_path() -> Path:
    return fixture_path("p5_7_independent_assertion_manifest.json")


def _assertion_sources(row: dict) -> set[str]:
    return {
        value.strip().upper()
        for value in (row.get("ACT_SOURCE"), row.get("MOA_SOURCE"))
        if value and value.strip()
    }


def build_independent_assertion_records(
    raw_path: Path | None = None,
) -> tuple[list[dict], list[dict], dict]:
    capture = _read_gzip_json(raw_path or default_independent_assertion_raw_path())
    if not capture["complete_for_query"]:
        raise ValueError("incomplete DrugCentral independent-source capture")
    structures = {
        row["structure_id"]: row for row in capture["structures"]
    }
    drug_index: dict[str, set[str]] = defaultdict(set)
    for row in capture["drug_crosswalk"]:
        drug_index[row["inchi_key"]].add(row["drug_chembl_id"])
    target_index: dict[str, set[str]] = defaultdict(set)
    for row in capture["target_crosswalk"]:
        target_index[row["uniprot_swissprot_accession"]].add(
            row["target_ensembl_id"]
        )

    rejection_reasons = Counter()
    human_count = 0
    independently_sourced_count = 0
    mapped_evidence = []
    for row in capture["interactions"]:
        if row["ORGANISM"] != "Homo sapiens":
            continue
        human_count += 1
        independent_sources = sorted(
            _assertion_sources(row) - EXCLUDED_ASSERTION_SOURCES
        )
        if not independent_sources:
            continue
        independently_sourced_count += 1
        structure = structures.get(int(row["STRUCT_ID"]))
        if structure is None:
            rejection_reasons["no_version_matched_drugcentral_structure"] += 1
            continue
        drug_ids = drug_index.get(structure["inchi_key"], set())
        target_ids = target_index.get(row["ACCESSION"], set())
        if not drug_ids:
            rejection_reasons["no_exact_full_inchikey_chembl_crosswalk"] += 1
            continue
        if len(drug_ids) > 1:
            rejection_reasons["ambiguous_exact_full_inchikey_chembl_crosswalk"] += 1
            continue
        if not target_ids:
            rejection_reasons["no_exact_swissprot_ensembl_crosswalk"] += 1
            continue
        if len(target_ids) > 1:
            rejection_reasons["ambiguous_exact_swissprot_ensembl_crosswalk"] += 1
            continue
        source_row_sha256 = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
        locator = (
            capture["independent_source"]["interaction_archive"]["sha256"]
            + f"#tsv-row={row['source_row_number']}"
        )
        mapped_evidence.append(
            {
                "id": stable_id("drugcentral-source-row", locator),
                "source_record_locator": locator,
                "source_row_sha256": source_row_sha256,
                "drugcentral_structure_id": int(row["STRUCT_ID"]),
                "drugcentral_drug_name": row["DRUG_NAME"],
                "drugcentral_target_accession": row["ACCESSION"],
                "drugcentral_target_name": row["TARGET_NAME"],
                "drugcentral_gene_symbol": row["GENE"],
                "drug_chembl_id": next(iter(drug_ids)),
                "target_ensembl_id": next(iter(target_ids)),
                "drug_identity_method": "exact_full_inchikey_unique_crosswalk",
                "target_identity_method": "exact_uniprot_swissprot_unique_crosswalk",
                "independent_assertion_sources": independent_sources,
                "activity_source": row.get("ACT_SOURCE") or None,
                "moa_source": row.get("MOA_SOURCE") or None,
                "activity_type": row.get("ACT_TYPE") or None,
                "activity_value": row.get("ACT_VALUE") or None,
                "activity_unit": row.get("ACT_UNIT") or None,
                "action_type": row.get("ACTION_TYPE") or None,
                "moa_flag": row.get("MOA") or None,
                "activity_source_url": row.get("ACT_SOURCE_URL") or None,
                "moa_source_url": row.get("MOA_SOURCE_URL") or None,
                "organism": row["ORGANISM"],
                "name_matching_used": False,
                "linkage_asserted_by_drugcentral": True,
            }
        )

    evidence_by_pair: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for evidence in mapped_evidence:
        evidence_by_pair[
            (evidence["drug_chembl_id"], evidence["target_ensembl_id"])
        ].append(evidence)
    independent_pairs = []
    for (drug_id, target_id), evidence_rows in sorted(evidence_by_pair.items()):
        pair_id = stable_id("independent-drug-target", f"{drug_id}-{target_id}")
        independent_pairs.append(
            {
                "id": pair_id,
                "drug_chembl_id": drug_id,
                "target_ensembl_id": target_id,
                "asserting_source": "DrugCentral",
                "source_release": capture["independent_source"]["release"],
                "source_release_date": capture["independent_source"]["release_date"],
                "drug_identity_method": "exact_full_inchikey_unique_crosswalk",
                "target_identity_method": "exact_uniprot_swissprot_unique_crosswalk",
                "source_evidence_ids": sorted(row["id"] for row in evidence_rows),
                "source_record_locators": sorted(
                    row["source_record_locator"] for row in evidence_rows
                ),
                "independent_assertion_sources": sorted(
                    {
                        source
                        for row in evidence_rows
                        for source in row["independent_assertion_sources"]
                    }
                ),
                "action_types": sorted(
                    {row["action_type"] for row in evidence_rows if row["action_type"]}
                ),
                "evidence_row_count": len(evidence_rows),
                "source_asserts_trial_linkage": False,
                "source_asserts_drug_target_linkage": True,
                "name_matching_used": False,
                "temporal_model_feature_use_allowed": False,
            }
        )

    pair_lookup = {
        (row["drug_chembl_id"], row["target_ensembl_id"]): row
        for row in independent_pairs
    }
    history_store = load_default_assertion_history_store()
    source_assertions = history_store.sample_assertions(
        history_store.manifest.assertion_record_count
    )
    current_assertions = [
        row for row in source_assertions if "25.09" in row["release_memberships"]
    ]
    corroborations = []
    trial_statuses: dict[str, set[str]] = defaultdict(set)
    for assertion in current_assertions:
        pair = pair_lookup.get(
            (assertion["drug_chembl_id"], assertion["target_ensembl_id"])
        )
        status = (
            "cross_source_drug_target_supported"
            if pair
            else "opentargets_chembl_only"
        )
        trial_statuses[assertion["nct_id"]].add(status)
        corroborations.append(
            {
                "id": stable_id("cross-source-corroboration", assertion["id"]),
                "source_assertion_id": assertion["id"],
                "nct_id": assertion["nct_id"],
                "drug_chembl_id": assertion["drug_chembl_id"],
                "target_ensembl_id": assertion["target_ensembl_id"],
                "corroboration_status": status,
                "independent_pair_id": pair["id"] if pair else None,
                "independent_source": "DrugCentral" if pair else None,
                "independent_source_evidence_count": (
                    pair["evidence_row_count"] if pair else 0
                ),
                "independent_assertion_sources": (
                    pair["independent_assertion_sources"] if pair else []
                ),
                "trial_specific_source_assertion_count": 1,
                "drug_target_source_count": 2 if pair else 1,
                "independent_source_is_trial_specific": False,
                "cross_source_support_scope": (
                    "drug_target_only_not_trial_linkage" if pair else "not_available"
                ),
                "trial_mapping_status_changed": False,
                "name_matching_used": False,
                "temporal_model_feature_use_allowed": False,
            }
        )
    metadata = {
        "capture": capture,
        "mapped_evidence_count": len(mapped_evidence),
        "human_count": human_count,
        "independently_sourced_count": independently_sourced_count,
        "rejection_reasons": rejection_reasons,
        "trial_statuses": trial_statuses,
    }
    return independent_pairs, corroborations, metadata


def _quality(
    pairs: list[dict], corroborations: list[dict], metadata: dict
) -> IndependentAssertionQuality:
    statuses = Counter(row["corroboration_status"] for row in corroborations)
    current_pairs = {
        (row["drug_chembl_id"], row["target_ensembl_id"])
        for row in corroborations
    }
    cross_pairs = {
        (row["drug_chembl_id"], row["target_ensembl_id"])
        for row in corroborations
        if row["corroboration_status"] == "cross_source_drug_target_supported"
    }
    trial_statuses = metadata["trial_statuses"]
    cross_status = "cross_source_drug_target_supported"
    only_status = "opentargets_chembl_only"
    capture = metadata["capture"]
    return IndependentAssertionQuality(
        source_admission_passed=(
            capture["complete_for_query"]
            and capture["independent_source"]["release"] == "2027"
            and bool(capture["independent_source"]["interaction_archive"]["sha256"])
            and bool(capture["independent_source"]["structure_archive"]["sha256"])
        ),
        raw_interaction_row_count=capture["interaction_row_count"],
        human_interaction_row_count=metadata["human_count"],
        independently_sourced_human_row_count=metadata[
            "independently_sourced_count"
        ],
        exact_crosswalk_evidence_row_count=metadata["mapped_evidence_count"],
        crosswalk_rejection_reason_counts=dict(
            sorted(metadata["rejection_reasons"].items())
        ),
        independent_drug_target_pair_count=len(pairs),
        independent_drug_count=len({row["drug_chembl_id"] for row in pairs}),
        independent_target_count=len({row["target_ensembl_id"] for row in pairs}),
        current_source_assertion_count=len(corroborations),
        current_source_pair_count=len(current_pairs),
        cross_source_supported_assertion_count=statuses[cross_status],
        single_source_assertion_count=statuses[only_status],
        cross_source_supported_pair_count=len(cross_pairs),
        single_source_pair_count=len(current_pairs - cross_pairs),
        mapped_nct_count=len(trial_statuses),
        cross_source_supported_nct_count=sum(
            cross_status in values for values in trial_statuses.values()
        ),
        all_assertions_cross_source_nct_count=sum(
            values == {cross_status} for values in trial_statuses.values()
        ),
        mixed_support_nct_count=sum(
            values == {cross_status, only_status} for values in trial_statuses.values()
        ),
        single_source_only_nct_count=sum(
            values == {only_status} for values in trial_statuses.values()
        ),
        remaining_unresolved_nct_count=21694,
        engineering_gate_passed=(
            capture["complete_for_query"]
            and len(pairs) > 6000
            and len(corroborations) == 86154
            and statuses[cross_status] > 10000
            and all(not row["trial_mapping_status_changed"] for row in corroborations)
        ),
        blocking_limitations=[
            "DrugCentral corroborates drug-target linkage, not the trial-specific drug-target assertion.",
            "Cross-source support does not establish target causality, efficacy, direction, or safety in a trial.",
            "Only exact unique InChIKey and Swiss-Prot crosswalks are admitted; unmatched or ambiguous identities are excluded.",
            "DrugCentral 2027 and identity crosswalk release 25.09 are post-baseline enrichment and forbidden as temporal features.",
            "No P5.5 identity candidate is promoted to a trial-target mapping; unresolved coverage is unchanged.",
        ],
    )


def render_independent_assertion_report(
    snapshot: IndependentAssertionSnapshot,
) -> str:
    q = snapshot.quality
    return "\n".join(
        [
            "# TargetIdeator P5.7 independent DrugCentral corroboration",
            "",
            f"> {snapshot.warning}",
            "",
            f"- Independent drug-target pairs: {q.independent_drug_target_pair_count}",
            f"- Current source assertions: {q.current_source_assertion_count}",
            f"- Cross-source supported assertions: {q.cross_source_supported_assertion_count}",
            f"- Open Targets/ChEMBL-only assertions: {q.single_source_assertion_count}",
            f"- Cross-source supported NCT: {q.cross_source_supported_nct_count}",
            f"- Newly mapped NCT: {q.newly_mapped_nct_count}",
            "",
            "## Blocking limitations",
            "",
            *(f"- {item}" for item in q.blocking_limitations),
            "",
        ]
    )


def write_independent_assertion_artifacts(
    output_dir: Path, raw_path: Path | None = None
) -> tuple[IndependentAssertionSnapshot, IndependentAssertionManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = raw_path or default_independent_assertion_raw_path()
    pairs, corroborations, metadata = build_independent_assertion_records(source)
    pair_path = output_dir / "p5_7_independent_drug_target_pairs.jsonl.gz"
    corroboration_path = output_dir / "p5_7_cross_source_corroborations.jsonl.gz"
    _write_jsonl_gzip(pair_path, pairs)
    _write_jsonl_gzip(corroboration_path, corroborations)
    snapshot = IndependentAssertionSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        independent_pair_path=pair_path.name,
        independent_pair_sha256=file_sha256(pair_path),
        corroboration_path=corroboration_path.name,
        corroboration_sha256=file_sha256(corroboration_path),
        quality=_quality(pairs, corroborations, metadata),
        warning=(
            "DRUG-TARGET CORROBORATION ONLY. DrugCentral does not independently "
            "assert the trial linkage and cannot create a new trial-target mapping."
        ),
    )
    snapshot_path = output_dir / "p5_7_independent_assertion_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_7_independent_assertion_report.md").write_text(
        render_independent_assertion_report(snapshot), encoding="utf-8"
    )
    history_store = load_default_assertion_history_store()
    history_path = artifact_path(history_store.root, history_store.manifest.assertion_path)
    source_checksums = {
        source.name: file_sha256(source),
        history_path.name: file_sha256(history_path),
        default_assertion_history_manifest_path().name: file_sha256(
            default_assertion_history_manifest_path()
        ),
    }
    manifest = IndependentAssertionManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=source_checksums,
        independent_pair_path=pair_path.name,
        independent_pair_sha256=file_sha256(pair_path),
        independent_pair_record_count=len(pairs),
        corroboration_path=corroboration_path.name,
        corroboration_sha256=file_sha256(corroboration_path),
        corroboration_record_count=len(corroborations),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "p5_7_independent_assertion_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class IndependentAssertionStore:
    def __init__(
        self,
        snapshot: IndependentAssertionSnapshot,
        manifest: IndependentAssertionManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "IndependentAssertionStore":
        return cls(
            IndependentAssertionSnapshot.model_validate(_load_json(snapshot_path)),
            IndependentAssertionManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, path: str, limit: int, status: str | None = None) -> list[dict]:
        result = []
        with gzip.open(artifact_path(self.root, path), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if status is None or row.get("corroboration_status") == status:
                    result.append(row)
                    if len(result) >= limit:
                        break
        return result

    def sample_pairs(self, limit: int = 20) -> list[dict]:
        return self._sample(self.manifest.independent_pair_path, limit)

    def sample_corroborations(
        self, limit: int = 20, status: str | None = None
    ) -> list[dict]:
        return self._sample(self.manifest.corroboration_path, limit, status)

    def trial(self, nct_id: str) -> dict:
        rows = []
        with gzip.open(
            artifact_path(self.root, self.manifest.corroboration_path),
            "rt",
            encoding="utf-8",
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if row["nct_id"] == nct_id:
                    rows.append(row)
        return {"nct_id": nct_id, "corroborations": rows}

    def quality_report(self) -> dict:
        history_store = load_default_assertion_history_store()
        history_path = artifact_path(
            history_store.root, history_store.manifest.assertion_path
        )
        expected = {
            default_independent_assertion_raw_path().name: file_sha256(
                default_independent_assertion_raw_path()
            ),
            history_path.name: file_sha256(history_path),
            default_assertion_history_manifest_path().name: file_sha256(
                default_assertion_history_manifest_path()
            ),
        }
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.independent_pair_path))
                == self.manifest.independent_pair_sha256
                and file_sha256(artifact_path(self.root, self.manifest.corroboration_path))
                == self.manifest.corroboration_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_independent_assertion_store() -> IndependentAssertionStore:
    return IndependentAssertionStore.load(
        default_independent_assertion_snapshot_path(),
        default_independent_assertion_manifest_path(),
    )
