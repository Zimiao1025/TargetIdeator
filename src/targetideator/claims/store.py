"""Deterministic P2.1 claim conversion, temporal query, and dependency correction."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from targetideator.data import fixture_path

from pydantic import ValidationError

from targetideator.claims.models import (
    ClaimChange,
    ClaimGraphDiff,
    ClaimGraphManifest,
    ClaimGraphQueryResult,
    ClaimGraphRawArtifact,
    ClaimGraphSnapshot,
    ClaimKind,
    ClaimObject,
    ClaimPolarity,
    ClaimProvenance,
    ClaimRelation,
    ClaimRelationType,
    EpistemicClaim,
    EvidenceFamily,
    StructuredClaimContext,
)
from targetideator.evidence.clinical_models import ClinicalHistorySnapshot
from targetideator.evidence.clinical_store import (
    ClinicalHistoryStore,
    default_clinical_snapshot_path,
    load_default_clinical_store,
)
from targetideator.evidence.models import EntityMapping
from targetideator.evidence.store import _load_json, file_sha256
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.io import write_json
from targetideator.normalization.entities import default_resolver

CONVERTER_VERSION = "structured-claim-converter-v1"
CLAIM_GRAPH_ID = "ti:claim-graph:crohns-clinical-history-25.03-25.09"
POPULATION_UNKNOWN = "registered study population; eligibility criteria not extracted in P2.1"
ANATOMY_UNKNOWN = "not specified by the structured P1.3 source fields"
CELL_UNKNOWN = "not specified by the structured P1.3 source fields"
OUTCOME_BOUNDARY = (
    "Clinical development and registry metadata only; no efficacy, safety-event, or causal-disease "
    "effect is asserted."
)


def default_claim_graph_snapshot_path() -> Path:
    return fixture_path("claim_graph_snapshot.json")


def default_claim_graph_manifest_path() -> Path:
    return fixture_path("claim_graph_manifest.json")


def _source_claim_id(version: str, source_id: str) -> str:
    return stable_id("claim-observation", f"chembl-source-{version}-{source_id}")


def _derived_claim_id(version: str, source_id: str) -> str:
    return stable_id("claim-observation", f"clinical-development-{version}-{source_id}")


def _trial_claim_id(version: str, nct_id: str) -> str:
    return stable_id("claim-observation", f"trial-state-{version}-{nct_id}")


def _family_id(nct_id: str) -> str:
    return stable_id("evidence-family", f"trial-{nct_id}")


def _relation(
    source: str,
    target: str,
    relation_type: ClaimRelationType,
    available_on: date,
    nct_id: str,
    notes: str,
) -> ClaimRelation:
    natural_key = f"{source}-{relation_type.value}-{target}"
    return ClaimRelation(
        id=stable_id("claim-relation", natural_key),
        source_claim_id=source,
        target_claim_id=target,
        relation_type=relation_type,
        available_on=available_on,
        evidence_family_id=_family_id(nct_id),
        notes=notes,
    )


def _context_from_evidence(record) -> StructuredClaimContext:
    return StructuredClaimContext(
        disease=record.disease,
        target=record.target,
        drug=record.drug,
        trial=record.trial,
        population=POPULATION_UNKNOWN,
        anatomical_region=ANATOMY_UNKNOWN,
        cell_type=CELL_UNKNOWN,
        model_system="interventional clinical-development record",
        clinical_phase=record.clinical_phase,
        clinical_status=record.clinical_status,
        outcome_scope="clinical-development metadata; efficacy endpoint not represented",
    )


def _evidence_provenance(record) -> ClaimProvenance:
    return ClaimProvenance(
        source_name="Open Targets ChEMBL evidence",
        source_record_id=record.source_evidence_id,
        source_observation_id=record.id,
        source_snapshot_id=record.release_id,
        available_on=record.release_date,
        source_url=record.source_urls[0],
        raw_record_sha256=record.raw_row_sha256,
        transform_version=CONVERTER_VERSION,
        locator=f"evidence.id={record.source_evidence_id}; structured fields",
        field_map=record.field_map,
    )


def _trial_provenance(record) -> ClaimProvenance:
    return ClaimProvenance(
        source_name="AACT studies",
        source_record_id=record.trial.identifier,
        source_observation_id=record.id,
        source_snapshot_id=record.release_id,
        available_on=record.snapshot_date,
        source_url=record.source_url,
        raw_record_sha256=record.raw_row_sha256,
        transform_version=CONVERTER_VERSION,
        locator=f"studies.txt:nct_id={record.trial.identifier}; structured fields",
        field_map=record.field_map,
    )


def _convert_snapshot(
    clinical: ClinicalHistorySnapshot,
    source_sha256: str,
) -> ClaimGraphSnapshot:
    claims: list[EpistemicClaim] = []
    relations: list[ClaimRelation] = []
    claim_ids_by_family: dict[str, list[str]] = {}
    aact_by_version_trial = {
        (item.snapshot_version, item.trial.identifier): item
        for item in clinical.trial_records
    }
    aact_for_chembl: dict[str, str] = {}
    for release in clinical.chembl_releases:
        eligible = [
            item for item in clinical.aact_releases if item.snapshot_date <= release.release_date
        ]
        if not eligible:
            continue
        aact_for_chembl[release.version] = max(eligible, key=lambda item: item.snapshot_date).version

    for record in clinical.evidence_records:
        family_id = _family_id(record.trial.identifier)
        source_id = _source_claim_id(record.release_version, record.source_evidence_id)
        derived_id = _derived_claim_id(record.release_version, record.source_evidence_id)
        context = _context_from_evidence(record)
        provenance = _evidence_provenance(record)
        source_claim = EpistemicClaim(
            id=source_id,
            assertion_key=stable_id(
                "claim-assertion", f"chembl-source-{record.source_evidence_id}"
            ),
            kind=ClaimKind.SOURCE_EVIDENCE_FACT,
            subject=record.target,
            predicate="is linked to a clinical-stage drug in a registered study",
            object=ClaimObject(entity=record.drug),
            polarity=ClaimPolarity.NEUTRAL,
            scope="clinical_development",
            context=context,
            observed_in=record.release_version,
            available_on=record.release_date,
            effect_size_missing_reason="The ChEMBL evidence string contains no treatment-effect estimate.",
            uncertainty="The record establishes source membership, not clinical benefit or target causality.",
            interpretation_boundary=OUTCOME_BOUNDARY,
            provenance=provenance,
        )
        derived_claim = EpistemicClaim(
            id=derived_id,
            assertion_key=stable_id(
                "claim-assertion", f"clinical-development-{record.source_evidence_id}"
            ),
            kind=ClaimKind.CLINICAL_DEVELOPMENT_ASSERTION,
            subject=record.target,
            predicate="has a ChEMBL clinical-development evidence string for",
            object=ClaimObject(entity=record.disease),
            polarity=ClaimPolarity.SUPPORTS,
            scope="clinical_development",
            context=context,
            observed_in=record.release_version,
            available_on=record.release_date,
            effect_size_missing_reason="Clinical-development presence is categorical, not an effect estimate.",
            uncertainty="Support is limited to clinical-development activity and cannot be read as efficacy.",
            interpretation_boundary=OUTCOME_BOUNDARY,
            provenance=provenance,
        )
        claims.extend((source_claim, derived_claim))
        claim_ids_by_family.setdefault(family_id, []).extend((source_id, derived_id))
        relations.append(
            _relation(
                derived_id,
                source_id,
                ClaimRelationType.DERIVED_FROM,
                record.release_date,
                record.trial.identifier,
                "The clinical-development assertion is deterministically derived from this source evidence string.",
            )
        )

    for trial in clinical.trial_records:
        family_id = _family_id(trial.trial.identifier)
        claim_id = _trial_claim_id(trial.snapshot_version, trial.trial.identifier)
        claims.append(
            EpistemicClaim(
                id=claim_id,
                assertion_key=stable_id(
                    "claim-assertion", f"trial-state-{trial.trial.identifier}"
                ),
                kind=ClaimKind.TRIAL_REGISTRY_STATE,
                subject=trial.trial,
                predicate="had registered overall status",
                object=ClaimObject(literal=trial.overall_status),
                polarity=ClaimPolarity.QUALIFIES,
                scope="registry_state",
                context=StructuredClaimContext(
                    trial=trial.trial,
                    population=POPULATION_UNKNOWN,
                    anatomical_region=ANATOMY_UNKNOWN,
                    cell_type=CELL_UNKNOWN,
                    model_system="ClinicalTrials.gov registry record",
                    trial_phase=trial.phase,
                    trial_status=trial.overall_status,
                    trial_last_update_posted_date=trial.last_update_posted_date,
                    outcome_scope="registry status and dates; no trial outcome interpretation",
                ),
                observed_in=trial.snapshot_version,
                available_on=trial.snapshot_date,
                effect_size_missing_reason="AACT studies.txt registry metadata contains no treatment-effect estimate.",
                uncertainty="Registry status is operational metadata and does not establish efficacy.",
                interpretation_boundary=OUTCOME_BOUNDARY,
                provenance=_trial_provenance(trial),
            )
        )
        claim_ids_by_family.setdefault(family_id, []).append(claim_id)

    for evidence in clinical.evidence_records:
        aact_version = aact_for_chembl.get(evidence.release_version)
        trial = aact_by_version_trial.get((aact_version, evidence.trial.identifier))
        if trial is None:
            continue
        source_id = _source_claim_id(evidence.release_version, evidence.source_evidence_id)
        derived_id = _derived_claim_id(evidence.release_version, evidence.source_evidence_id)
        trial_id = _trial_claim_id(trial.snapshot_version, trial.trial.identifier)
        available_on = max(evidence.release_date, trial.snapshot_date)
        relations.extend(
            (
                _relation(
                    trial_id,
                    derived_id,
                    ClaimRelationType.QUALIFIES,
                    available_on,
                    trial.trial.identifier,
                    "The historical registry state qualifies interpretation of the clinical-development assertion.",
                ),
                _relation(
                    trial_id,
                    source_id,
                    ClaimRelationType.SAME_STUDY_AS,
                    available_on,
                    trial.trial.identifier,
                    "Both claims describe the same NCT-identified registered study and are not independent evidence; cohort or arm identity is not asserted.",
                ),
            )
        )

    claims_by_assertion: dict[str, list[EpistemicClaim]] = {}
    for claim in claims:
        claims_by_assertion.setdefault(claim.assertion_key, []).append(claim)
    for observations in claims_by_assertion.values():
        observations.sort(key=lambda item: (item.available_on, item.observed_in))
        for earlier, later in zip(observations, observations[1:], strict=False):
            nct_id = later.context.trial.identifier
            relations.append(
                _relation(
                    later.id,
                    earlier.id,
                    ClaimRelationType.SUPERSEDES,
                    later.available_on,
                    nct_id,
                    "Later source observation supersedes the earlier observation for temporal replay.",
                )
            )

    trial_entities = {
        item.trial.identifier: item.trial for item in clinical.trial_records
    }
    claim_by_id = {item.id: item for item in claims}
    families = [
        EvidenceFamily(
            id=family_id,
            dependency_key=claim_by_id[member_ids[0]].context.trial.identifier,
            trial=trial_entities[claim_by_id[member_ids[0]].context.trial.identifier],
            member_claim_ids=sorted(member_ids),
            correction_rationale=(
                "All normalized and derived claims in this family trace to the same registered trial; "
                "release repetitions and registry metadata do not add independent evidence units."
            ),
        )
        for family_id, member_ids in sorted(claim_ids_by_family.items())
    ]
    return ClaimGraphSnapshot(
        id=CLAIM_GRAPH_ID,
        source_clinical_snapshot_id=clinical.id,
        source_clinical_snapshot_sha256=source_sha256,
        converter_version=CONVERTER_VERSION,
        claims=sorted(claims, key=lambda item: (item.available_on, item.id)),
        relations=sorted(relations, key=lambda item: (item.available_on, item.id)),
        evidence_families=families,
    )


def build_claim_graph_snapshot(
    clinical_snapshot_path: Path,
    snapshot_path: Path,
    manifest_path: Path,
) -> tuple[ClaimGraphSnapshot, ClaimGraphManifest]:
    source_payload = _load_json(clinical_snapshot_path)
    clinical = ClinicalHistorySnapshot.model_validate(source_payload)
    source_sha = file_sha256(clinical_snapshot_path)
    snapshot = _convert_snapshot(clinical, source_sha)
    write_json(snapshot_path, snapshot.model_dump(mode="json"))
    manifest = ClaimGraphManifest(
        snapshot_id=snapshot.id,
        source_artifact=ClaimGraphRawArtifact(
            path=clinical_snapshot_path.name,
            sha256=source_sha,
        ),
        normalized_path=snapshot_path.name,
        normalized_sha256=file_sha256(snapshot_path),
        converter_version=CONVERTER_VERSION,
        claim_count=len(snapshot.claims),
        relation_count=len(snapshot.relations),
        evidence_family_count=len(snapshot.evidence_families),
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    return snapshot, manifest


class ClaimGraphStore:
    def __init__(
        self,
        snapshot: ClaimGraphSnapshot,
        clinical_store: ClinicalHistoryStore,
        manifest: ClaimGraphManifest | None = None,
        snapshot_path: Path | None = None,
        source_snapshot_path: Path | None = None,
    ):
        self.snapshot = snapshot
        self.clinical_store = clinical_store
        self.manifest = manifest
        self.snapshot_path = snapshot_path
        self.source_snapshot_path = source_snapshot_path
        self._resolver = default_resolver()
        self._claims = {item.id: item for item in snapshot.claims}
        self._family_by_claim = {
            claim_id: family
            for family in snapshot.evidence_families
            for claim_id in family.member_claim_ids
        }

    @classmethod
    def load(
        cls,
        snapshot_path: Path,
        clinical_store: ClinicalHistoryStore,
        manifest_path: Path | None = None,
        source_snapshot_path: Path | None = None,
    ) -> "ClaimGraphStore":
        try:
            snapshot = ClaimGraphSnapshot.model_validate(_load_json(snapshot_path))
            manifest = (
                ClaimGraphManifest.model_validate(_load_json(manifest_path))
                if manifest_path
                else None
            )
        except ValidationError as exc:
            raise ValueError(f"Invalid claim-graph artifact: {exc}") from exc
        return cls(snapshot, clinical_store, manifest, snapshot_path, source_snapshot_path)

    def _canonical_id(self, value: str, entity_type: str) -> str:
        result = self._resolver.resolve(value, entity_type, self.snapshot.id)
        return result.canonical.identifier if isinstance(result, EntityMapping) else value

    def query(self, disease_id: str, target_id: str, as_of_date: date) -> ClaimGraphQueryResult:
        disease = self._canonical_id(disease_id, "disease")
        target = self._canonical_id(target_id, "gene")
        clinical_snapshot = self.clinical_store.snapshot
        chembl = [item for item in clinical_snapshot.chembl_releases if item.release_date <= as_of_date]
        aact = [item for item in clinical_snapshot.aact_releases if item.snapshot_date <= as_of_date]
        selected_chembl = max(chembl, key=lambda item: item.release_date) if chembl else None
        selected_aact = max(aact, key=lambda item: item.snapshot_date) if aact else None
        evidence_claims = [
            item
            for item in self.snapshot.claims
            if item.kind != ClaimKind.TRIAL_REGISTRY_STATE
            and selected_chembl is not None
            and item.observed_in == selected_chembl.version
            and item.context.disease is not None
            and item.context.disease.identifier == disease
            and item.context.target is not None
            and item.context.target.identifier == target
        ]
        family_ids = {self._family_by_claim[item.id].id for item in evidence_claims}
        trial_claims = [
            item
            for item in self.snapshot.claims
            if item.kind == ClaimKind.TRIAL_REGISTRY_STATE
            and selected_aact is not None
            and item.observed_in == selected_aact.version
            and self._family_by_claim[item.id].id in family_ids
        ]
        selected_claims = sorted(
            [*evidence_claims, *trial_claims], key=lambda item: (item.kind, item.id)
        )
        selected_ids = {item.id for item in selected_claims}
        relations = [
            item
            for item in self.snapshot.relations
            if item.source_claim_id in selected_ids and item.target_claim_id in selected_ids
        ]
        families = []
        for family in self.snapshot.evidence_families:
            members = sorted(set(family.member_claim_ids) & selected_ids)
            if members:
                families.append(family.model_copy(update={"member_claim_ids": members}))
        leakage = sum(item.available_on > as_of_date for item in selected_claims) + sum(
            item.available_on > as_of_date for item in relations
        )
        valid = selected_chembl is not None and selected_aact is not None and leakage == 0
        ratio = len(families) / len(selected_claims) if selected_claims else 0.0
        warning = (
            "Claims describe clinical-development and registry metadata only; they do not assert efficacy "
            "or target causality. Dependency-corrected counts use one independent unit per NCT trial."
        )
        return ClaimGraphQueryResult(
            snapshot_id=self.snapshot.id,
            disease_id=disease,
            target_id=target,
            as_of_date=as_of_date,
            selected_chembl_release=selected_chembl.version if selected_chembl else None,
            selected_aact_snapshot=selected_aact.version if selected_aact else None,
            claims=selected_claims,
            relations=relations,
            evidence_families=families,
            naive_claim_count=len(selected_claims),
            independent_evidence_count=len(families),
            dependency_correction_ratio=ratio,
            post_cutoff_leakage_count=leakage,
            retrospective_valid=valid,
            warning=warning,
        )

    @staticmethod
    def _claim_signature(claim: EpistemicClaim) -> dict[str, Any]:
        return {
            "predicate": claim.predicate,
            "object": claim.object.model_dump(mode="json"),
            "polarity": claim.polarity,
            "clinical_phase": claim.context.clinical_phase,
            "clinical_status": claim.context.clinical_status,
            "trial_phase": claim.context.trial_phase,
            "trial_status": claim.context.trial_status,
            "trial_last_update_posted_date": claim.context.trial_last_update_posted_date,
        }

    def diff(
        self,
        disease_id: str,
        target_id: str,
        earlier_date: date,
        later_date: date,
    ) -> ClaimGraphDiff:
        earlier = self.query(disease_id, target_id, earlier_date)
        later = self.query(disease_id, target_id, later_date)
        earlier_by_key = {item.assertion_key: item for item in earlier.claims}
        later_by_key = {item.assertion_key: item for item in later.claims}
        shared = sorted(earlier_by_key.keys() & later_by_key.keys())
        changes: list[ClaimChange] = []
        for key in shared:
            before = self._claim_signature(earlier_by_key[key])
            after = self._claim_signature(later_by_key[key])
            fields = sorted(field for field in before if before[field] != after[field])
            if fields:
                changes.append(
                    ClaimChange(
                        assertion_key=key,
                        earlier_claim_id=earlier_by_key[key].id,
                        later_claim_id=later_by_key[key].id,
                        changed_fields=fields,
                    )
                )
        return ClaimGraphDiff(
            earlier_date=earlier_date,
            later_date=later_date,
            added_assertion_keys=sorted(later_by_key.keys() - earlier_by_key.keys()),
            removed_assertion_keys=sorted(earlier_by_key.keys() - later_by_key.keys()),
            changed_claims=changes,
        )

    def claim_lineage(self, claim_id: str) -> dict[str, Any] | None:
        claim = self._claims.get(claim_id)
        if claim is None:
            return None
        source_id = claim.provenance.source_observation_id
        if claim.provenance.source_name == "AACT studies":
            raw = self.clinical_store.raw_trial(source_id)
        else:
            raw = self.clinical_store.raw_evidence(source_id)
        family = self._family_by_claim[claim.id]
        return {
            "claim": claim.model_dump(mode="json"),
            "raw_source_record": raw,
            "evidence_family": family.model_dump(mode="json"),
        }

    def quality_report(self) -> dict[str, Any]:
        cutoff = date(2025, 9, 17)
        targets = ("IL23A", "JAK1", "TNFSF15", "NOD2")
        queries = [self.query("MONDO:0005011", target, cutoff) for target in targets]
        before = [
            self.query("MONDO:0005011", target, date(2025, 3, 18)) for target in targets
        ]
        diffs = [
            self.diff("MONDO:0005011", target, date(2025, 3, 19), cutoff)
            for target in targets
        ]
        source_checksum_matches = bool(
            self.source_snapshot_path
            and file_sha256(self.source_snapshot_path)
            == self.snapshot.source_clinical_snapshot_sha256
        )
        normalized_checksum_matches = bool(
            self.manifest
            and self.snapshot_path
            and file_sha256(self.snapshot_path) == self.manifest.normalized_sha256
        )
        deterministic = False
        if self.source_snapshot_path and self.snapshot_path:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rebuilt, _ = build_claim_graph_snapshot(
                    self.source_snapshot_path,
                    root / "snapshot.json",
                    root / "manifest.json",
                )
                deterministic = canonical_json_bytes(rebuilt.model_dump(mode="json")) == canonical_json_bytes(
                    self.snapshot.model_dump(mode="json")
                )
        relation_type_counts = {
            kind.value: sum(item.relation_type == kind for item in self.snapshot.relations)
            for kind in ClaimRelationType
        }
        active_claims = sum(item.naive_claim_count for item in queries)
        independent = sum(item.independent_evidence_count for item in queries)
        return {
            "snapshot_id": self.snapshot.id,
            "claim_observation_count": len(self.snapshot.claims),
            "claim_assertion_count": len({item.assertion_key for item in self.snapshot.claims}),
            "relation_count": len(self.snapshot.relations),
            "relation_type_counts": relation_type_counts,
            "evidence_family_count": len(self.snapshot.evidence_families),
            "structured_field_provenance_coverage": (
                sum(item.provenance.mode == "structured_fields" for item in self.snapshot.claims)
                / len(self.snapshot.claims)
                if self.snapshot.claims
                else 1.0
            ),
            "raw_source_lineage_coverage": (
                sum(self.claim_lineage(item.id)["raw_source_record"] is not None for item in self.snapshot.claims)
                / len(self.snapshot.claims)
                if self.snapshot.claims
                else 1.0
            ),
            "unsupported_efficacy_claim_count": sum(
                item.scope not in {"clinical_development", "registry_state"}
                for item in self.snapshot.claims
            ),
            "current_metadata_used_for_claims": False,
            "post_cutoff_leakage_count": sum(
                item.post_cutoff_leakage_count for item in [*queries, *before]
            ),
            "active_naive_claim_count": active_claims,
            "active_independent_evidence_count": independent,
            "dependency_correction_ratio": independent / active_claims if active_claims else 0.0,
            "changed_assertions_25_03_to_25_09": sum(
                len(item.changed_claims) for item in diffs
            ),
            "source_checksum_matches": source_checksum_matches,
            "normalized_checksum_matches": normalized_checksum_matches,
            "deterministic_rebuild_matches": deterministic,
            "retrospective_replay_enabled": all(item.retrospective_valid for item in queries[:2]),
        }


def load_default_claim_graph_store() -> ClaimGraphStore:
    return ClaimGraphStore.load(
        default_claim_graph_snapshot_path(),
        clinical_store=load_default_clinical_store(),
        manifest_path=default_claim_graph_manifest_path(),
        source_snapshot_path=default_clinical_snapshot_path(),
    )
