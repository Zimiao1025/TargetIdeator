"""Archived Open Targets Parquet adapter for temporal replay.

The adapter scans every file in ``association_by_datasource_direct`` for each
configured release, then freezes only the Crohn disease × four-target subset.
The resulting timeline represents release membership of datasource-level
associations.  It does not pretend that an aggregated association row is an
individual evidence string.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from targetideator.evidence.models import (
    ArchiveFile,
    ArchiveRelease,
    EntityMapping,
    HistoricalEvidenceSnapshot,
    ReleaseAssociation,
    UnresolvedEntity,
)
from targetideator.ids import canonical_json_bytes, stable_id
from targetideator.normalization.entities import default_resolver

ADAPTER_VERSION = "opentargets-archive-association-v1"
DATASET = "association_by_datasource_direct"
SNAPSHOT_ID = "ti:snapshot:opentargets-archive-25.03-25.09-crohns-4-targets"
RELEASES = {
    "25.03": date(2025, 3, 19),
    "25.09": date(2025, 9, 17),
}
DISEASE_IDS = ("EFO_0000384", "MONDO_0005011")
TARGET_IDS = (
    "ENSG00000110944",
    "ENSG00000162434",
    "ENSG00000181634",
    "ENSG00000167207",
)
QUERY = """SELECT datatypeId, datasourceId, diseaseId, targetId, score,
       evidenceCount, filename
FROM read_parquet($parquet_files, filename = true)
WHERE diseaseId IN ('EFO_0000384', 'MONDO_0005011')
  AND targetId IN ('ENSG00000110944', 'ENSG00000162434',
                   'ENSG00000181634', 'ENSG00000167207')
ORDER BY diseaseId, targetId, datasourceId"""


class OpenTargetsArchiveError(RuntimeError):
    """Raised when a release cannot be captured completely."""


def query_sha256() -> str:
    return hashlib.sha256(QUERY.encode("utf-8")).hexdigest()


def archive_url(release_version: str) -> str:
    return (
        "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/"
        f"{release_version}/output/{DATASET}/"
    )


def _list_parquet_urls(release_version: str) -> list[str]:
    base = archive_url(release_version)
    try:
        with urllib.request.urlopen(base, timeout=60) as response:
            listing = response.read().decode("utf-8")
    except OSError as exc:
        raise OpenTargetsArchiveError(f"unable to list {base}: {exc}") from exc
    names = sorted(set(re.findall(r'href="(part-[^"]+\.parquet)"', listing)))
    if not names:
        raise OpenTargetsArchiveError(f"no Parquet files found at {base}")
    return [base + name for name in names]


def _download_file(url: str, destination: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "TargetIdeator-P1.2/0.3"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
            last_modified = response.headers.get("Last-Modified")
    except OSError as exc:
        raise OpenTargetsArchiveError(f"unable to download {url}: {exc}") from exc
    return {
        "url": url,
        "size_bytes": destination.stat().st_size,
        "sha256": digest.hexdigest(),
        "last_modified": last_modified,
        "local_path": str(destination),
    }


def _scan_parquet(files: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    paths = [item["local_path"] for item in files]
    url_by_name = {Path(item["local_path"]).name: item["url"] for item in files}
    connection = duckdb.connect()
    try:
        dataset_count = connection.execute(
            "SELECT count(*) FROM read_parquet($parquet_files)",
            {"parquet_files": paths},
        ).fetchone()[0]
        cursor = connection.execute(QUERY, {"parquet_files": paths})
        columns = [description[0] for description in cursor.description]
        rows = []
        for values in cursor.fetchall():
            row = dict(zip(columns, values, strict=True))
            filename = Path(row.pop("filename")).name
            row["sourceParquetUrl"] = url_by_name[filename]
            rows.append(row)
    finally:
        connection.close()
    return int(dataset_count), rows


def capture_archived_release(
    release_version: str,
    *,
    workers: int = 8,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Download, completely scan, and freeze one release-specific subset."""

    if release_version not in RELEASES:
        raise ValueError(f"unsupported release {release_version}; expected one of {sorted(RELEASES)}")
    urls = _list_parquet_urls(release_version)
    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix=f"targetideator-{release_version}-") as directory:
        root = Path(directory)

        def download(url: str) -> dict[str, Any]:
            return _download_file(url, root / url.rsplit("/", 1)[-1])

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            downloaded = list(pool.map(download, urls))
        downloaded.sort(key=lambda item: item["url"])
        dataset_count, rows = _scan_parquet(downloaded)

    return {
        "capture_schema_version": "2.0.0",
        "adapter_version": ADAPTER_VERSION,
        "captured_at": timestamp.isoformat(),
        "release_version": release_version,
        "release_date": RELEASES[release_version].isoformat(),
        "archive_url": archive_url(release_version),
        "dataset": DATASET,
        "query": QUERY,
        "query_sha256": query_sha256(),
        "query_scope": {
            "disease_ids": list(DISEASE_IDS),
            "target_ids": list(TARGET_IDS),
            "granularity": "datasource_level_direct_association",
        },
        "archive_file_count": len(urls),
        "dataset_row_count": dataset_count,
        "complete_for_query": len(downloaded) == len(urls),
        "archive_files": [
            {key: value for key, value in item.items() if key != "local_path"}
            for item in downloaded
        ],
        "rows": rows,
    }


def _association_url(disease_id: str, target_id: str) -> str:
    api_disease = disease_id.replace(":", "_")
    return f"https://platform.opentargets.org/evidence/{api_disease}/{target_id}"


def normalize_archived_captures(
    captures: list[dict[str, Any]],
    raw_sha256_by_release: dict[str, str],
) -> HistoricalEvidenceSnapshot:
    """Build a release-membership timeline from saved raw subset captures."""

    if len(captures) < 2:
        raise OpenTargetsArchiveError("at least two archived releases are required")
    captures = sorted(captures, key=lambda item: item["release_date"])
    if len({capture["release_version"] for capture in captures}) != len(captures):
        raise OpenTargetsArchiveError("release versions must be unique")
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

    membership_first_seen: dict[str, tuple[str, date]] = {}
    for capture in captures:
        if capture.get("query_sha256") != query_sha256():
            raise OpenTargetsArchiveError("capture query does not match the archive adapter")
        version = capture["release_version"]
        if version not in RELEASES or capture["release_date"] != RELEASES[version].isoformat():
            raise OpenTargetsArchiveError(f"release metadata mismatch for {version}")
        release_date = RELEASES[version]
        for row in capture["rows"]:
            disease = resolve(row["diseaseId"], "disease")
            target = resolve(row["targetId"], "gene")
            if disease is None or target is None:
                continue
            membership = stable_id(
                "membership",
                f"{disease.canonical.identifier}-{target.canonical.identifier}-{row['datasourceId']}",
            )
            membership_first_seen.setdefault(membership, (version, release_date))

    earliest_capture_date = RELEASES[captures[0]["release_version"]]
    releases: list[ArchiveRelease] = []
    records: list[ReleaseAssociation] = []
    for capture in captures:
        version = capture["release_version"]
        release_date = RELEASES[version]
        release_id = stable_id("release", f"opentargets-{version}")
        normalized_count = 0
        for row in capture["rows"]:
            disease = resolve(row["diseaseId"], "disease")
            target = resolve(row["targetId"], "gene")
            if disease is None or target is None:
                continue
            membership = stable_id(
                "membership",
                f"{disease.canonical.identifier}-{target.canonical.identifier}-{row['datasourceId']}",
            )
            first_version, first_date = membership_first_seen[membership]
            raw_row = {
                "datatypeId": row["datatypeId"],
                "datasourceId": row["datasourceId"],
                "diseaseId": row["diseaseId"],
                "targetId": row["targetId"],
                "score": row["score"],
                "evidenceCount": row["evidenceCount"],
                "sourceParquetUrl": row["sourceParquetUrl"],
            }
            records.append(
                ReleaseAssociation(
                    id=stable_id("association", f"ot-{version}-{membership.rsplit(':', 1)[-1]}"),
                    membership_key=membership,
                    release_id=release_id,
                    release_version=version,
                    release_date=release_date,
                    target=target.canonical,
                    disease=disease.canonical,
                    datatype_id=row["datatypeId"],
                    datasource_id=row["datasourceId"],
                    score=float(row["score"]),
                    evidence_count=int(row["evidenceCount"]),
                    first_observed_release=first_version,
                    first_observed_on=first_date,
                    first_observation_left_censored=first_date == earliest_capture_date,
                    source_parquet_url=row["sourceParquetUrl"],
                    association_url=_association_url(
                        disease.canonical.identifier, target.canonical.identifier
                    ),
                    raw_row_sha256=hashlib.sha256(canonical_json_bytes(raw_row)).hexdigest(),
                    transform_version=ADAPTER_VERSION,
                    field_map={
                        "target": "$.targetId",
                        "disease": "$.diseaseId",
                        "datatype_id": "$.datatypeId",
                        "datasource_id": "$.datasourceId",
                        "score": "$.score",
                        "evidence_count": "$.evidenceCount",
                        "release_date": "capture.release_date",
                        "source_parquet_url": "$.sourceParquetUrl",
                    },
                )
            )
            normalized_count += 1
        releases.append(
            ArchiveRelease(
                id=release_id,
                version=version,
                release_date=release_date,
                archive_url=capture["archive_url"],
                dataset=DATASET,
                captured_at=datetime.fromisoformat(capture["captured_at"]),
                raw_sha256=raw_sha256_by_release[version],
                archive_files=[ArchiveFile.model_validate(item) for item in capture["archive_files"]],
                dataset_row_count=capture["dataset_row_count"],
                subset_row_count=normalized_count,
                complete_for_query=bool(capture["complete_for_query"]),
            )
        )

    records.sort(key=lambda item: (item.release_date, item.membership_key))
    return HistoricalEvidenceSnapshot(
        id=SNAPSHOT_ID,
        scope="Crohn disease × IL23A/JAK1/TNFSF15/NOD2 direct datasource associations",
        adapter_version=ADAPTER_VERSION,
        query_sha256=query_sha256(),
        releases=releases,
        mappings=sorted(mappings_by_id.values(), key=lambda item: item.id),
        unresolved_entities=sorted(unresolved_by_id.values(), key=lambda item: item.id),
        records=records,
    )
