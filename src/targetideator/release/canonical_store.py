"""R2.7 field-level canonical-content acceptance for the frozen R2.6 replay."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.outcomes.identity_store import _write_jsonl_gzip
from targetideator.release.canonical_models import (
    CanonicalAcceptanceManifest,
    CanonicalAcceptanceQuality,
    CanonicalAcceptanceRecord,
    CanonicalAcceptanceSnapshot,
    CanonicalFieldRule,
)
from targetideator.release.replay_hardening_store import ReplayHardeningStore

BUILDER_VERSION = "r2.7-canonical-content-v1"
CONTRACT_VERSION = "canonical-content-v1"
APPROVED_CHANGED_PATH_MAP_SHA256 = (
    "686613f082d6b553909f9ae277c4726e5d86d83df7cfb8aab8539241024d57c5"
)
HEX_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")
ARRAY_INDEX = re.compile(r"\[\d+\]")
MISSING = object()

CAPTURE_TIMESTAMP_ARTIFACTS = {
    "opentargets_25_03_associations_raw.json",
    "opentargets_25_09_associations_raw.json",
    "aact_broad_outcomes_test_raw.json.gz",
    "aact_broad_outcomes_train_raw.json.gz",
    "aact_broad_outcomes_validation_raw.json.gz",
    "aact_20250301_trials_raw.json",
    "aact_20250901_trials_raw.json",
    "chembl_25_03_evidence_raw.json",
    "chembl_25_09_evidence_raw.json",
    "chembl_molecules_current_raw.json",
    "ctgov_trials_current_raw.json",
    "opentargets_25_09_full_drug_dictionary_raw.json.gz",
    "europepmc_literature_raw.json",
    "opentargets_25_09_drug_dictionary_raw.json.gz",
    "opentargets_25_03_25_09_historical_snapshot.json",
    "clinical_history_snapshot.json",
}
RETRY_COUNTER_ARTIFACTS = {
    "chembl_25_03_evidence_raw.json",
    "chembl_25_09_evidence_raw.json",
    "opentargets_25_09_full_drug_dictionary_raw.json.gz",
    "opentargets_25_09_drug_dictionary_raw.json.gz",
    "opentargets_25_03_25_09_historical_snapshot.json",
}
CHECKSUM_LINEAGE_ARTIFACTS = {
    "literature_manifest.json",
    "opentargets_25_03_25_09_historical_manifest.json",
    "opentargets_25_03_25_09_historical_snapshot.json",
    "clinical_history_manifest.json",
    "clinical_history_snapshot.json",
    "claim_graph_manifest.json",
    "p3_ideation_manifest.json",
    "p4_falsification_manifest.json",
    "p4_revision_manifest.json",
    "p5_decision_manifest.json",
    "p5_2_broad_outcome_manifest.json",
    "p5_3_identity_manifest.json",
    "p5_4_mapping_audit_manifest.json",
    "p5_5_drug_identity_manifest.json",
    "p5_6_assertion_history_manifest.json",
    "p5_7_independent_assertion_manifest.json",
    "p5_8_support_audit_manifest.json",
    "p5_9_selection_audit_manifest.json",
    "p6_0_artifact_inventory.jsonl.gz",
    "p6_0_evaluation_manifest.json",
    "p6_0_evaluation_snapshot.json",
    "p6_1_robustness_manifest.json",
    "p6_2_cohort_stress_manifest.json",
    "p6_3_paired_control_manifest.json",
    "p6_4_counterevidence_ablation_manifest.json",
    "p6_5_claim_synthesis_manifest.json",
    "p6_5_claim_synthesis_snapshot.json",
    "p6_5_experiment_dispositions.jsonl.gz",
    "p6_6_paper_bundle_manifest.json",
    "p6_6_paper_bundle_snapshot.json",
    "p6_6_paper_file_inventory.jsonl.gz",
    "p6_6_source_manifest_inventory.jsonl.gz",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _source_checksums() -> dict[str, str]:
    root = _project_root()
    paths = (
        "src/targetideator/release/canonical_models.py",
        "src/targetideator/release/canonical_store.py",
        "src/targetideator/release/replay_hardening_store.py",
    )
    return {path: file_sha256(root / path) for path in paths}


def canonical_rules() -> list[CanonicalFieldRule]:
    return [
        CanonicalFieldRule(
            id="capture_timestamp",
            selector="approved artifacts: **.captured_at",
            semantic_guard="both values are parseable timestamps",
            rationale="Capture wall-clock time is provenance metadata, not captured content.",
        ),
        CanonicalFieldRule(
            id="bounded_retry_counter",
            selector="approved artifacts: **.(attempt_count|retry_count)",
            semantic_guard="attempt_count is 1..3 and retry_count is 0..2",
            rationale="Bounded transport attempts do not change validated Parquet content.",
        ),
        CanonicalFieldRule(
            id="ctgov_status_timestamp",
            selector="ctgov_trials_current_raw.json: $.api_status.payload.dataTimestamp",
            semantic_guard="both values are parseable timestamps",
            rationale="The current API status clock is validation metadata and is not historical evidence.",
        ),
        CanonicalFieldRule(
            id="ctgov_status_payload_checksum",
            selector="ctgov_trials_current_raw.json: $.api_status.payload_sha256",
            semantic_guard="both values are SHA-256 strings",
            rationale="This checksum follows the independently admitted status-timestamp drift.",
        ),
        CanonicalFieldRule(
            id="current_api_capture_version",
            selector="clinical_history_manifest.json: $.raw_artifacts[*].version",
            semantic_guard="the parent source is chembl_api or ctgov_api in both artifacts",
            rationale="For current validation APIs, version is the capture instant, not a release identity.",
        ),
        CanonicalFieldRule(
            id="current_validation_data_timestamp",
            selector="clinical_history_snapshot.json: $.current_trial_validations[*].data_timestamp",
            semantic_guard="both values are parseable timestamps",
            rationale="The current registry validation timestamp is excluded from temporal evidence.",
        ),
        CanonicalFieldRule(
            id="checksum_lineage",
            selector="approved derived artifacts: explicit *sha256 fields",
            semantic_guard="both values are SHA-256 strings and every replay artifact is independently audited",
            rationale="Checksum propagation is accepted only after all 113 artifacts receive their own gate decision.",
        ),
        CanonicalFieldRule(
            id="paper_checksum_cell",
            selector="paper/tables/table_1_source_manifest_inventory.md: SHA-256 table cells",
            semantic_guard="replacing only 64-hex cells makes the Markdown byte-identical",
            rationale="The paper table is a rendered checksum-lineage view, not a scientific result field.",
        ),
    ]


def _load_structured(path: Path) -> Any:
    if path.name.endswith(".jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream]
    if path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".md":
        return path.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported canonical-content artifact: {path}")


def _normalized_path(path: str) -> str:
    return ARRAY_INDEX.sub("[*]", path)


def _json_differences(
    expected: Any, observed: Any, path: str = "$"
) -> list[tuple[str, str, Any, Any]]:
    if type(expected) is not type(observed):
        return [(path, _normalized_path(path), expected, observed)]
    if isinstance(expected, dict):
        differences = []
        for key in sorted(set(expected) | set(observed)):
            child = f"{path}.{key}"
            if key not in expected:
                differences.append((child, _normalized_path(child), MISSING, observed[key]))
            elif key not in observed:
                differences.append((child, _normalized_path(child), expected[key], MISSING))
            else:
                differences.extend(_json_differences(expected[key], observed[key], child))
        return differences
    if isinstance(expected, list):
        differences = []
        if len(expected) != len(observed):
            child = f"{path}.__length__"
            differences.append((child, _normalized_path(child), len(expected), len(observed)))
        for index, (left, right) in enumerate(zip(expected, observed)):
            differences.extend(_json_differences(left, right, f"{path}[{index}]"))
        return differences
    return [] if expected == observed else [(path, _normalized_path(path), expected, observed)]


def _parse_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and HEX_SHA256.fullmatch(value) is not None


def _rule_for_path(relative_path: str, path: str) -> str | None:
    if relative_path in CAPTURE_TIMESTAMP_ARTIFACTS and path.endswith(".captured_at"):
        return "capture_timestamp"
    if relative_path in RETRY_COUNTER_ARTIFACTS and path.endswith(
        (".attempt_count", ".retry_count")
    ):
        return "bounded_retry_counter"
    if relative_path == "ctgov_trials_current_raw.json":
        if path == "$.api_status.payload.dataTimestamp":
            return "ctgov_status_timestamp"
        if path == "$.api_status.payload_sha256":
            return "ctgov_status_payload_checksum"
    if (
        relative_path == "clinical_history_manifest.json"
        and path == "$.raw_artifacts[*].version"
    ):
        return "current_api_capture_version"
    if (
        relative_path == "clinical_history_snapshot.json"
        and path == "$.current_trial_validations[*].data_timestamp"
    ):
        return "current_validation_data_timestamp"
    if relative_path in CHECKSUM_LINEAGE_ARTIFACTS:
        terminal = path.rsplit(".", 1)[-1]
        if (
            terminal == "sha256"
            or terminal.endswith("_sha256")
            or ".source_checksums." in path
            or ".raw_checksums." in path
        ):
            return "checksum_lineage"
    if (
        relative_path == "paper/tables/table_1_source_manifest_inventory.md"
        and path == "$.__markdown_sha256_cells__"
    ):
        return "paper_checksum_cell"
    return None


def _semantic_guard(
    relative_path: str,
    concrete_path: str,
    normalized_path: str,
    expected_value: Any,
    observed_value: Any,
    expected_document: Any,
    observed_document: Any,
) -> bool:
    rule = _rule_for_path(relative_path, normalized_path)
    if rule in {
        "capture_timestamp",
        "ctgov_status_timestamp",
        "current_validation_data_timestamp",
    }:
        return _parse_timestamp(expected_value) and _parse_timestamp(observed_value)
    if rule == "bounded_retry_counter":
        value = observed_value if expected_value is MISSING else expected_value
        other = expected_value if expected_value is not MISSING else observed_value
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        if other is not MISSING and (not isinstance(other, int) or isinstance(other, bool)):
            return False
        maximum = 3 if normalized_path.endswith(".attempt_count") else 2
        minimum = 1 if normalized_path.endswith(".attempt_count") else 0
        values = [item for item in (expected_value, observed_value) if item is not MISSING]
        return all(minimum <= item <= maximum for item in values)
    if rule in {"ctgov_status_payload_checksum", "checksum_lineage"}:
        return _is_sha(expected_value) and _is_sha(observed_value)
    if rule == "current_api_capture_version":
        match = re.fullmatch(r"\$\.raw_artifacts\[(\d+)\]\.version", concrete_path)
        if match is None:
            return False
        index = int(match.group(1))
        allowed = {"chembl_api", "ctgov_api"}
        try:
            return (
                expected_document["raw_artifacts"][index]["source"] in allowed
                and observed_document["raw_artifacts"][index]["source"] in allowed
                and _parse_timestamp(expected_value)
                and _parse_timestamp(observed_value)
            )
        except (IndexError, KeyError, TypeError):
            return False
    return rule == "paper_checksum_cell"


def _project_json(value: Any, approved_paths: set[str], path: str = "$") -> Any:
    if isinstance(value, dict):
        projected = {}
        for key, item in value.items():
            child = f"{path}.{key}"
            if _normalized_path(child) in approved_paths:
                continue
            projected[key] = _project_json(item, approved_paths, child)
        return projected
    if isinstance(value, list):
        return [
            _project_json(item, approved_paths, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    return value


def _canonical_sha256(document: Any, approved_paths: set[str]) -> str:
    if isinstance(document, str):
        payload = HEX_SHA256.sub("<CANONICAL_SHA256>", document).encode("utf-8")
    else:
        payload = canonical_json_bytes(_project_json(document, approved_paths))
    return hashlib.sha256(payload).hexdigest()


def _markdown_differences(expected: str, observed: str) -> list[tuple[str, str, Any, Any]]:
    normalized_expected = HEX_SHA256.sub("<CANONICAL_SHA256>", expected)
    normalized_observed = HEX_SHA256.sub("<CANONICAL_SHA256>", observed)
    if expected == observed:
        return []
    if normalized_expected != normalized_observed:
        return [("$.__markdown_content__", "$.__markdown_content__", expected, observed)]
    if not HEX_SHA256.findall(expected) or len(HEX_SHA256.findall(expected)) != len(
        HEX_SHA256.findall(observed)
    ):
        return [("$.__markdown_content__", "$.__markdown_content__", expected, observed)]
    return [
        (
            "$.__markdown_sha256_cells__",
            "$.__markdown_sha256_cells__",
            "<expected checksum cells>",
            "<observed checksum cells>",
        )
    ]


def write_canonical_acceptance_artifacts(
    replay_root: Path,
    output_dir: Path,
    expected_root: Path | None = None,
) -> tuple[CanonicalAcceptanceSnapshot, CanonicalAcceptanceManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_root = expected_root or (_project_root() / "src" / "targetideator" / "fixtures")
    hardening = ReplayHardeningStore.load(
        replay_root / "r2_6_replay_hardening_snapshot.json",
        replay_root / "r2_6_replay_hardening_manifest.json",
    )
    diagnoses = hardening.diagnosis()
    prepared = []
    changed_path_map: dict[str, list[str]] = {}
    for diagnosis in diagnoses:
        if diagnosis.diagnosis == "exact_byte_match":
            prepared.append((diagnosis, None, None, [], []))
            continue
        expected_document = _load_structured(expected_root / diagnosis.relative_path)
        observed_document = _load_structured(replay_root / "data" / diagnosis.relative_path)
        differences = (
            _markdown_differences(expected_document, observed_document)
            if isinstance(expected_document, str)
            else _json_differences(expected_document, observed_document)
        )
        changed_paths = sorted({item[1] for item in differences})
        changed_path_map[diagnosis.relative_path] = changed_paths
        prepared.append(
            (diagnosis, expected_document, observed_document, differences, changed_paths)
        )

    changed_map_sha = hashlib.sha256(canonical_json_bytes(changed_path_map)).hexdigest()
    changed_map_matches = changed_map_sha == APPROVED_CHANGED_PATH_MAP_SHA256
    records = []
    for diagnosis, expected_document, observed_document, differences, changed_paths in prepared:
        if diagnosis.diagnosis == "exact_byte_match":
            records.append(
                CanonicalAcceptanceRecord(
                    id=stable_id("canonical-acceptance", diagnosis.relative_path),
                    execution_recipe_id=diagnosis.execution_recipe_id,
                    relative_path=diagnosis.relative_path,
                    byte_status=diagnosis.byte_status,
                    acceptance_status="accepted_byte_identity",
                    changed_paths=[],
                    applied_rule_ids=[],
                    expected_sha256=diagnosis.expected_sha256,
                    observed_sha256=diagnosis.observed_sha256,
                    approved_path_set_matches=True,
                    semantic_guards_passed=True,
                    canonical_content_matches=True,
                )
            )
            continue

        rule_ids = sorted(
            {
                rule
                for path in changed_paths
                if (rule := _rule_for_path(diagnosis.relative_path, path)) is not None
            }
        )
        paths_approved = changed_map_matches and all(
            _rule_for_path(diagnosis.relative_path, path) is not None
            for path in changed_paths
        )
        semantic_passed = paths_approved and all(
            _semantic_guard(
                diagnosis.relative_path,
                concrete,
                normalized,
                expected_value,
                observed_value,
                expected_document,
                observed_document,
            )
            for concrete, normalized, expected_value, observed_value in differences
        )
        approved_paths = set(changed_paths)
        expected_canonical = _canonical_sha256(expected_document, approved_paths)
        observed_canonical = _canonical_sha256(observed_document, approved_paths)
        canonical_matches = expected_canonical == observed_canonical
        accepted = (
            diagnosis.diagnosis == "declared_metadata_only_drift"
            and paths_approved
            and semantic_passed
            and canonical_matches
        )
        records.append(
            CanonicalAcceptanceRecord(
                id=stable_id("canonical-acceptance", diagnosis.relative_path),
                execution_recipe_id=diagnosis.execution_recipe_id,
                relative_path=diagnosis.relative_path,
                byte_status=diagnosis.byte_status,
                acceptance_status=(
                    "accepted_canonical_content_v1" if accepted else "rejected"
                ),
                changed_paths=changed_paths,
                applied_rule_ids=rule_ids,
                expected_sha256=diagnosis.expected_sha256,
                observed_sha256=diagnosis.observed_sha256,
                expected_canonical_sha256=expected_canonical,
                observed_canonical_sha256=observed_canonical,
                approved_path_set_matches=paths_approved,
                semantic_guards_passed=semantic_passed,
                canonical_content_matches=canonical_matches,
            )
        )

    counts = Counter(row.acceptance_status for row in records)
    semantic_failures = sum(not row.semantic_guards_passed for row in records)
    canonical_mismatches = sum(not row.canonical_content_matches for row in records)
    canonical_gate = (
        len(records) == 113
        and counts["accepted_byte_identity"] == 66
        and counts["accepted_canonical_content_v1"] == 47
        and counts["rejected"] == 0
        and changed_map_matches
        and semantic_failures == 0
        and canonical_mismatches == 0
    )
    quality = CanonicalAcceptanceQuality(
        byte_identity_acceptance_count=counts["accepted_byte_identity"],
        canonical_content_acceptance_count=counts[
            "accepted_canonical_content_v1"
        ],
        rejected_count=counts["rejected"],
        approved_changed_path_map_sha256=APPROVED_CHANGED_PATH_MAP_SHA256,
        changed_path_map_matches_approved_v1=changed_map_matches,
        semantic_guard_failure_count=semantic_failures,
        canonical_mismatch_count=canonical_mismatches,
        canonical_content_gate_passed=canonical_gate,
        blocking_limitations=[
            "Canonical-content v1 applies only to the frozen 47-artifact path map; any new path requires a new contract version.",
            "Checksum-lineage drift is accepted only because all 113 replay artifacts receive independent acceptance records.",
            "Byte identity remains mandatory for undeclared fields and artifacts outside the approved map.",
            "Projected-wheel runtime smoke and applied package convergence remain separate gates.",
            "R2.7 does not authorize redistribution or alter scientific claim status or C1/C4.",
        ],
    )
    ledger_path = output_dir / "r2_7_canonical_acceptance_ledger.jsonl.gz"
    _write_jsonl_gzip(ledger_path, [row.model_dump(mode="json") for row in records])
    parent_manifest = replay_root / "r2_6_replay_hardening_manifest.json"
    snapshot = CanonicalAcceptanceSnapshot(
        id=stable_id("canonical-acceptance", replay_root.name),
        created_at=hardening.snapshot.created_at,
        parent_replay_hardening_snapshot_id=hardening.snapshot.id,
        parent_replay_hardening_manifest_sha256=file_sha256(parent_manifest),
        staging_root_label=replay_root.name,
        rules=canonical_rules(),
        acceptance_ledger_path=ledger_path.name,
        acceptance_ledger_sha256=file_sha256(ledger_path),
        quality=quality,
        warning=(
            "VERSIONED FIELD-LEVEL ACCEPTANCE. Canonical-content v1 is a narrow gate for "
            "the frozen path map, not a general checksum waiver or release authorization."
        ),
    )
    snapshot_path = output_dir / "r2_7_canonical_acceptance_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = CanonicalAcceptanceManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        parent_replay_hardening_snapshot_id=hardening.snapshot.id,
        parent_replay_hardening_manifest_sha256=file_sha256(parent_manifest),
        acceptance_ledger_path=ledger_path.name,
        acceptance_ledger_sha256=file_sha256(ledger_path),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(
        output_dir / "r2_7_canonical_acceptance_manifest.json",
        manifest.model_dump(mode="json"),
    )
    return snapshot, manifest


class CanonicalAcceptanceStore:
    def __init__(
        self,
        snapshot: CanonicalAcceptanceSnapshot,
        manifest: CanonicalAcceptanceManifest,
        root: Path,
    ):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "CanonicalAcceptanceStore":
        return cls(
            CanonicalAcceptanceSnapshot.model_validate(_load_json(snapshot_path)),
            CanonicalAcceptanceManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def acceptance(self) -> list[CanonicalAcceptanceRecord]:
        with gzip.open(
            self.root / self.manifest.acceptance_ledger_path, "rt", encoding="utf-8"
        ) as stream:
            return [
                CanonicalAcceptanceRecord.model_validate(json.loads(line))
                for line in stream
            ]

    def quality_report(self) -> dict:
        parent_manifest = self.root / "r2_6_replay_hardening_manifest.json"
        try:
            source_match = _source_checksums() == self.manifest.source_checksums
        except FileNotFoundError:
            source_match = None
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "contract_version": self.snapshot.contract_version,
            "parent_replay_hardening_link_matches": (
                parent_manifest.is_file()
                and file_sha256(parent_manifest)
                == self.manifest.parent_replay_hardening_manifest_sha256
            ),
            "artifact_checksums_match": (
                file_sha256(self.root / self.manifest.acceptance_ledger_path)
                == self.manifest.acceptance_ledger_sha256
                and file_sha256(self.root / self.manifest.snapshot_path)
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": source_match,
            "warning": self.snapshot.warning,
        }
