"""Conservative entity resolution with an explicit unresolved queue.

P1 never uses fuzzy matching to silently force a disease or gene identifier.
Only canonical identifiers and reviewed aliases are auto-resolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from targetideator.evidence.models import (
    CanonicalEntity,
    EntityMapping,
    MappingStatus,
    UnresolvedEntity,
)
from targetideator.ids import stable_id

DEFAULT_SNAPSHOT_ID = "ti:snapshot:opentargets-26.09-crohns-4-targets"


@dataclass(frozen=True)
class EntityDefinition:
    canonical: CanonicalEntity
    aliases: tuple[str, ...]


DEFINITIONS = (
    EntityDefinition(
        CanonicalEntity(
            entity_type="disease",
            namespace="MONDO",
            identifier="MONDO:0005011",
            label="Crohn disease",
        ),
        (
            "MONDO:0005011",
            "MONDO_0005011",
            "Crohn disease",
            "Crohn's disease",
            "EFO:0000384",
            "EFO_0000384",
        ),
    ),
    EntityDefinition(
        CanonicalEntity(
            entity_type="gene",
            namespace="Ensembl",
            identifier="ENSG00000110944",
            label="IL23A",
        ),
        ("ENSG00000110944", "IL23A"),
    ),
    EntityDefinition(
        CanonicalEntity(
            entity_type="gene",
            namespace="Ensembl",
            identifier="ENSG00000162434",
            label="JAK1",
        ),
        ("ENSG00000162434", "JAK1"),
    ),
    EntityDefinition(
        CanonicalEntity(
            entity_type="gene",
            namespace="Ensembl",
            identifier="ENSG00000181634",
            label="TNFSF15",
        ),
        ("ENSG00000181634", "TNFSF15"),
    ),
    EntityDefinition(
        CanonicalEntity(
            entity_type="gene",
            namespace="Ensembl",
            identifier="ENSG00000167207",
            label="NOD2",
        ),
        ("ENSG00000167207", "NOD2"),
    ),
)

# A small, explicit acceptance panel.  Its score is reported as seed-panel
# precision, never as an estimate of global entity-linking performance.
SEED_PANEL: tuple[tuple[str, str, str], ...] = (
    ("disease", "MONDO:0005011", "MONDO:0005011"),
    ("disease", "MONDO_0005011", "MONDO:0005011"),
    ("disease", "EFO:0000384", "MONDO:0005011"),
    ("disease", "EFO_0000384", "MONDO:0005011"),
    ("disease", "Crohn disease", "MONDO:0005011"),
    ("disease", "Crohn's disease", "MONDO:0005011"),
    ("gene", "IL23A", "ENSG00000110944"),
    ("gene", "ENSG00000110944", "ENSG00000110944"),
    ("gene", "JAK1", "ENSG00000162434"),
    ("gene", "TNFSF15", "ENSG00000181634"),
    ("gene", "NOD2", "ENSG00000167207"),
    ("gene", "ENSG00000167207", "ENSG00000167207"),
)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


class EntityResolver:
    def __init__(self, definitions: tuple[EntityDefinition, ...] = DEFINITIONS):
        self._definitions = definitions
        self._index: dict[tuple[str, str], list[EntityDefinition]] = {}
        for definition in definitions:
            for alias in definition.aliases:
                bucket = self._index.setdefault(
                    (definition.canonical.entity_type, _key(alias)), []
                )
                if definition not in bucket:
                    bucket.append(definition)

    def resolve(
        self,
        value: str,
        entity_type: str,
        snapshot_id: str = DEFAULT_SNAPSHOT_ID,
    ) -> EntityMapping | UnresolvedEntity:
        candidates = self._index.get((entity_type, _key(value)), [])
        natural_key = f"{entity_type}-{_key(value) or 'empty'}"
        if len(candidates) != 1:
            status = MappingStatus.AMBIGUOUS if candidates else MappingStatus.UNRESOLVED
            reason = (
                "multiple reviewed aliases match; human adjudication required"
                if candidates
                else "no exact canonical identifier or reviewed alias"
            )
            return UnresolvedEntity(
                id=stable_id("unresolved", natural_key),
                input_value=value,
                entity_type=entity_type,
                status=status,
                reason=reason,
                candidate_ids=[item.canonical.identifier for item in candidates],
            )

        definition = candidates[0]
        canonical = definition.canonical
        exact = value.casefold() == canonical.identifier.casefold()
        return EntityMapping(
            id=stable_id("mapping", f"{natural_key}-{_key(canonical.identifier)}"),
            input_value=value,
            entity_type=entity_type,
            canonical=canonical,
            status=MappingStatus.EXACT if exact else MappingStatus.CURATED_ALIAS,
            confidence=1.0,
            mapping_method="canonical_identifier" if exact else "reviewed_alias_table_v1",
            snapshot_id=snapshot_id,
        )

    def seed_panel_metrics(self) -> dict[str, float | int]:
        correct = 0
        for entity_type, value, expected in SEED_PANEL:
            result = self.resolve(value, entity_type)
            if isinstance(result, EntityMapping) and result.canonical.identifier == expected:
                correct += 1
        total = len(SEED_PANEL)
        return {
            "correct": correct,
            "total": total,
            "precision": correct / total if total else 0.0,
        }


def default_resolver() -> EntityResolver:
    return EntityResolver()
