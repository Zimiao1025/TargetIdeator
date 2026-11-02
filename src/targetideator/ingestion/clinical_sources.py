"""Clinical evidence and trial adapters for P1.3.

The historical path deliberately uses two independently dated sources:

* Open Targets archived ``sourceId=chembl`` Parquet for one evidence string
  per drug/target/disease/trial assertion.
* AACT monthly flat-file archives for one ClinicalTrials.gov study row per
  NCT identifier.

Current ChEMBL and ClinicalTrials.gov APIs are captured only as identifier and
metadata cross-checks.  They are never used to backfill a historical cutoff.
"""

from __future__ import annotations

import csv
import hashlib
import http.client
import io
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from targetideator.ids import canonical_json_bytes
from targetideator.ingestion.opentargets_archive import RELEASES

CLINICAL_ADAPTER_VERSION = "clinical-evidence-trial-v1"
CHEMBL_DATASET = "evidence/sourceId=chembl"
DRUG_MOLECULE_DATASET = "drug_molecule"
DISEASE_IDS = ("EFO_0000384", "MONDO_0005011")
TARGET_IDS = (
    "ENSG00000110944",
    "ENSG00000162434",
    "ENSG00000181634",
    "ENSG00000167207",
)
AACT_SNAPSHOTS = {
    "20250301": date(2025, 3, 1),
    "20250901": date(2025, 9, 1),
}
DOWNLOAD_RETRY_DELAYS_SECONDS = (1.0, 2.0)
RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}

CHEMBL_EVIDENCE_FIELDS = (
    "id",
    "datasourceId",
    "datatypeId",
    "targetId",
    "diseaseId",
    "diseaseFromSource",
    "diseaseFromSourceMappedId",
    "drugId",
    "drugFromSource",
    "clinicalPhase",
    "clinicalStatus",
    "studyId",
    "studyStartDate",
    "studyStopReason",
    "score",
    "urls",
    "literature",
)
CHEMBL_QUERY = """SELECT {fields}, filename
FROM read_parquet($parquet_files, filename = true)
WHERE diseaseId IN ('EFO_0000384', 'MONDO_0005011')
  AND targetId IN ('ENSG00000110944', 'ENSG00000162434',
                   'ENSG00000181634', 'ENSG00000167207')
ORDER BY targetId, drugId, studyId, id""".format(fields=", ".join(CHEMBL_EVIDENCE_FIELDS))
CHEMBL_TRIAL_MAPPING_QUERY = """SELECT {fields}, filename
FROM read_parquet($parquet_files, filename = true)
WHERE studyId IN (SELECT nct_id FROM requested_nct_ids)
ORDER BY studyId, drugId, targetId, id""".format(fields=", ".join(CHEMBL_EVIDENCE_FIELDS))


class ClinicalSourceError(RuntimeError):
    """Raised when a clinical source cannot be captured completely."""


class DownloadIntegrityError(OSError):
    """Raised when a transport reports success for an incomplete archive shard."""


def _utc_timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)


def chembl_archive_url(release_version: str) -> str:
    return (
        "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/"
        f"{release_version}/output/{CHEMBL_DATASET}/"
    )


def opentargets_dataset_url(release_version: str, dataset: str) -> str:
    return (
        "https://ftp.ebi.ac.uk/pub/databases/opentargets/platform/"
        f"{release_version}/output/{dataset}/"
    )


def aact_snapshot_url(snapshot_version: str) -> str:
    return (
        "https://aact.ctti-clinicaltrials.org/static/exported_files/monthly/"
        f"{snapshot_version}_export_ctgov.zip"
    )


def _list_parquet_urls(base: str) -> list[str]:
    request = urllib.request.Request(base, headers={"User-Agent": "TargetIdeator-P1.3/0.5"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            listing = response.read().decode("utf-8")
    except OSError as exc:
        raise ClinicalSourceError(f"unable to list {base}: {exc}") from exc
    names = sorted(set(re.findall(r'href="(part-[^"]+\.parquet)"', listing)))
    if not names:
        raise ClinicalSourceError(f"no Parquet files found at {base}")
    return [base + name for name in names]


def _retryable_download_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS_CODES
    return isinstance(
        exc,
        (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException),
    )


def _validate_download_integrity(
    path: Path,
    url: str,
    content_length: str | None,
) -> None:
    observed_size = path.stat().st_size
    if content_length is not None:
        try:
            expected_size = int(content_length)
        except ValueError:
            expected_size = None
        if expected_size is not None and observed_size != expected_size:
            raise DownloadIntegrityError(
                f"Content-Length mismatch for {url}: expected {expected_size}, "
                f"observed {observed_size}"
            )
    if url.endswith(".parquet"):
        if observed_size < 8:
            raise DownloadIntegrityError(
                f"Parquet shard is too small for header/footer magic: {url}"
            )
        with path.open("rb") as stream:
            header = stream.read(4)
            stream.seek(-4, 2)
            footer = stream.read(4)
        if header != b"PAR1" or footer != b"PAR1":
            raise DownloadIntegrityError(
                f"Parquet header/footer magic mismatch for {url}"
            )


def _download(
    url: str,
    destination: Path,
    *,
    retry_delays: tuple[float, ...] = DOWNLOAD_RETRY_DELAYS_SECONDS,
    sleep=time.sleep,
) -> dict[str, Any]:
    """Download one immutable archive shard with bounded, auditable retries."""

    request = urllib.request.Request(url, headers={"User-Agent": "TargetIdeator-P1.3/0.5"})
    attempt_count = len(retry_delays) + 1
    for attempt in range(1, attempt_count + 1):
        digest = hashlib.sha256()
        partial = destination.with_name(f"{destination.name}.part")
        try:
            with urllib.request.urlopen(request, timeout=180) as response, partial.open(
                "wb"
            ) as out:
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                last_modified = response.headers.get("Last-Modified")
                content_length = response.headers.get("Content-Length")
            _validate_download_integrity(partial, url, content_length)
            partial.replace(destination)
            return {
                "url": url,
                "size_bytes": destination.stat().st_size,
                "sha256": digest.hexdigest(),
                "last_modified": last_modified,
                "attempt_count": attempt,
                "retry_count": attempt - 1,
                "local_path": str(destination),
            }
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            partial.unlink(missing_ok=True)
            if attempt == attempt_count or not _retryable_download_error(exc):
                raise ClinicalSourceError(
                    f"unable to download {url} after {attempt} attempt(s): {exc}"
                ) from exc
            sleep(retry_delays[attempt - 1])
    raise AssertionError("download retry loop exited without a result")


def capture_chembl_evidence_release(
    release_version: str,
    *,
    workers: int = 8,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Completely scan one archived ChEMBL evidence partition and freeze the subset."""

    if release_version not in RELEASES:
        raise ValueError(f"unsupported release {release_version}; expected one of {sorted(RELEASES)}")
    base = chembl_archive_url(release_version)
    urls = _list_parquet_urls(base)
    with tempfile.TemporaryDirectory(prefix=f"targetideator-chembl-{release_version}-") as directory:
        root = Path(directory)

        def download(url: str) -> dict[str, Any]:
            return _download(url, root / url.rsplit("/", 1)[-1])

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            downloaded = list(pool.map(download, urls))
        downloaded.sort(key=lambda item: item["url"])
        paths = [item["local_path"] for item in downloaded]
        url_by_name = {Path(item["local_path"]).name: item["url"] for item in downloaded}
        connection = duckdb.connect()
        try:
            dataset_count = int(
                connection.execute(
                    "SELECT count(*) FROM read_parquet($parquet_files)",
                    {"parquet_files": paths},
                ).fetchone()[0]
            )
            cursor = connection.execute(CHEMBL_QUERY, {"parquet_files": paths})
            columns = [description[0] for description in cursor.description]
            rows: list[dict[str, Any]] = []
            for values in cursor.fetchall():
                row = dict(zip(columns, values, strict=True))
                filename = Path(row.pop("filename")).name
                row["sourceParquetUrl"] = url_by_name[filename]
                rows.append(row)
        finally:
            connection.close()

    if len({row["id"] for row in rows}) != len(rows):
        raise ClinicalSourceError(f"duplicate ChEMBL evidence IDs in release {release_version}")
    if any(not re.fullmatch(r"NCT\d{8}", row.get("studyId") or "") for row in rows):
        raise ClinicalSourceError(f"release {release_version} contains an unmappable trial ID")
    return {
        "capture_schema_version": "3.0.0",
        "adapter_version": CLINICAL_ADAPTER_VERSION,
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "release_version": release_version,
        "release_date": RELEASES[release_version].isoformat(),
        "archive_url": base,
        "dataset": CHEMBL_DATASET,
        "query": CHEMBL_QUERY,
        "query_sha256": hashlib.sha256(CHEMBL_QUERY.encode("utf-8")).hexdigest(),
        "query_scope": {
            "disease_ids": list(DISEASE_IDS),
            "target_ids": list(TARGET_IDS),
            "granularity": "individual_chembl_clinical_evidence",
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


def capture_chembl_trial_mapping_release(
    release_version: str,
    nct_ids: list[str] | set[str] | tuple[str, ...],
    *,
    workers: int = 8,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Scan an archived release for trial→drug→target rows in a frozen NCT cohort."""

    if release_version not in RELEASES:
        raise ValueError(f"unsupported release {release_version}; expected one of {sorted(RELEASES)}")
    requested = sorted(set(nct_ids))
    if not requested or any(not re.fullmatch(r"NCT\d{8}", item) for item in requested):
        raise ValueError("nct_ids must contain valid NCT identifiers")
    base = chembl_archive_url(release_version)
    urls = _list_parquet_urls(base)
    with tempfile.TemporaryDirectory(
        prefix=f"targetideator-chembl-trial-map-{release_version}-"
    ) as directory:
        root = Path(directory)

        def download(url: str) -> dict[str, Any]:
            return _download(url, root / url.rsplit("/", 1)[-1])

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            downloaded = list(pool.map(download, urls))
        downloaded.sort(key=lambda item: item["url"])
        paths = [item["local_path"] for item in downloaded]
        url_by_name = {Path(item["local_path"]).name: item["url"] for item in downloaded}
        connection = duckdb.connect()
        try:
            connection.execute("CREATE TEMP TABLE requested_nct_ids(nct_id VARCHAR PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO requested_nct_ids VALUES (?)", [(item,) for item in requested]
            )
            dataset_count = int(
                connection.execute(
                    "SELECT count(*) FROM read_parquet($parquet_files)",
                    {"parquet_files": paths},
                ).fetchone()[0]
            )
            cursor = connection.execute(
                CHEMBL_TRIAL_MAPPING_QUERY, {"parquet_files": paths}
            )
            columns = [description[0] for description in cursor.description]
            rows = []
            for values in cursor.fetchall():
                row = dict(zip(columns, values, strict=True))
                filename = Path(row.pop("filename")).name
                row["sourceParquetUrl"] = url_by_name[filename]
                rows.append(row)
        finally:
            connection.close()
    mapped_nct_ids = {row["studyId"] for row in rows if row.get("studyId")}
    return {
        "capture_schema_version": "5.3.0",
        "adapter_version": "p5.3-chembl-trial-drug-target-v1",
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "release_version": release_version,
        "release_date": RELEASES[release_version].isoformat(),
        "archive_url": base,
        "dataset": CHEMBL_DATASET,
        "query": CHEMBL_TRIAL_MAPPING_QUERY,
        "query_sha256": hashlib.sha256(
            CHEMBL_TRIAL_MAPPING_QUERY.encode("utf-8")
        ).hexdigest(),
        "query_scope": {
            "requested_nct_count": len(requested),
            "granularity": "individual_chembl_evidence_trial_drug_target_row",
            "use_policy": "identity_and_outcome_provenance_not_model_feature",
        },
        "archive_file_count": len(urls),
        "dataset_row_count": dataset_count,
        "matched_row_count": len(rows),
        "mapped_nct_count": len(mapped_nct_ids),
        "unmapped_nct_count": len(set(requested) - mapped_nct_ids),
        "complete_for_query": len(downloaded) == len(urls),
        "archive_files": [
            {key: value for key, value in item.items() if key != "local_path"}
            for item in downloaded
        ],
        "rows": rows,
    }


def capture_opentargets_drug_dictionary_release(
    release_version: str,
    drug_ids: list[str] | set[str] | tuple[str, ...],
    *,
    workers: int = 4,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture version-matched molecule names for exact cross-source auditing."""

    if release_version not in RELEASES:
        raise ValueError(f"unsupported release {release_version}; expected one of {sorted(RELEASES)}")
    requested = sorted(set(drug_ids))
    if not requested or any(not re.fullmatch(r"CHEMBL\d+", item) for item in requested):
        raise ValueError("drug_ids must contain valid ChEMBL identifiers")
    base = opentargets_dataset_url(release_version, DRUG_MOLECULE_DATASET)
    urls = _list_parquet_urls(base)
    with tempfile.TemporaryDirectory(
        prefix=f"targetideator-drug-dictionary-{release_version}-"
    ) as directory:
        root = Path(directory)

        def download(url: str) -> dict[str, Any]:
            return _download(url, root / url.rsplit("/", 1)[-1])

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            downloaded = list(pool.map(download, urls))
        downloaded.sort(key=lambda item: item["url"])
        paths = [item["local_path"] for item in downloaded]
        connection = duckdb.connect()
        try:
            connection.execute("CREATE TEMP TABLE requested_drug_ids(drug_id VARCHAR PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO requested_drug_ids VALUES (?)", [(item,) for item in requested]
            )
            dataset_count = int(
                connection.execute(
                    "SELECT count(*) FROM read_parquet($parquet_files)",
                    {"parquet_files": paths},
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """SELECT id, name, tradeNames, synonyms, parentId,
                          maximumClinicalTrialPhase, isApproved, hasBeenWithdrawn
                   FROM read_parquet($parquet_files)
                   WHERE id IN (SELECT drug_id FROM requested_drug_ids)
                   ORDER BY id""",
                {"parquet_files": paths},
            )
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]
        finally:
            connection.close()
    captured_ids = {row["id"] for row in rows}
    return {
        "capture_schema_version": "5.3.0",
        "adapter_version": "p5.3-opentargets-drug-dictionary-v1",
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "release_version": release_version,
        "release_date": RELEASES[release_version].isoformat(),
        "archive_url": base,
        "dataset": DRUG_MOLECULE_DATASET,
        "query_scope": {
            "requested_drug_count": len(requested),
            "use_policy": "exact_name_crosscheck_and_display_not_temporal_model_feature",
        },
        "archive_file_count": len(urls),
        "dataset_row_count": dataset_count,
        "matched_drug_count": len(captured_ids),
        "missing_drug_ids": sorted(set(requested) - captured_ids),
        "complete_for_query": len(downloaded) == len(urls),
        "archive_files": [
            {key: value for key, value in item.items() if key != "local_path"}
            for item in downloaded
        ],
        "rows": rows,
    }


def capture_opentargets_full_drug_dictionary_release(
    release_version: str,
    *,
    workers: int = 4,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture the complete versioned molecule identity and hierarchy dictionary."""

    if release_version not in RELEASES:
        raise ValueError(f"unsupported release {release_version}; expected one of {sorted(RELEASES)}")
    base = opentargets_dataset_url(release_version, DRUG_MOLECULE_DATASET)
    urls = _list_parquet_urls(base)
    query = """SELECT id, name, tradeNames, synonyms, parentId, childChemblIds,
                      drugType, maximumClinicalTrialPhase, isApproved, hasBeenWithdrawn
               FROM read_parquet($parquet_files)
               ORDER BY id"""
    with tempfile.TemporaryDirectory(
        prefix=f"targetideator-full-drug-dictionary-{release_version}-"
    ) as directory:
        root = Path(directory)

        def download(url: str) -> dict[str, Any]:
            return _download(url, root / url.rsplit("/", 1)[-1])

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            downloaded = list(pool.map(download, urls))
        downloaded.sort(key=lambda item: item["url"])
        paths = [item["local_path"] for item in downloaded]
        connection = duckdb.connect()
        try:
            cursor = connection.execute(query, {"parquet_files": paths})
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]
        finally:
            connection.close()
    if len({row["id"] for row in rows}) != len(rows):
        raise ClinicalSourceError("full drug dictionary contains duplicate ChEMBL IDs")
    return {
        "capture_schema_version": "5.5.0",
        "adapter_version": "p5.5-opentargets-full-drug-identity-v1",
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "release_version": release_version,
        "release_date": RELEASES[release_version].isoformat(),
        "archive_url": base,
        "dataset": DRUG_MOLECULE_DATASET,
        "query": query,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "query_scope": {
            "scope": "all_drug_molecule_rows",
            "use_policy": (
                "exact_name_and_parent_child_identity_resolution_only_"
                "not_trial_target_mapping_or_temporal_model_feature"
            ),
        },
        "archive_file_count": len(urls),
        "dataset_row_count": len(rows),
        "complete_for_query": len(downloaded) == len(urls),
        "archive_files": [
            {key: value for key, value in item.items() if key != "local_path"}
            for item in downloaded
        ],
        "rows": rows,
    }


class _HTTPRangeReader(io.RawIOBase):
    """Seekable, block-cached reader used by :mod:`zipfile` over HTTP Range."""

    def __init__(self, url: str, *, block_size: int = 16 * 1024 * 1024):
        self.url = url
        self.download_url = url
        self.block_size = block_size
        self.position = 0
        self.cache_start = 0
        self.cache = b""
        headers, _, self.download_url = self._request(0, 0)
        content_range = headers.get("Content-Range")
        if not content_range or "/" not in content_range:
            raise ClinicalSourceError(f"AACT archive does not support byte ranges: {url}")
        self.size = int(content_range.rsplit("/", 1)[-1])
        self.etag = (headers.get("ETag") or "").strip('"') or None
        self.last_modified = headers.get("Last-Modified")

    def _request(self, start: int, end: int) -> tuple[Any, bytes, str]:
        last_error: Exception | None = None
        for attempt in range(4):
            request = urllib.request.Request(
                self.download_url,
                headers={
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "TargetIdeator-P1.3/0.5",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    content_range = response.headers.get("Content-Range")
                    if response.status != 206 or not content_range:
                        raise ClinicalSourceError(
                            "AACT object store ignored byte range "
                            f"{start}-{end}: status={response.status}"
                        )
                    expected = end - start + 1
                    payload = response.read(expected + 1)
                    if len(payload) > expected:
                        raise ClinicalSourceError(
                            f"AACT range response exceeded {expected} requested bytes"
                        )
                    return response.headers, payload, response.geturl()
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After", "unknown")
                    raise ClinicalSourceError(
                        f"AACT download rate-limited; retry-after={retry_after}s: {self.url}"
                    ) from exc
                if attempt < 3:
                    time.sleep(2**attempt)
            except http.client.HTTPException as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2**attempt)
            except OSError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2**attempt)
        raise ClinicalSourceError(f"unable to range-read {self.url}: {last_error}") from last_error

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self.position + offset
        elif whence == io.SEEK_END:
            position = self.size + offset
        else:
            raise ValueError(f"invalid whence: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self.position = position
        return position

    def read(self, size: int = -1) -> bytes:
        if self.position >= self.size:
            return b""
        if size < 0:
            size = self.size - self.position
        requested_end = min(self.size, self.position + size)
        output = bytearray()
        while self.position < requested_end:
            cache_end = self.cache_start + len(self.cache)
            if not (self.cache_start <= self.position < cache_end):
                fetch_end = min(self.size - 1, self.position + self.block_size - 1)
                _, self.cache, _ = self._request(self.position, fetch_end)
                self.cache_start = self.position
                cache_end = self.cache_start + len(self.cache)
            take = min(requested_end, cache_end) - self.position
            offset = self.position - self.cache_start
            output.extend(self.cache[offset : offset + take])
            self.position += take
        return bytes(output)


def capture_aact_snapshot(
    snapshot_version: str,
    nct_ids: list[str] | set[str] | tuple[str, ...],
    *,
    captured_at: datetime | None = None,
    download_url: str | None = None,
) -> dict[str, Any]:
    """Stream ``studies.txt`` from an AACT archive and retain exact matching rows."""

    if snapshot_version not in AACT_SNAPSHOTS:
        raise ValueError(
            f"unsupported AACT snapshot {snapshot_version}; expected one of {sorted(AACT_SNAPSHOTS)}"
        )
    requested = sorted(set(nct_ids))
    if not requested or any(not re.fullmatch(r"NCT\d{8}", item) for item in requested):
        raise ValueError("nct_ids must contain valid NCT identifiers")
    url = aact_snapshot_url(snapshot_version)
    remote = _HTTPRangeReader(download_url or url)
    rows: list[dict[str, str | None]] = []
    dataset_count = 0
    try:
        with zipfile.ZipFile(remote) as archive:
            entry = archive.getinfo("studies.txt")
            with archive.open(entry) as binary:
                text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
                reader = csv.DictReader(text, delimiter="|")
                for row in reader:
                    dataset_count += 1
                    if row.get("nct_id") in requested:
                        rows.append(dict(row))
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error) as exc:
        raise ClinicalSourceError(f"unable to read AACT snapshot {snapshot_version}: {exc}") from exc
    rows.sort(key=lambda item: item.get("nct_id") or "")
    found = {row["nct_id"] for row in rows}
    missing = sorted(set(requested) - found)
    return {
        "capture_schema_version": "3.0.0",
        "adapter_version": CLINICAL_ADAPTER_VERSION,
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "snapshot_version": snapshot_version,
        "snapshot_date": AACT_SNAPSHOTS[snapshot_version].isoformat(),
        "archive_url": url,
        "archive_size_bytes": remote.size,
        "archive_etag": remote.etag,
        "archive_last_modified": remote.last_modified,
        "entry": {
            "name": entry.filename,
            "crc32": f"{entry.CRC:08x}",
            "compressed_size_bytes": entry.compress_size,
            "uncompressed_size_bytes": entry.file_size,
        },
        "dataset_row_count": dataset_count,
        "requested_nct_ids": requested,
        "missing_nct_ids": missing,
        "complete_for_query": not missing and len(rows) == len(requested),
        "rows": rows,
    }


def _get_json(url: str) -> tuple[dict[str, Any], str]:
    request = urllib.request.Request(url, headers={"User-Agent": "TargetIdeator-P1.3/0.5"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = response.read()
    except OSError as exc:
        raise ClinicalSourceError(f"unable to fetch {url}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClinicalSourceError(f"invalid JSON from {url}: {exc}") from exc
    return payload, hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def capture_chembl_molecules(
    drug_ids: list[str] | set[str] | tuple[str, ...],
    *,
    captured_at: datetime | None = None,
    workers: int = 8,
) -> dict[str, Any]:
    """Capture current ChEMBL molecule records for cross-source naming only."""

    identifiers = sorted(set(drug_ids))
    base = "https://www.ebi.ac.uk/chembl/api/data/molecule"
    status_url = "https://www.ebi.ac.uk/chembl/api/data/status.json"
    status_payload, status_digest = _get_json(status_url)

    def fetch(identifier: str) -> dict[str, Any]:
        if not re.fullmatch(r"CHEMBL\d+", identifier):
            raise ValueError(f"invalid ChEMBL molecule ID: {identifier}")
        url = f"{base}/{identifier}.json"
        payload, digest = _get_json(url)
        return {"url": url, "payload_sha256": digest, "payload": payload}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        molecules = list(pool.map(fetch, identifiers))
    molecules.sort(key=lambda item: item["payload"]["molecule_chembl_id"])
    return {
        "capture_schema_version": "3.0.0",
        "adapter_version": CLINICAL_ADAPTER_VERSION,
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "endpoint": base,
        "database_status": {
            "url": status_url,
            "payload_sha256": status_digest,
            "payload": status_payload,
        },
        "use_policy": "current_metadata_enrichment_only",
        "complete_for_query": len(molecules) == len(identifiers),
        "molecules": molecules,
    }


def capture_ctgov_current(
    nct_ids: list[str] | set[str] | tuple[str, ...],
    *,
    captured_at: datetime | None = None,
    workers: int = 8,
) -> dict[str, Any]:
    """Capture compact current ClinicalTrials.gov fields for NCT-ID validation only."""

    identifiers = sorted(set(nct_ids))
    base = "https://clinicaltrials.gov/api/v2/studies"
    version_url = "https://clinicaltrials.gov/api/v2/version"
    version_payload, version_digest = _get_json(version_url)
    if any(not re.fullmatch(r"NCT\d{8}", identifier) for identifier in identifiers):
        raise ValueError("invalid NCT ID")
    parameters = urllib.parse.urlencode(
        {
            "query.id": " OR ".join(identifiers),
            "format": "json",
            "fields": "NCTId,StudyFirstPostDate,LastUpdatePostDate,OverallStatus",
            "pageSize": max(1, len(identifiers)),
        }
    )
    query_url = f"{base}?{parameters}"
    response, _ = _get_json(query_url)
    studies = [
        {
            "url": f"{base}/{payload['protocolSection']['identificationModule']['nctId']}",
            "payload_sha256": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
            "payload": payload,
        }
        for payload in response.get("studies", [])
    ]
    studies.sort(
        key=lambda item: item["payload"]["protocolSection"]["identificationModule"]["nctId"]
    )
    observed = {
        item["payload"]["protocolSection"]["identificationModule"]["nctId"]
        for item in studies
    }
    if observed != set(identifiers):
        raise ClinicalSourceError(
            f"ClinicalTrials.gov identifier mismatch; missing={sorted(set(identifiers) - observed)}"
        )
    return {
        "capture_schema_version": "3.0.0",
        "adapter_version": CLINICAL_ADAPTER_VERSION,
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "endpoint": base,
        "api_status": {
            "url": version_url,
            "payload_sha256": version_digest,
            "payload": version_payload,
        },
        "query_url": query_url,
        "fields": ["NCTId", "StudyFirstPostDate", "LastUpdatePostDate", "OverallStatus"],
        "use_policy": "current_identifier_validation_only",
        "complete_for_query": len(studies) == len(identifiers),
        "studies": studies,
    }
