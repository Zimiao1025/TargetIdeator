"""Open Targets adapter for the first P1 vertical slice.

The public GraphQL endpoint exposes the current release, not arbitrary historic
releases.  Consequently this adapter labels its capture as a frozen current
subset and sets ``retrospective_claims_allowed`` to false.  Archived Parquet
release ingestion is a later P1 adapter, not something inferred from record
dates in this response.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from targetideator.evidence.models import (
    AvailabilityBasis,
    DatePrecision,
    EntityMapping,
    EvidenceSnapshot,
    SnapshotMode,
    SourceLineage,
    SourceSnapshot,
    TemporalEvidence,
    UnresolvedEntity,
)
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.normalization.entities import default_resolver

ADAPTER_VERSION = "opentargets-graphql-v1"
ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"
RELEASE_VERSION = "26.09"
RELEASE_DATE = date(2026, 9, 24)
RELEASE_URL = "http://ftp.ebi.ac.uk/pub/databases/opentargets/platform/26.09/output/"
SNAPSHOT_ID = "ti:snapshot:opentargets-26.09-crohns-4-targets"
DISEASE_ID = "MONDO_0005011"
TARGET_IDS = (
    "ENSG00000110944",  # IL23A
    "ENSG00000162434",  # JAK1
    "ENSG00000181634",  # TNFSF15
    "ENSG00000167207",  # NOD2
)

QUERY = """query P1Evidence($disease: String!, $targets: [String!]!, $size: Int!, $cursor: String) {
  meta {
    name
    product
    dataPrefix
    apiVersion { x y z suffix }
    dataVersion { year month iteration }
  }
  disease(efoId: $disease) {
    id
    name
    evidences(ensemblIds: $targets, enableIndirect: false, size: $size, cursor: $cursor) {
      cursor
      count
      rows {
        id
        datasourceId
        datatypeId
        score
        evidenceDate
        publicationDate
        publicationYear
        releaseDate
        releaseVersion
        studyStartDate
        studyId
        directionOnTarget
        directionOnTrait
        targetFromSource
        diseaseFromSource
        diseaseFromSourceId
        diseaseFromSourceMappedId
        literature
        urls { url niceName }
        target { id approvedSymbol approvedName }
        disease { id name }
      }
    }
  }
  targets(ensemblIds: $targets) {
    id
    approvedSymbol
    approvedName
    biotype
  }
}"""


class OpenTargetsError(RuntimeError):
    """Raised when the upstream response cannot form a frozen capture."""


def query_sha256() -> str:
    return hashlib.sha256(QUERY.encode("utf-8")).hexdigest()


def capture_live(size: int = 500, captured_at: datetime | None = None) -> dict[str, Any]:
    """Fetch one explicit disease/target subset from the current OT release."""

    if not 1 <= size <= 500:
        raise ValueError("Open Targets evidence page size must be between 1 and 500")
    base_variables = {"disease": DISEASE_ID, "targets": list(TARGET_IDS), "size": size}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    page_cursors: list[str | None] = []
    payload: dict[str, Any] | None = None
    all_rows: list[dict[str, Any]] = []
    source_count: int | None = None
    while True:
        variables = {**base_variables, "cursor": cursor}
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"query": QUERY, "variables": variables}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "TargetIdeator-P1/0.2",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                page = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise OpenTargetsError(f"Open Targets capture failed: {exc}") from exc
        if page.get("errors"):
            raise OpenTargetsError(f"Open Targets returned GraphQL errors: {page['errors']}")
        disease = page.get("data", {}).get("disease")
        if not disease:
            raise OpenTargetsError("Open Targets response does not contain the requested disease")
        evidence = disease["evidences"]
        if payload is None:
            payload = page
            source_count = evidence["count"]
        elif evidence["count"] != source_count:
            raise OpenTargetsError("source count changed while cursor pagination was in progress")
        page_cursors.append(cursor)
        all_rows.extend(evidence["rows"])
        next_cursor = evidence.get("cursor")
        if len(all_rows) >= int(source_count or 0):
            break
        if not next_cursor or next_cursor in seen_cursors:
            raise OpenTargetsError("cursor pagination ended before all evidence was returned")
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    assert payload is not None
    payload["data"]["disease"]["evidences"] = {
        "cursor": None,
        "count": source_count,
        "rows": all_rows,
    }

    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {
        "capture_schema_version": "1.0.0",
        "adapter_version": ADAPTER_VERSION,
        "captured_at": timestamp.isoformat(),
        "endpoint": ENDPOINT,
        "release_version": RELEASE_VERSION,
        "release_date": RELEASE_DATE.isoformat(),
        "release_url": RELEASE_URL,
        "query": QUERY,
        "query_sha256": query_sha256(),
        "variables": {**base_variables, "cursor": None},
        "page_cursors": page_cursors,
        "response": payload,
    }


def _parse_partial_date(value: Any) -> tuple[date | None, DatePrecision]:
    if value is None or value == "":
        return None, DatePrecision.UNKNOWN
    text = str(value).strip()
    try:
        if len(text) == 4:
            return date(int(text), 12, 31), DatePrecision.YEAR
        if len(text) == 7:
            year, month = (int(part) for part in text.split("-"))
            return date(year, month, calendar.monthrange(year, month)[1]), DatePrecision.MONTH
        return date.fromisoformat(text[:10]), DatePrecision.DAY
    except (TypeError, ValueError):
        return None, DatePrecision.UNKNOWN


def _publication_date(row: dict[str, Any]) -> date | None:
    parsed, _ = _parse_partial_date(row.get("publicationDate"))
    if parsed:
        return parsed
    year = row.get("publicationYear")
    parsed, _ = _parse_partial_date(year)
    return parsed


def _record_urls(row: dict[str, Any]) -> list[str]:
    urls = [item.get("url") for item in row.get("urls") or [] if item.get("url")]
    urls.extend(
        f"https://pubmed.ncbi.nlm.nih.gov/{literature_id}/"
        for literature_id in row.get("literature") or []
        if str(literature_id).isdigit()
    )
    if not urls:
        disease_id = row["disease"]["id"]
        target_id = row["target"]["id"]
        urls.append(f"https://platform.opentargets.org/evidence/{disease_id}/{target_id}")
    return list(dict.fromkeys(urls))


def _lineage(row: dict[str, Any]) -> SourceLineage:
    return SourceLineage(
        snapshot_id=SNAPSHOT_ID,
        raw_record_id=row["id"],
        raw_record_sha256=hashlib.sha256(canonical_json_bytes(row)).hexdigest(),
        transform_version=ADAPTER_VERSION,
        field_map={
            "target": "$.target.{id,approvedSymbol}",
            "disease": "$.disease.{id,name}",
            "datasource_id": "$.datasourceId",
            "datatype_id": "$.datatypeId",
            "score": "$.score",
            "event_date": "$.evidenceDate",
            "publication_date": "$.publicationDate|$.publicationYear",
            "study_start_date": "$.studyStartDate",
            "available_on": "capture.release_date (conservative known-presence date)",
            "direction_on_target": "$.directionOnTarget",
            "direction_on_trait": "$.directionOnTrait",
            "source_urls": "$.urls|$.literature|Open Targets association fallback",
        },
    )


def normalize_capture(capture: dict[str, Any], raw_sha256: str) -> EvidenceSnapshot:
    """Deterministically normalize a saved capture into the P1 contract."""

    if capture.get("query_sha256") != query_sha256():
        raise OpenTargetsError("capture query does not match this adapter version")
    if capture.get("release_version") != RELEASE_VERSION:
        raise OpenTargetsError("capture release version does not match configured release")
    data = capture.get("response", {}).get("data", {})
    disease_payload = data.get("disease")
    if not disease_payload:
        raise OpenTargetsError("capture has no disease payload")
    evidence_payload = disease_payload.get("evidences") or {}
    rows = evidence_payload.get("rows") or []
    source_total = int(evidence_payload.get("count") or 0)
    resolver = default_resolver()

    mappings_by_id: dict[str, EntityMapping] = {}
    unresolved_by_id: dict[str, UnresolvedEntity] = {}

    def resolve(value: str, entity_type: str) -> EntityMapping | None:
        result = resolver.resolve(value, entity_type, SNAPSHOT_ID)
        if isinstance(result, EntityMapping):
            mappings_by_id[result.id] = result
            return result
        unresolved_by_id[result.id] = result
        return None

    # Record both identifiers and display labels encountered at the boundary.
    resolve(disease_payload["id"], "disease")
    resolve(disease_payload["name"], "disease")
    for target in data.get("targets") or []:
        resolve(target["id"], "gene")
        resolve(target["approvedSymbol"], "gene")

    records: list[TemporalEvidence] = []
    for row in rows:
        target_mapping = resolve(row["target"]["id"], "gene")
        disease_mapping = resolve(row["disease"]["id"], "disease")
        if target_mapping is None or disease_mapping is None:
            continue
        event_date, precision = _parse_partial_date(row.get("evidenceDate"))
        study_start, _ = _parse_partial_date(row.get("studyStartDate"))
        records.append(
            TemporalEvidence(
                id=stable_id("evidence", f"ot-{row['id']}"),
                target=target_mapping.canonical,
                disease=disease_mapping.canonical,
                datasource_id=row["datasourceId"],
                datatype_id=row["datatypeId"],
                score=row.get("score"),
                evidence_date_raw=row.get("evidenceDate"),
                event_date=event_date,
                event_date_precision=precision,
                publication_date=_publication_date(row),
                study_start_date=study_start,
                # The current API response only proves presence at release time.
                # Earlier event/publication dates are not treated as availability.
                available_on=RELEASE_DATE,
                availability_basis=AvailabilityBasis.SOURCE_RELEASE,
                direction_on_target=row.get("directionOnTarget"),
                direction_on_trait=row.get("directionOnTrait"),
                study_id=row.get("studyId"),
                literature_ids=[str(value) for value in row.get("literature") or []],
                source_urls=_record_urls(row),
                lineage=_lineage(row),
            )
        )

    records.sort(key=lambda record: record.id)
    complete = len(records) == source_total and len(rows) == source_total
    source = SourceSnapshot(
        id=SNAPSHOT_ID,
        source_name="Open Targets Platform",
        release_version=RELEASE_VERSION,
        release_date=RELEASE_DATE,
        captured_at=datetime.fromisoformat(capture["captured_at"]),
        mode=SnapshotMode.FROZEN_CURRENT_SUBSET,
        retrospective_claims_allowed=False,
        api_endpoint=ENDPOINT,
        release_url=RELEASE_URL,
        adapter_version=ADAPTER_VERSION,
        query_sha256=query_sha256(),
        raw_sha256=raw_sha256,
        record_count=len(records),
        source_total_count=source_total,
        complete_for_query=complete,
    )
    return EvidenceSnapshot(
        source=source,
        mappings=sorted(mappings_by_id.values(), key=lambda item: item.id),
        unresolved_entities=sorted(unresolved_by_id.values(), key=lambda item: item.id),
        records=records,
    )
