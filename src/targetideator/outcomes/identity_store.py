"""Build auditable trial→drug→target mappings and enriched outcome provenance."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from targetideator.data import artifact_path, fixture_path
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.ingestion.identity_sources import THERAPEUTIC_INTERVENTION_TYPES
from targetideator.io import write_json
from targetideator.outcomes.broad_store import (
    default_broad_manifest_path,
    load_default_broad_outcome_store,
)
from targetideator.outcomes.identity_models import (
    IdentityManifest,
    IdentityQuality,
    IdentitySnapshot,
    MappingCoverage,
)

BUILDER_VERSION = "p5.3-auditable-trial-drug-target-v1"
SNAPSHOT_ID = "ti:identity-snapshot:trial-drug-target-ot25-09-v1"
CREATED_AT = datetime(2026, 11, 2, 23, 45, tzinfo=timezone.utc)
CLASSIFIER_VERSION = "p5-explicit-registry-stop-reason-v2"
EXPLICIT_CAUSE_CATEGORIES = {
    "efficacy_termination",
    "safety_termination",
    "pk_termination",
    "strategy_termination",
}

_SAFETY_CUES = (
    "toxicity",
    "toxicities",
    "adverse event",
    "safety concern",
    "safety issue",
    "safety signal",
    "safety reason",
)
_EFFICACY_CUES = (
    "lack of efficacy",
    "lack of effectiveness",
    "futility",
    "did not show superiority",
    "unlikely to meet its primary endpoint",
    "efficacy/effectiveness reasons",
)
_PK_CUES = ("pharmacokinetic", "bioavailability", "insufficient exposure", "drug exposure")
_STRATEGY_CUES = (
    "business decision",
    "business reasons",
    "business objectives",
    "strategic consideration",
    "strategic decision",
    "strategy reasons",
    "commercial decision",
    "corporate priorities",
    "portfolio reprioritization",
    "no longer pursuing development",
)


def default_trial_mapping_raw_path() -> Path:
    return fixture_path("chembl_25_09_broad_trial_mapping_raw.json.gz")


def default_aact_intervention_raw_path() -> Path:
    return fixture_path("aact_broad_interventions_train_raw.json.gz")


def default_drug_dictionary_raw_path() -> Path:
    return fixture_path("opentargets_25_09_drug_dictionary_raw.json.gz")


def default_identity_snapshot_path() -> Path:
    return fixture_path("p5_3_identity_snapshot.json")


def default_identity_manifest_path() -> Path:
    return fixture_path("p5_3_identity_manifest.json")


def _read_gzip_json(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def _read_jsonl_gzip(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def _write_jsonl_gzip(path: Path, rows: list[dict]) -> None:
    with path.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            for row in rows:
                compressed.write(canonical_json_bytes(row) + b"\n")


def normalize_drug_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("®", " ").replace("™", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def _coverage(total: int, mapped: int) -> MappingCoverage:
    return MappingCoverage(
        total_count=total,
        mapped_count=mapped,
        coverage=mapped / total if total else 0.0,
    )


def _reason_trace(reason: str | None, rule_id: str) -> dict:
    text = (reason or "").casefold()
    safety_negated = bool(
        re.search(
            r"(?:(?:not|no|without|unrelated|neither|non[- ])[^.;]{0,60}safety|"
            r"safety[^.;]{0,35}(?:not\s+(?:a|the)\s+reason|did\s+not))",
            text,
        )
    )
    efficacy_negated = bool(
        re.search(
            r"(?:(?:not|no|without|unrelated|neither|non[- ])[^.;]{0,60}"
            r"(?:efficacy|therapeutic)|(?:efficacy|therapeutic)[^.;]{0,35}"
            r"(?:not\s+(?:a|the)\s+reason|did\s+not))",
            text,
        )
    )
    cues = sorted(
        {
            cue
            for cue in (*_SAFETY_CUES, *_EFFICACY_CUES, *_PK_CUES, *_STRATEGY_CUES)
            if cue in text
        }
    )
    return {
        "classifier_version": CLASSIFIER_VERSION,
        "classification_rule_id": rule_id,
        "reason_present": bool(reason),
        "reason_sha256": (
            hashlib.sha256(reason.encode("utf-8")).hexdigest() if reason else None
        ),
        "safety_negation_detected": safety_negated,
        "efficacy_negation_detected": efficacy_negated,
        "matched_lexical_cues": cues,
    }


def _build_aact_name_index(capture: dict) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    normalized: dict[str, set[str]] = defaultdict(set)
    raw_names: dict[str, list[str]] = defaultdict(list)
    for item in capture["interventions"]:
        if item["intervention_type"] not in THERAPEUTIC_INTERVENTION_TYPES:
            continue
        values = [item.get("name"), *(item.get("aliases") or [])]
        for value in values:
            name = normalize_drug_name(value)
            if name:
                normalized[item["nct_id"]].add(name)
                raw_names[item["nct_id"]].append(value)
    return normalized, {key: sorted(set(values)) for key, values in raw_names.items()}


def build_identity_records(
    mapping_raw_path: Path | None = None,
    intervention_raw_path: Path | None = None,
    drug_dictionary_raw_path: Path | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    mapping_capture = _read_gzip_json(mapping_raw_path or default_trial_mapping_raw_path())
    intervention_capture = _read_gzip_json(
        intervention_raw_path or default_aact_intervention_raw_path()
    )
    drug_dictionary_capture = _read_gzip_json(
        drug_dictionary_raw_path or default_drug_dictionary_raw_path()
    )
    mapping_release_date = mapping_capture["release_date"]
    mapping_capture_row_count = len(mapping_capture["rows"])
    mapping_capture_complete = mapping_capture["complete_for_query"]
    intervention_capture_complete = intervention_capture["complete_for_query"]
    drug_dictionary_capture_complete = drug_dictionary_capture["complete_for_query"]
    drug_dictionary_row_count = len(drug_dictionary_capture["rows"])
    drug_dictionary_missing_id_count = len(drug_dictionary_capture["missing_drug_ids"])
    broad_store = load_default_broad_outcome_store()
    outcome_path = artifact_path(
        broad_store.root, broad_store.manifest.normalized_dataset_path
    )
    outcome_records = _read_jsonl_gzip(outcome_path)
    broad_nct_ids = {row["nct_id"] for row in outcome_records}
    aact_names, aact_raw_names = _build_aact_name_index(intervention_capture)
    drug_dictionary = {item["id"]: item for item in drug_dictionary_capture["rows"]}

    groups: dict[tuple[str, str, str], dict[str, set]] = {}
    invalid_source_rows = []
    for row in mapping_capture["rows"]:
        nct_id, drug_id, target_id = row.get("studyId"), row.get("drugId"), row.get("targetId")
        valid = bool(
            re.fullmatch(r"NCT\d{8}", nct_id or "")
            and re.fullmatch(r"CHEMBL\d+", drug_id or "")
            and re.fullmatch(r"ENSG\d{11}", target_id or "")
        )
        if not valid:
            invalid_source_rows.append(row)
            continue
        key = (nct_id, drug_id, target_id)
        group = groups.setdefault(
            key,
            {
                "evidence_ids": set(),
                "evidence_row_sha256s": set(),
                "drug_names": set(),
                "disease_ids": set(),
                "disease_names": set(),
                "clinical_statuses": set(),
                "study_stop_reasons": set(),
                "source_parquet_urls": set(),
                "source_urls": set(),
            },
        )
        group["evidence_ids"].add(row["id"])
        group["evidence_row_sha256s"].add(
            hashlib.sha256(canonical_json_bytes(row)).hexdigest()
        )
        if row.get("drugFromSource"):
            group["drug_names"].add(row["drugFromSource"])
        if row.get("diseaseId"):
            group["disease_ids"].add(row["diseaseId"])
        if row.get("diseaseFromSource"):
            group["disease_names"].add(row["diseaseFromSource"])
        if row.get("clinicalStatus"):
            group["clinical_statuses"].add(row["clinicalStatus"])
        if row.get("studyStopReason"):
            group["study_stop_reasons"].add(row["studyStopReason"])
        group["source_parquet_urls"].add(row["sourceParquetUrl"])
        for source in row.get("urls") or []:
            if isinstance(source, dict) and source.get("url"):
                group["source_urls"].add(source["url"])

    mappings = []
    mapping_ids_by_nct: dict[str, list[str]] = defaultdict(list)
    mappings_by_nct: dict[str, list[dict]] = defaultdict(list)
    for (nct_id, drug_id, target_id), group in sorted(groups.items()):
        dictionary_row = drug_dictionary.get(drug_id)
        dictionary_names = (
            [
                dictionary_row.get("name"),
                *(dictionary_row.get("tradeNames") or []),
                *(dictionary_row.get("synonyms") or []),
            ]
            if dictionary_row
            else []
        )
        raw_drug_names = sorted(
            {value for value in (*group["drug_names"], *dictionary_names) if value}
        )
        source_names = {
            normalized
            for value in raw_drug_names
            if (normalized := normalize_drug_name(value))
        }
        if nct_id not in aact_names:
            crosscheck_status = "not_available_outside_aact_train_capture"
            agreement = []
        elif not source_names:
            crosscheck_status = "source_drug_name_unavailable"
            agreement = []
        else:
            agreement = sorted(source_names & aact_names[nct_id])
            crosscheck_status = (
                "exact_normalized_agreement"
                if agreement
                else "no_exact_normalized_agreement"
            )
        mapping_id = stable_id(
            "trial-drug-target", f"ot25-09-{nct_id}-{drug_id}-{target_id}"
        )
        mapping = {
            "id": mapping_id,
            "nct_id": nct_id,
            "drug_chembl_id": drug_id,
            "target_ensembl_id": target_id,
            "mapping_assertion": "source_asserted_open_targets_chembl_evidence",
            "mapping_release": "25.09",
            "mapping_release_date": mapping_release_date,
            "temporal_use_allowed": False,
            "evidence_ids": sorted(group["evidence_ids"]),
            "evidence_row_sha256s": sorted(group["evidence_row_sha256s"]),
            "drug_names_from_evidence": sorted(group["drug_names"]),
            "drug_names_from_dictionary": sorted(
                {value for value in dictionary_names if value}
            ),
            "disease_ids": sorted(group["disease_ids"]),
            "disease_names": sorted(group["disease_names"]),
            "clinical_statuses": sorted(group["clinical_statuses"]),
            "study_stop_reasons": sorted(group["study_stop_reasons"]),
            "source_parquet_urls": sorted(group["source_parquet_urls"]),
            "source_urls": sorted(group["source_urls"]),
            "aact_name_crosscheck_status": crosscheck_status,
            "aact_exact_normalized_agreements": agreement,
            "aact_therapeutic_names": aact_raw_names.get(nct_id, []),
            "fuzzy_mapping_used": False,
        }
        mappings.append(mapping)
        mapping_ids_by_nct[nct_id].append(mapping_id)
        mappings_by_nct[nct_id].append(mapping)

    mapped_nct_ids = set(mapping_ids_by_nct)
    provenance = []
    for row in outcome_records:
        mapping_ids = sorted(mapping_ids_by_nct.get(row["nct_id"], []))
        nct_mappings = mappings_by_nct.get(row["nct_id"], [])
        provenance.append(
            {
                "id": stable_id("outcome-provenance", row["id"]),
                "outcome_record_id": row["id"],
                "nct_id": row["nct_id"],
                "split": row["split"],
                "baseline_snapshot": row["baseline_snapshot"],
                "outcome_snapshot": row["outcome_snapshot"],
                "outcome_category": row["outcome_category"],
                "outcome_status": row["outcome_status"],
                "why_stopped": row["why_stopped"],
                "label_efficacy": row["label_efficacy"],
                "label_safety": row["label_safety"],
                "label_pk": row["label_pk"],
                "label_strategy": row["label_strategy"],
                "baseline_raw_sha256": row["baseline_raw_sha256"],
                "outcome_raw_sha256": row["outcome_raw_sha256"],
                "classification_trace": _reason_trace(
                    row["why_stopped"], row["classification_rule_id"]
                ),
                "identity_mapping_status": (
                    "mapped_source_asserted" if mapping_ids else "unmapped"
                ),
                "mapping_ids": mapping_ids,
                "drug_chembl_ids": sorted(
                    {item["drug_chembl_id"] for item in nct_mappings}
                ),
                "drug_names": sorted(
                    {
                        name
                        for item in nct_mappings
                        for name in item["drug_names_from_dictionary"]
                    }
                ),
                "target_ensembl_ids": sorted(
                    {item["target_ensembl_id"] for item in nct_mappings}
                ),
                "mapping_release": "25.09" if mapping_ids else None,
                "mapping_used_as_model_feature": False,
            }
        )

    outcomes_by_nct: dict[str, dict[str, set]] = defaultdict(
        lambda: {"splits": set(), "categories": set()}
    )
    for row in outcome_records:
        outcomes_by_nct[row["nct_id"]]["splits"].add(row["split"])
        outcomes_by_nct[row["nct_id"]]["categories"].add(row["outcome_category"])
    unresolved = [
        {
            "id": stable_id("unresolved-trial-identity", nct_id),
            "nct_id": nct_id,
            "status": "unresolved_no_source_asserted_mapping",
            "reason": "no Open Targets 25.09 ChEMBL evidence row for this NCT",
            "observed_splits": sorted(outcomes_by_nct[nct_id]["splits"]),
            "observed_outcome_categories": sorted(
                outcomes_by_nct[nct_id]["categories"]
            ),
            "aact_train_therapeutic_names": aact_raw_names.get(nct_id, []),
            "fuzzy_mapping_attempted": False,
            "automatic_target_inference_allowed": False,
        }
        for nct_id in sorted(broad_nct_ids - mapped_nct_ids)
    ]
    unresolved.extend(
        {
            "id": stable_id("unresolved-source-evidence", row.get("id") or str(index)),
            "nct_id": row.get("studyId"),
            "status": "invalid_source_identity_fields",
            "reason": "source row lacks a valid NCT, ChEMBL drug, or Ensembl target identifier",
            "source_evidence_id": row.get("id"),
            "drug_id": row.get("drugId"),
            "target_id": row.get("targetId"),
            "fuzzy_mapping_attempted": False,
            "automatic_target_inference_allowed": False,
        }
        for index, row in enumerate(invalid_source_rows)
    )
    unresolved.sort(key=lambda item: (item.get("nct_id") or "", item["id"]))
    metadata = {
        "mapping_capture_row_count": mapping_capture_row_count,
        "mapping_capture_complete": mapping_capture_complete,
        "intervention_capture_complete": intervention_capture_complete,
        "drug_dictionary_capture_complete": drug_dictionary_capture_complete,
        "drug_dictionary_row_count": drug_dictionary_row_count,
        "drug_dictionary_missing_id_count": drug_dictionary_missing_id_count,
        "broad_nct_ids": broad_nct_ids,
        "invalid_source_rows": invalid_source_rows,
    }
    del mapping_capture, intervention_capture, drug_dictionary_capture
    del outcome_records, groups, drug_dictionary
    return mappings, provenance, unresolved, metadata


def _build_quality(
    mappings: list[dict], provenance: list[dict], unresolved: list[dict], metadata: dict
) -> IdentityQuality:
    broad_nct_ids = metadata["broad_nct_ids"]
    mapped_nct_ids = {item["nct_id"] for item in mappings}
    source_count = metadata["mapping_capture_row_count"]
    invalid_count = len(metadata["invalid_source_rows"])
    mappings_by_nct: dict[str, list[dict]] = defaultdict(list)
    for item in mappings:
        mappings_by_nct[item["nct_id"]].append(item)
    category_total = Counter(item["outcome_category"] for item in provenance)
    category_mapped = Counter(
        item["outcome_category"]
        for item in provenance
        if item["identity_mapping_status"] == "mapped_source_asserted"
    )
    explicit = [
        item for item in provenance if item["outcome_category"] in EXPLICIT_CAUSE_CATEGORIES
    ]
    crosscheck = Counter(item["aact_name_crosscheck_status"] for item in mappings)
    return IdentityQuality(
        broad_unique_nct_count=len(broad_nct_ids),
        source_evidence_row_count=source_count,
        valid_source_evidence_row_count=source_count - invalid_count,
        invalid_source_evidence_row_count=invalid_count,
        drug_dictionary_row_count=metadata["drug_dictionary_row_count"],
        drug_dictionary_missing_id_count=metadata[
            "drug_dictionary_missing_id_count"
        ],
        unique_trial_drug_target_mapping_count=len(mappings),
        mapped_unique_nct_count=len(mapped_nct_ids),
        unmapped_unique_nct_count=len(broad_nct_ids - mapped_nct_ids),
        unique_nct_mapping_coverage=len(mapped_nct_ids) / len(broad_nct_ids),
        multi_drug_trial_count=sum(
            len({item["drug_chembl_id"] for item in values}) > 1
            for values in mappings_by_nct.values()
        ),
        multi_target_trial_count=sum(
            len({item["target_ensembl_id"] for item in values}) > 1
            for values in mappings_by_nct.values()
        ),
        outcome_provenance_record_count=len(provenance),
        outcome_record_mapping_coverage=_coverage(
            len(provenance),
            sum(
                item["identity_mapping_status"] == "mapped_source_asserted"
                for item in provenance
            ),
        ),
        mapping_coverage_by_outcome_category={
            category: _coverage(total, category_mapped[category])
            for category, total in sorted(category_total.items())
        },
        explicit_cause_event_mapping_coverage=_coverage(
            len(explicit),
            sum(
                item["identity_mapping_status"] == "mapped_source_asserted"
                for item in explicit
            ),
        ),
        aact_name_crosscheck_available_mapping_count=(
            crosscheck["exact_normalized_agreement"]
            + crosscheck["no_exact_normalized_agreement"]
        ),
        aact_name_exact_agreement_count=crosscheck["exact_normalized_agreement"],
        aact_name_no_exact_agreement_count=crosscheck[
            "no_exact_normalized_agreement"
        ],
        aact_name_source_unavailable_mapping_count=crosscheck[
            "source_drug_name_unavailable"
        ],
        aact_name_crosscheck_unavailable_mapping_count=crosscheck[
            "not_available_outside_aact_train_capture"
        ],
        classification_trace_coverage=(
            sum(bool(item["classification_trace"]["classifier_version"]) for item in provenance)
            / len(provenance)
        ),
        source_complete_for_query=(
            metadata["mapping_capture_complete"]
            and metadata["intervention_capture_complete"]
            and metadata["drug_dictionary_capture_complete"]
        ),
        engineering_gate_passed=(
            metadata["mapping_capture_complete"]
            and metadata["intervention_capture_complete"]
            and metadata["drug_dictionary_capture_complete"]
            and len(provenance) == 71947
            and len(mapped_nct_ids) > 10_000
        ),
        blocking_limitations=[
            "Only source-asserted Open Targets ChEMBL evidence mappings are accepted; unmapped trials remain unresolved.",
            "The 25.09 mapping release is identity/provenance enrichment and is forbidden as a pre-cutoff model feature.",
            "AACT exact-name crosscheck is available only for the 2023-03 baseline capture and is an audit, not mapping evidence.",
            "One trial may legitimately map to multiple drugs and targets; no single-target collapse is performed.",
            "Mapping coverage is insufficient for an unbiased target-level outcome benchmark.",
        ],
    )


def render_identity_report(snapshot: IdentitySnapshot) -> str:
    quality = snapshot.quality
    lines = [
        "# TargetIdeator P5.3 trial→drug→target identity and outcome provenance",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Broad unique NCT: {quality.broad_unique_nct_count}",
        f"- Source evidence rows: {quality.source_evidence_row_count}",
        f"- Unique trial-drug-target mappings: {quality.unique_trial_drug_target_mapping_count}",
        f"- Mapped unique NCT: {quality.mapped_unique_nct_count}",
        f"- Unique-NCT mapping coverage: {quality.unique_nct_mapping_coverage:.4f}",
        f"- Explicit cause-event mapping coverage: {quality.explicit_cause_event_mapping_coverage.coverage:.4f}",
        f"- AACT exact-name agreements: {quality.aact_name_exact_agreement_count}/"
        f"{quality.aact_name_crosscheck_available_mapping_count}",
        "",
        "## Coverage by outcome category",
        "",
    ]
    lines.extend(
        f"- `{category}`: {coverage.mapped_count}/{coverage.total_count} "
        f"({coverage.coverage:.3f})"
        for category, coverage in quality.mapping_coverage_by_outcome_category.items()
    )
    lines.extend(["", "## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in quality.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def write_identity_artifacts(
    output_dir: Path,
    mapping_raw_path: Path | None = None,
    intervention_raw_path: Path | None = None,
    drug_dictionary_raw_path: Path | None = None,
) -> tuple[IdentitySnapshot, IdentityManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_source = mapping_raw_path or default_trial_mapping_raw_path()
    intervention_source = intervention_raw_path or default_aact_intervention_raw_path()
    drug_dictionary_source = (
        drug_dictionary_raw_path or default_drug_dictionary_raw_path()
    )
    mappings, provenance, unresolved, metadata = build_identity_records(
        mapping_source, intervention_source, drug_dictionary_source
    )
    mapping_path = output_dir / "p5_3_trial_drug_target_mappings.jsonl.gz"
    provenance_path = output_dir / "p5_3_outcome_provenance.jsonl.gz"
    unresolved_path = output_dir / "p5_3_unresolved_trials.jsonl.gz"
    _write_jsonl_gzip(mapping_path, mappings)
    _write_jsonl_gzip(provenance_path, provenance)
    _write_jsonl_gzip(unresolved_path, unresolved)
    quality = _build_quality(mappings, provenance, unresolved, metadata)
    snapshot = IdentitySnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        mapping_path=mapping_path.name,
        mapping_sha256=file_sha256(mapping_path),
        provenance_path=provenance_path.name,
        provenance_sha256=file_sha256(provenance_path),
        unresolved_path=unresolved_path.name,
        unresolved_sha256=file_sha256(unresolved_path),
        quality=quality,
        warning=(
            "DEVELOPMENT-ONLY IDENTITY ENRICHMENT. Mapping is source asserted and auditable, "
            "but incomplete and forbidden as a temporal model feature in the current benchmark."
        ),
    )
    snapshot_path = output_dir / "p5_3_identity_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_3_identity_report.md").write_text(
        render_identity_report(snapshot), encoding="utf-8"
    )
    broad_store = load_default_broad_outcome_store()
    broad_dataset_path = artifact_path(
        broad_store.root, broad_store.manifest.normalized_dataset_path
    )
    source_checksums = {
        mapping_source.name: file_sha256(mapping_source),
        intervention_source.name: file_sha256(intervention_source),
        drug_dictionary_source.name: file_sha256(drug_dictionary_source),
        broad_dataset_path.name: file_sha256(broad_dataset_path),
        default_broad_manifest_path().name: file_sha256(default_broad_manifest_path()),
    }
    manifest = IdentityManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=source_checksums,
        mapping_path=mapping_path.name,
        mapping_sha256=file_sha256(mapping_path),
        provenance_path=provenance_path.name,
        provenance_sha256=file_sha256(provenance_path),
        unresolved_path=unresolved_path.name,
        unresolved_sha256=file_sha256(unresolved_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
        mapping_count=len(mappings),
        provenance_count=len(provenance),
        unresolved_count=len(unresolved),
    )
    write_json(output_dir / "p5_3_identity_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class IdentityStore:
    def __init__(self, snapshot: IdentitySnapshot, manifest: IdentityManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "IdentityStore":
        return cls(
            IdentitySnapshot.model_validate(_load_json(snapshot_path)),
            IdentityManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, filename: str, limit: int) -> list[dict]:
        result = []
        with gzip.open(artifact_path(self.root, filename), "rt", encoding="utf-8") as stream:
            for line in stream:
                result.append(json.loads(line))
                if len(result) >= limit:
                    break
        return result

    def _for_nct(self, filename: str, nct_id: str) -> list[dict]:
        result = []
        with gzip.open(artifact_path(self.root, filename), "rt", encoding="utf-8") as stream:
            for line in stream:
                item = json.loads(line)
                if item.get("nct_id") == nct_id:
                    result.append(item)
        return result

    def sample_mappings(self, limit: int = 20) -> list[dict]:
        return self._sample(self.manifest.mapping_path, limit)

    def sample_provenance(self, limit: int = 20) -> list[dict]:
        return self._sample(self.manifest.provenance_path, limit)

    def sample_unresolved(self, limit: int = 20) -> list[dict]:
        return self._sample(self.manifest.unresolved_path, limit)

    def trial_lineage(self, nct_id: str) -> dict:
        return {
            "nct_id": nct_id,
            "mappings": self._for_nct(self.manifest.mapping_path, nct_id),
            "outcome_provenance": self._for_nct(
                self.manifest.provenance_path, nct_id
            ),
            "unresolved": self._for_nct(self.manifest.unresolved_path, nct_id),
        }

    def quality_report(self) -> dict:
        broad_store = load_default_broad_outcome_store()
        broad_dataset_path = artifact_path(
            broad_store.root, broad_store.manifest.normalized_dataset_path
        )
        expected_sources = {
            default_trial_mapping_raw_path().name: file_sha256(
                default_trial_mapping_raw_path()
            ),
            default_aact_intervention_raw_path().name: file_sha256(
                default_aact_intervention_raw_path()
            ),
            default_drug_dictionary_raw_path().name: file_sha256(
                default_drug_dictionary_raw_path()
            ),
            broad_dataset_path.name: file_sha256(broad_dataset_path),
            default_broad_manifest_path().name: file_sha256(default_broad_manifest_path()),
        }
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.mapping_path))
                == self.manifest.mapping_sha256
                and file_sha256(artifact_path(self.root, self.manifest.provenance_path))
                == self.manifest.provenance_sha256
                and file_sha256(artifact_path(self.root, self.manifest.unresolved_path))
                == self.manifest.unresolved_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected_sources == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_identity_store() -> IdentityStore:
    return IdentityStore.load(
        default_identity_snapshot_path(), default_identity_manifest_path()
    )
