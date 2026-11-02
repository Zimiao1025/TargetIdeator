"""Historical AACT landmark-pair capture for temporal outcome modeling."""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from datetime import date, datetime, timezone
from typing import Any

from targetideator.ingestion.clinical_sources import (
    ClinicalSourceError,
    _HTTPRangeReader,
    aact_snapshot_url,
)

OUTCOME_ADAPTER_VERSION = "aact-immune-landmark-outcome-v1"
LANDMARK_PAIRS = {
    "train": ("20230301", "20230901"),
    "validation": ("20240301", "20240901"),
    "test": ("20250301", "20250901"),
}
SNAPSHOT_DATES = {
    version: date(int(version[:4]), int(version[4:6]), int(version[6:]))
    for pair in LANDMARK_PAIRS.values()
    for version in pair
}
ONGOING_STATUSES = {
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING",
}
IMMUNE_CONDITION_PATTERNS = {
    "crohns_disease": re.compile(r"\bcrohn(?:'s|s)?\b", re.IGNORECASE),
    "ulcerative_colitis": re.compile(r"\bulcerative colitis\b", re.IGNORECASE),
    "rheumatoid_arthritis": re.compile(r"\brheumatoid arthritis\b", re.IGNORECASE),
    "psoriasis": re.compile(r"\bpsoriasis\b", re.IGNORECASE),
    "systemic_lupus": re.compile(
        r"\b(?:systemic lupus|lupus erythematosus)\b", re.IGNORECASE
    ),
    "atopic_dermatitis": re.compile(r"\batopic dermatitis\b", re.IGNORECASE),
}

BROAD_BASELINE_FIELDS = (
    "nct_id",
    "phase",
    "overall_status",
    "enrollment",
    "enrollment_type",
    "source_class",
    "number_of_arms",
    "has_dmc",
    "is_fda_regulated_drug",
    "study_first_posted_date",
)
BROAD_OUTCOME_FIELDS = (
    "nct_id",
    "overall_status",
    "why_stopped",
    "completion_date",
    "completion_date_type",
    "study_first_submitted_date",
    "study_first_posted_date",
    "last_update_posted_date",
)


def _timestamp(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _entry_manifest(remote: _HTTPRangeReader, entry: zipfile.ZipInfo) -> dict[str, Any]:
    return {
        "archive_url": remote.url,
        "archive_size_bytes": remote.size,
        "archive_etag": remote.etag,
        "archive_last_modified": remote.last_modified,
        "entry_name": entry.filename,
        "entry_crc32": f"{entry.CRC:08x}",
        "entry_compressed_size_bytes": entry.compress_size,
        "entry_uncompressed_size_bytes": entry.file_size,
    }


def _condition_memberships(
    archive: zipfile.ZipFile,
) -> tuple[dict[str, list[str]], int, zipfile.ZipInfo]:
    entry = archive.getinfo("conditions.txt")
    memberships: dict[str, set[str]] = {}
    row_count = 0
    with archive.open(entry) as binary:
        reader = csv.DictReader(
            io.TextIOWrapper(binary, encoding="utf-8", newline=""), delimiter="|"
        )
        for row in reader:
            row_count += 1
            name = row.get("downcase_name") or row.get("name") or ""
            matched = [
                label
                for label, pattern in IMMUNE_CONDITION_PATTERNS.items()
                if pattern.search(name)
            ]
            if matched and row.get("nct_id"):
                memberships.setdefault(row["nct_id"], set()).update(matched)
    return (
        {key: sorted(values) for key, values in memberships.items()},
        row_count,
        entry,
    )


def _eligible_phase(value: str | None) -> bool:
    phase = re.sub(r"[^A-Z0-9]+", "", (value or "").upper())
    return "PHASE2" in phase or "PHASE3" in phase


def _enum_value(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def capture_landmark_pair(
    split: str,
    *,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture one baseline cohort and its fixed six-month AACT outcome snapshot."""

    if split not in LANDMARK_PAIRS:
        raise ValueError(f"unknown split {split}; expected one of {sorted(LANDMARK_PAIRS)}")
    baseline_version, outcome_version = LANDMARK_PAIRS[split]
    baseline_remote = _HTTPRangeReader(aact_snapshot_url(baseline_version))
    baseline_rows: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(baseline_remote) as archive:
            memberships, condition_count, condition_entry = _condition_memberships(archive)
            studies_entry = archive.getinfo("studies.txt")
            study_count = 0
            with archive.open(studies_entry) as binary:
                reader = csv.DictReader(
                    io.TextIOWrapper(binary, encoding="utf-8", newline=""), delimiter="|"
                )
                for row in reader:
                    study_count += 1
                    nct_id = row.get("nct_id")
                    if (
                        nct_id in memberships
                        and _enum_value(row.get("study_type")) == "INTERVENTIONAL"
                        and _enum_value(row.get("overall_status")) in ONGOING_STATUSES
                        and _eligible_phase(row.get("phase"))
                    ):
                        item = dict(row)
                        item["indication_groups"] = memberships[nct_id]
                        baseline_rows.append(item)
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error) as exc:
        raise ClinicalSourceError(
            f"unable to capture AACT landmark {baseline_version}: {exc}"
        ) from exc
    baseline_rows.sort(key=lambda item: item["nct_id"])
    requested = {item["nct_id"] for item in baseline_rows}

    outcome_remote = _HTTPRangeReader(aact_snapshot_url(outcome_version))
    outcome_rows: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(outcome_remote) as archive:
            outcome_entry = archive.getinfo("studies.txt")
            outcome_study_count = 0
            with archive.open(outcome_entry) as binary:
                reader = csv.DictReader(
                    io.TextIOWrapper(binary, encoding="utf-8", newline=""), delimiter="|"
                )
                for row in reader:
                    outcome_study_count += 1
                    if row.get("nct_id") in requested:
                        outcome_rows.append(dict(row))
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error) as exc:
        raise ClinicalSourceError(
            f"unable to capture AACT outcome {outcome_version}: {exc}"
        ) from exc
    outcome_rows.sort(key=lambda item: item["nct_id"])
    found = {item["nct_id"] for item in outcome_rows}
    return {
        "capture_schema_version": "5.1.0",
        "adapter_version": OUTCOME_ADAPTER_VERSION,
        "captured_at": _timestamp(captured_at).isoformat(),
        "split": split,
        "baseline_version": baseline_version,
        "baseline_date": SNAPSHOT_DATES[baseline_version].isoformat(),
        "outcome_version": outcome_version,
        "outcome_date": SNAPSHOT_DATES[outcome_version].isoformat(),
        "horizon_days": (
            SNAPSHOT_DATES[outcome_version] - SNAPSHOT_DATES[baseline_version]
        ).days,
        "query_scope": {
            "study_type": "INTERVENTIONAL",
            "phases": ["PHASE2", "PHASE2/PHASE3", "PHASE3"],
            "baseline_statuses": sorted(ONGOING_STATUSES),
            "indication_groups": sorted(IMMUNE_CONDITION_PATTERNS),
        },
        "baseline_archive": {
            **_entry_manifest(baseline_remote, studies_entry),
            "studies_row_count": study_count,
            "conditions_row_count": condition_count,
            "conditions_entry": {
                key: value
                for key, value in _entry_manifest(
                    baseline_remote, condition_entry
                ).items()
                if key.startswith("entry_")
            },
        },
        "outcome_archive": {
            **_entry_manifest(outcome_remote, outcome_entry),
            "studies_row_count": outcome_study_count,
        },
        "baseline_rows": baseline_rows,
        "outcome_rows": outcome_rows,
        "missing_outcome_nct_ids": sorted(requested - found),
        "complete_for_query": len(found) == len(requested),
    }


def _project(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) or None for field in fields}


def capture_broad_landmark_pair(
    split: str,
    *,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture a projected all-indication Phase II/III landmark pair."""

    if split not in LANDMARK_PAIRS:
        raise ValueError(f"unknown split {split}; expected one of {sorted(LANDMARK_PAIRS)}")
    baseline_version, outcome_version = LANDMARK_PAIRS[split]
    baseline_remote = _HTTPRangeReader(aact_snapshot_url(baseline_version))
    baseline_rows: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(baseline_remote) as archive:
            studies_entry = archive.getinfo("studies.txt")
            study_count = 0
            with archive.open(studies_entry) as binary:
                reader = csv.DictReader(
                    io.TextIOWrapper(binary, encoding="utf-8", newline=""),
                    delimiter="|",
                )
                for row in reader:
                    study_count += 1
                    if (
                        _enum_value(row.get("study_type")) == "INTERVENTIONAL"
                        and _enum_value(row.get("overall_status")) in ONGOING_STATUSES
                        and _eligible_phase(row.get("phase"))
                    ):
                        baseline_rows.append(_project(row, BROAD_BASELINE_FIELDS))
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error) as exc:
        raise ClinicalSourceError(
            f"unable to capture broad AACT landmark {baseline_version}: {exc}"
        ) from exc
    baseline_rows.sort(key=lambda item: item["nct_id"])
    requested = {item["nct_id"] for item in baseline_rows}

    outcome_remote = _HTTPRangeReader(aact_snapshot_url(outcome_version))
    outcome_rows: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(outcome_remote) as archive:
            outcome_entry = archive.getinfo("studies.txt")
            outcome_study_count = 0
            with archive.open(outcome_entry) as binary:
                reader = csv.DictReader(
                    io.TextIOWrapper(binary, encoding="utf-8", newline=""),
                    delimiter="|",
                )
                for row in reader:
                    outcome_study_count += 1
                    if row.get("nct_id") in requested:
                        outcome_rows.append(_project(row, BROAD_OUTCOME_FIELDS))
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error) as exc:
        raise ClinicalSourceError(
            f"unable to capture broad AACT outcome {outcome_version}: {exc}"
        ) from exc
    outcome_rows.sort(key=lambda item: item["nct_id"])
    found = {item["nct_id"] for item in outcome_rows}
    return {
        "capture_schema_version": "5.2.0",
        "adapter_version": f"{OUTCOME_ADAPTER_VERSION}-broad-projected-v1",
        "captured_at": _timestamp(captured_at).isoformat(),
        "split": split,
        "baseline_version": baseline_version,
        "baseline_date": SNAPSHOT_DATES[baseline_version].isoformat(),
        "outcome_version": outcome_version,
        "outcome_date": SNAPSHOT_DATES[outcome_version].isoformat(),
        "horizon_days": (
            SNAPSHOT_DATES[outcome_version] - SNAPSHOT_DATES[baseline_version]
        ).days,
        "query_scope": {
            "study_type": "INTERVENTIONAL",
            "phase_policy": "contains_phase2_or_phase3",
            "baseline_statuses": sorted(ONGOING_STATUSES),
            "indications": "all",
            "baseline_projection": list(BROAD_BASELINE_FIELDS),
            "outcome_projection": list(BROAD_OUTCOME_FIELDS),
        },
        "baseline_archive": {
            **_entry_manifest(baseline_remote, studies_entry),
            "studies_row_count": study_count,
        },
        "outcome_archive": {
            **_entry_manifest(outcome_remote, outcome_entry),
            "studies_row_count": outcome_study_count,
        },
        "baseline_rows": baseline_rows,
        "outcome_rows": outcome_rows,
        "missing_outcome_nct_ids": sorted(requested - found),
        "complete_for_query": len(found) == len(requested),
    }


def write_gzip_capture(path: str, capture: dict[str, Any]) -> None:
    """Write a deterministic compressed JSON source capture."""

    payload = json.dumps(
        capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with open(path, "wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            compressed.write(payload)
