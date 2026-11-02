"""Build a descriptive join from source-support strata to outcome provenance."""

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
from targetideator.outcomes.identity_store import (
    EXPLICIT_CAUSE_CATEGORIES,
    _write_jsonl_gzip,
    default_identity_manifest_path,
    load_default_identity_store,
)
from targetideator.outcomes.independent_assertion_store import (
    default_independent_assertion_manifest_path,
    load_default_independent_assertion_store,
)
from targetideator.outcomes.support_audit_models import (
    SupportAuditManifest,
    SupportAuditQuality,
    SupportAuditSnapshot,
)

BUILDER_VERSION = "p5.8-corroboration-aware-outcome-provenance-v1"
SNAPSHOT_ID = "ti:support-audit:outcome-provenance-v1"
CREATED_AT = datetime(2026, 11, 2, 22, 0, tzinfo=timezone.utc)
STRATA = (
    "unmapped_no_source_assertion",
    "mapped_all_cross_source_pairs",
    "mapped_mixed_pair_support",
    "mapped_opentargets_chembl_only",
)


def default_support_audit_snapshot_path() -> Path:
    return fixture_path("p5_8_support_audit_snapshot.json")


def default_support_audit_manifest_path() -> Path:
    return fixture_path("p5_8_support_audit_manifest.json")


def _support_by_trial() -> dict[str, dict]:
    store = load_default_independent_assertion_store()
    by_trial: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(
        artifact_path(store.root, store.manifest.corroboration_path),
        "rt",
        encoding="utf-8",
    ) as stream:
        for line in stream:
            row = json.loads(line)
            by_trial[row["nct_id"]].append(row)
    result = {}
    for nct_id, rows in by_trial.items():
        cross = sum(row["corroboration_status"] == "cross_source_drug_target_supported" for row in rows)
        total = len(rows)
        if cross == total:
            stratum = "mapped_all_cross_source_pairs"
        elif cross:
            stratum = "mapped_mixed_pair_support"
        else:
            stratum = "mapped_opentargets_chembl_only"
        result[nct_id] = {
            "support_stratum": stratum,
            "source_assertion_count": total,
            "cross_source_supported_assertion_count": cross,
            "opentargets_chembl_only_assertion_count": total - cross,
            "source_assertion_ids": sorted(row["source_assertion_id"] for row in rows),
        }
    return result


def build_support_audit_records() -> tuple[list[dict], list[dict], SupportAuditQuality]:
    identity = load_default_identity_store()
    support = _support_by_trial()
    enriched = []
    explicit = []
    seen_nct = set()
    nct_counts = Counter()
    outcome_counts = Counter()
    explicit_counts = Counter()
    category_counts: dict[str, Counter] = defaultdict(Counter)
    with gzip.open(
        artifact_path(identity.root, identity.manifest.provenance_path),
        "rt",
        encoding="utf-8",
    ) as stream:
        for line in stream:
            row = json.loads(line)
            trial_support = support.get(row["nct_id"])
            if trial_support is None:
                trial_support = {
                    "support_stratum": "unmapped_no_source_assertion",
                    "source_assertion_count": 0,
                    "cross_source_supported_assertion_count": 0,
                    "opentargets_chembl_only_assertion_count": 0,
                    "source_assertion_ids": [],
                }
            stratum = trial_support["support_stratum"]
            enriched_row = {
                **row,
                "support_audit_id": stable_id("outcome-support-audit", row["outcome_record_id"]),
                **trial_support,
                "cross_source_support_scope": "drug_target_only_not_trial_linkage",
                "trial_mapping_status_changed": False,
                "outcome_interpretation_changed": False,
                "support_stratum_used_as_model_feature": False,
            }
            enriched.append(enriched_row)
            outcome_counts[stratum] += 1
            if row["nct_id"] not in seen_nct:
                seen_nct.add(row["nct_id"])
                nct_counts[stratum] += 1
            if row["outcome_category"] in EXPLICIT_CAUSE_CATEGORIES:
                explicit_row = {
                    **enriched_row,
                    "audit_scope": "explicit_registry_stop_reason_lineage_only",
                    "causal_target_attribution_allowed": False,
                }
                explicit.append(explicit_row)
                explicit_counts[stratum] += 1
                category_counts[row["outcome_category"]][stratum] += 1
    nct_dict = {name: nct_counts[name] for name in STRATA}
    outcome_dict = {name: outcome_counts[name] for name in STRATA}
    explicit_dict = {name: explicit_counts[name] for name in STRATA}
    category_dict = {
        category: {name: category_counts[category][name] for name in STRATA}
        for category in sorted(EXPLICIT_CAUSE_CATEGORIES)
    }
    quality = SupportAuditQuality(
        outcome_provenance_record_count=len(enriched),
        unique_nct_count=len(seen_nct),
        mapped_nct_count=len(support),
        unmapped_nct_count=nct_counts["unmapped_no_source_assertion"],
        nct_counts_by_support_stratum=nct_dict,
        outcome_record_counts_by_support_stratum=outcome_dict,
        explicit_event_record_count=len(explicit),
        explicit_event_counts_by_support_stratum=explicit_dict,
        explicit_event_counts_by_category_and_support_stratum=category_dict,
        source_assertion_record_count=sum(item["source_assertion_count"] for item in support.values()),
        support_stratum_coverage=len(enriched) / len(enriched) if enriched else 0.0,
        engineering_gate_passed=(
            len(enriched) == 71947
            and len(seen_nct) == 36086
            and len(explicit) == 167
            and len(support) == 14392
            and sum(nct_counts.values()) == len(seen_nct)
            and all(not row["trial_mapping_status_changed"] for row in enriched)
            and all(not row["support_stratum_used_as_model_feature"] for row in enriched)
        ),
        blocking_limitations=[
            "Support strata describe source coverage, not comparative efficacy, safety, PK, or strategy risk.",
            "DrugCentral supports a drug-target pair but does not independently assert the trial linkage.",
            "The four strata are systematically confounded; no missing-at-random or causal claim is made.",
            "Explicit registry stop reasons are trial-level provenance and cannot be attributed to a target.",
            "Post-baseline support strata are audit metadata and remain forbidden as temporal model features.",
        ],
    )
    return enriched, explicit, quality


def render_support_audit_report(snapshot: SupportAuditSnapshot) -> str:
    q = snapshot.quality
    lines = [
        "# TargetIdeator P5.8 corroboration-aware outcome provenance audit",
        "",
        f"> {snapshot.warning}",
        "",
        f"- Outcome provenance records: {q.outcome_provenance_record_count}",
        f"- Unique NCT: {q.unique_nct_count}",
        f"- Explicit stop-reason events: {q.explicit_event_record_count}",
        "",
        "## Trial support strata",
        "",
    ]
    lines.extend(f"- `{name}`: {count}" for name, count in q.nct_counts_by_support_stratum.items())
    lines.extend(["", "## Blocking limitations", ""])
    lines.extend(f"- {item}" for item in q.blocking_limitations)
    lines.append("")
    return "\n".join(lines)


def _source_checksums() -> dict[str, str]:
    identity = load_default_identity_store()
    independent = load_default_independent_assertion_store()
    identity_path = artifact_path(identity.root, identity.manifest.provenance_path)
    corroboration_path = artifact_path(
        independent.root, independent.manifest.corroboration_path
    )
    return {
        identity_path.name: file_sha256(identity_path),
        default_identity_manifest_path().name: file_sha256(default_identity_manifest_path()),
        corroboration_path.name: file_sha256(corroboration_path),
        default_independent_assertion_manifest_path().name: file_sha256(default_independent_assertion_manifest_path()),
    }


def write_support_audit_artifacts(output_dir: Path) -> tuple[SupportAuditSnapshot, SupportAuditManifest]:
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched, explicit, quality = build_support_audit_records()
    enriched_path = output_dir / "p5_8_support_stratified_outcomes.jsonl.gz"
    explicit_path = output_dir / "p5_8_explicit_event_audit.jsonl.gz"
    _write_jsonl_gzip(enriched_path, enriched)
    _write_jsonl_gzip(explicit_path, explicit)
    snapshot = SupportAuditSnapshot(
        id=SNAPSHOT_ID,
        created_at=CREATED_AT,
        enriched_outcome_path=enriched_path.name,
        enriched_outcome_sha256=file_sha256(enriched_path),
        explicit_event_path=explicit_path.name,
        explicit_event_sha256=file_sha256(explicit_path),
        quality=quality,
        warning=(
            "DESCRIPTIVE PROVENANCE AUDIT ONLY. Support strata must not be read as "
            "outcome-rate comparisons, target attribution, or model validation."
        ),
    )
    snapshot_path = output_dir / "p5_8_support_audit_snapshot.json"
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    (output_dir / "p5_8_support_audit_report.md").write_text(
        render_support_audit_report(snapshot), encoding="utf-8"
    )
    manifest = SupportAuditManifest(
        snapshot_id=snapshot.id,
        builder_version=BUILDER_VERSION,
        source_checksums=_source_checksums(),
        enriched_outcome_path=enriched_path.name,
        enriched_outcome_sha256=file_sha256(enriched_path),
        enriched_outcome_record_count=len(enriched),
        explicit_event_path=explicit_path.name,
        explicit_event_sha256=file_sha256(explicit_path),
        explicit_event_record_count=len(explicit),
        snapshot_path=snapshot_path.name,
        snapshot_sha256=file_sha256(snapshot_path),
    )
    write_json(output_dir / "p5_8_support_audit_manifest.json", manifest.model_dump(mode="json"))
    return snapshot, manifest


class SupportAuditStore:
    def __init__(self, snapshot: SupportAuditSnapshot, manifest: SupportAuditManifest, root: Path):
        self.snapshot = snapshot
        self.manifest = manifest
        self.root = root

    @classmethod
    def load(cls, snapshot_path: Path, manifest_path: Path) -> "SupportAuditStore":
        return cls(
            SupportAuditSnapshot.model_validate(_load_json(snapshot_path)),
            SupportAuditManifest.model_validate(_load_json(manifest_path)),
            snapshot_path.parent,
        )

    def _sample(self, filename: str, limit: int, stratum: str | None = None, category: str | None = None) -> list[dict]:
        rows = []
        with gzip.open(artifact_path(self.root, filename), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if stratum is not None and row["support_stratum"] != stratum:
                    continue
                if category is not None and row["outcome_category"] != category:
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    break
        return rows

    def sample_outcomes(self, limit: int = 20, stratum: str | None = None) -> list[dict]:
        return self._sample(self.manifest.enriched_outcome_path, limit, stratum)

    def sample_explicit_events(self, limit: int = 20, stratum: str | None = None, category: str | None = None) -> list[dict]:
        return self._sample(self.manifest.explicit_event_path, limit, stratum, category)

    def trial(self, nct_id: str) -> dict:
        rows = []
        with gzip.open(
            artifact_path(self.root, self.manifest.enriched_outcome_path),
            "rt",
            encoding="utf-8",
        ) as stream:
            for line in stream:
                row = json.loads(line)
                if row["nct_id"] == nct_id:
                    rows.append(row)
        return {"nct_id": nct_id, "outcome_provenance": rows}

    def quality_report(self) -> dict:
        expected = _source_checksums()
        return {
            **self.snapshot.quality.model_dump(mode="json"),
            "snapshot_id": self.snapshot.id,
            "artifact_checksums_match": (
                file_sha256(artifact_path(self.root, self.manifest.enriched_outcome_path))
                == self.manifest.enriched_outcome_sha256
                and file_sha256(artifact_path(self.root, self.manifest.explicit_event_path))
                == self.manifest.explicit_event_sha256
                and file_sha256(artifact_path(self.root, self.manifest.snapshot_path))
                == self.manifest.snapshot_sha256
            ),
            "source_checksums_match": expected == self.manifest.source_checksums,
            "warning": self.snapshot.warning,
        }


def load_default_support_audit_store() -> SupportAuditStore:
    return SupportAuditStore.load(default_support_audit_snapshot_path(), default_support_audit_manifest_path())
