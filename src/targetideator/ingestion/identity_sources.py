"""Versioned AACT intervention capture for P5.3 identity auditing."""

from __future__ import annotations

import csv
import codecs
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from targetideator.ingestion.clinical_sources import (
    ClinicalSourceError,
    _HTTPRangeReader,
    aact_snapshot_url,
)
from targetideator.ingestion.outcome_sources import (
    LANDMARK_PAIRS,
    _entry_manifest,
    _enum_value,
    write_gzip_capture,
)

IDENTITY_ADAPTER_VERSION = "p5.3-aact-intervention-v1"
THERAPEUTIC_INTERVENTION_TYPES = {
    "DRUG",
    "BIOLOGICAL",
    "COMBINATION_PRODUCT",
    "DIETARY_SUPPLEMENT",
}


def _remote_zip_text_lines(
    remote: _HTTPRangeReader, entry: zipfile.ZipInfo, *, chunk_size: int = 1024 * 1024
):
    """Yield one remote ZIP member without ``ZipExtFile.readall`` allocation."""

    if entry.compress_type != zipfile.ZIP_DEFLATED:
        raise ClinicalSourceError(
            f"unsupported compression for {entry.filename}: {entry.compress_type}"
        )
    remote.seek(entry.header_offset)
    local_header = remote.read(30)
    if len(local_header) != 30 or local_header[:4] != b"PK\x03\x04":
        raise ClinicalSourceError(f"invalid local ZIP header for {entry.filename}")
    filename_length = int.from_bytes(local_header[26:28], "little")
    extra_length = int.from_bytes(local_header[28:30], "little")
    remote.seek(entry.header_offset + 30 + filename_length + extra_length)
    remaining = entry.compress_size
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    decoder = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    crc32 = 0
    uncompressed_size = 0
    while remaining:
        compressed = remote.read(min(chunk_size, remaining))
        if not compressed:
            raise ClinicalSourceError(f"truncated compressed member {entry.filename}")
        remaining -= len(compressed)
        uncompressed = decompressor.decompress(compressed)
        crc32 = zlib.crc32(uncompressed, crc32)
        uncompressed_size += len(uncompressed)
        pending += decoder.decode(uncompressed)
        lines = pending.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            pending = lines.pop()
        else:
            pending = ""
        yield from lines
    tail = decompressor.flush()
    crc32 = zlib.crc32(tail, crc32)
    uncompressed_size += len(tail)
    pending += decoder.decode(tail, final=True)
    if pending:
        yield pending
    if uncompressed_size != entry.file_size:
        raise ClinicalSourceError(
            f"uncompressed size mismatch for {entry.filename}: "
            f"{uncompressed_size} != {entry.file_size}"
        )
    if crc32 != entry.CRC:
        raise ClinicalSourceError(
            f"CRC mismatch for {entry.filename}: {crc32:08x} != {entry.CRC:08x}"
        )


def capture_aact_interventions(
    split: str,
    nct_ids: set[str],
    *,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture baseline intervention names and aliases for a frozen broad cohort."""

    if split not in LANDMARK_PAIRS:
        raise ValueError(f"unknown split {split}")
    baseline_version, _ = LANDMARK_PAIRS[split]
    remote = _HTTPRangeReader(aact_snapshot_url(baseline_version))
    intervention_rows = []
    intervention_ids = set()
    try:
        with zipfile.ZipFile(remote) as archive:
            intervention_entry = archive.getinfo("interventions.txt")
            intervention_source_count = 0
            reader = csv.DictReader(
                _remote_zip_text_lines(remote, intervention_entry), delimiter="|"
            )
            for row in reader:
                intervention_source_count += 1
                if row.get("nct_id") in nct_ids:
                    item = {
                        "intervention_id": row.get("id"),
                        "nct_id": row.get("nct_id"),
                        "intervention_type": _enum_value(row.get("intervention_type")),
                        "name": row.get("name") or None,
                    }
                    intervention_rows.append(item)
                    intervention_ids.add(row.get("id"))
            alias_entry = archive.getinfo("intervention_other_names.txt")
            alias_source_count = 0
            aliases: dict[str, set[str]] = {}
            reader = csv.DictReader(
                _remote_zip_text_lines(remote, alias_entry), delimiter="|"
            )
            for row in reader:
                alias_source_count += 1
                if row.get("intervention_id") in intervention_ids and row.get("name"):
                    aliases.setdefault(row["intervention_id"], set()).add(row["name"])
            intervention_manifest = _entry_manifest(remote, intervention_entry)
            alias_manifest = _entry_manifest(remote, alias_entry)
    except (OSError, zipfile.BadZipFile, KeyError, csv.Error, zlib.error) as exc:
        raise ClinicalSourceError(
            f"unable to capture AACT interventions for {baseline_version}: {exc}"
        ) from exc
    finally:
        remote.close()
    for row in intervention_rows:
        row["aliases"] = sorted(aliases.get(row["intervention_id"], set()))
    intervention_rows.sort(
        key=lambda item: (item["nct_id"], item["intervention_id"] or "")
    )
    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    found_nct = {item["nct_id"] for item in intervention_rows}
    return {
        "capture_schema_version": "5.3.0",
        "adapter_version": IDENTITY_ADAPTER_VERSION,
        "captured_at": timestamp.isoformat(),
        "split": split,
        "baseline_version": baseline_version,
        "cohort_nct_count": len(nct_ids),
        "nct_with_intervention_count": len(found_nct),
        "missing_intervention_nct_ids": sorted(nct_ids - found_nct),
        "eligible_mapping_types": sorted(THERAPEUTIC_INTERVENTION_TYPES),
        "intervention_archive": {
            **intervention_manifest,
            "source_row_count": intervention_source_count,
        },
        "alias_archive": {
            **alias_manifest,
            "source_row_count": alias_source_count,
        },
        "interventions": intervention_rows,
        "complete_for_query": True,
    }


def write_identity_capture(path: Path, capture: dict[str, Any]) -> None:
    write_gzip_capture(str(path), capture)
