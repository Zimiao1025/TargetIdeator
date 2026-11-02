"""Capture versioned DrugCentral drug-target assertions and exact ID crosswalks."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from targetideator.ingestion.clinical_sources import (
    _download,
    _list_parquet_urls,
    _utc_timestamp,
    opentargets_dataset_url,
)

DRUGCENTRAL_RELEASE = "2027"
DRUGCENTRAL_RELEASE_DATE = "2026-09-25"
DRUGCENTRAL_INTERACTION_URL = (
    "https://unmtid-dbs.net/download/DrugCentral/2027/"
    "drug.target.interaction.tsv.gz"
)
DRUGCENTRAL_STRUCTURE_URL = (
    "https://unmtid-dbs.net/download/DrugCentral/2027/structures.molV2.sdf.gz"
)
OPENTARGETS_RELEASE = "25.09"


class IndependentSourceCaptureError(RuntimeError):
    """Raised when an independent-source capture is incomplete or ambiguous."""


def _download_bytes(url: str) -> tuple[bytes, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": "TargetIdeator-P5.7/0.17"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
        metadata = {
            "url": response.geturl(),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": (response.headers.get("ETag") or "").strip('"') or None,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return payload, metadata


def _parse_drugcentral_structures(payload: bytes) -> list[dict]:
    try:
        from rdkit import Chem
    except ImportError as exc:  # pragma: no cover - capture-only optional dependency
        raise IndependentSourceCaptureError(
            "DrugCentral structure capture requires rdkit; run with `uv run --with rdkit`"
        ) from exc
    supplier = Chem.ForwardSDMolSupplier(
        io.BytesIO(gzip.decompress(payload)), sanitize=True, removeHs=False
    )
    rows = []
    for source_record_number, molecule in enumerate(supplier, start=1):
        if molecule is None:
            raise IndependentSourceCaptureError(
                f"unable to parse DrugCentral SDF record {source_record_number}"
            )
        structure_id = molecule.GetProp("ID")
        inchi_key = Chem.MolToInchiKey(molecule)
        if not structure_id or not inchi_key:
            raise IndependentSourceCaptureError(
                f"missing structure identity in DrugCentral record {source_record_number}"
            )
        rows.append(
            {
                "source_record_number": source_record_number,
                "structure_id": int(structure_id),
                "preferred_name": molecule.GetProp("PREFERRED_NAME"),
                "inchi_key": inchi_key,
            }
        )
    return rows


def capture_drugcentral_independent_source(
    *, workers: int = 8, captured_at: datetime | None = None
) -> dict[str, Any]:
    """Capture DrugCentral 2027 plus exact structure and protein ID crosswalks."""

    interaction_payload, interaction_archive = _download_bytes(
        DRUGCENTRAL_INTERACTION_URL
    )
    structure_payload, structure_archive = _download_bytes(DRUGCENTRAL_STRUCTURE_URL)
    with gzip.open(io.BytesIO(interaction_payload), "rt", encoding="utf-8", newline="") as stream:
        interactions = []
        for source_row_number, row in enumerate(
            csv.DictReader(stream, delimiter="\t"), start=2
        ):
            interactions.append({"source_row_number": source_row_number, **row})
    structures = _parse_drugcentral_structures(structure_payload)

    datasets = {
        "drug_molecule": opentargets_dataset_url(
            OPENTARGETS_RELEASE, "drug_molecule"
        ),
        "target": opentargets_dataset_url(OPENTARGETS_RELEASE, "target"),
    }
    with tempfile.TemporaryDirectory(prefix="targetideator-independent-crosswalk-") as tmp:
        root = Path(tmp)
        archive_files = []
        local_paths = {}
        for dataset, base in datasets.items():
            urls = _list_parquet_urls(base)
            target_dir = root / dataset
            target_dir.mkdir()

            def download(url: str) -> dict[str, Any]:
                return _download(url, target_dir / url.rsplit("/", 1)[-1])

            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                downloaded = list(pool.map(download, urls))
            downloaded.sort(key=lambda item: item["url"])
            archive_files.extend(
                {"dataset": dataset, **{k: v for k, v in item.items() if k != "local_path"}}
                for item in downloaded
            )
            local_paths[dataset] = [item["local_path"] for item in downloaded]
        connection = duckdb.connect()
        try:
            drug_crosswalk = [
                {"drug_chembl_id": drug_id, "inchi_key": inchi_key}
                for drug_id, inchi_key in connection.execute(
                    "SELECT id, inchiKey FROM read_parquet($paths) "
                    "WHERE inchiKey IS NOT NULL ORDER BY id",
                    {"paths": local_paths["drug_molecule"]},
                ).fetchall()
            ]
            target_crosswalk = [
                {
                    "target_ensembl_id": target_id,
                    "uniprot_swissprot_accession": accession,
                }
                for target_id, accession in connection.execute(
                    "SELECT target.id, protein.id "
                    "FROM read_parquet($paths) target, "
                    "UNNEST(target.proteinIds) AS item(protein) "
                    "WHERE protein.source = 'uniprot_swissprot' "
                    "ORDER BY target.id, protein.id",
                    {"paths": local_paths["target"]},
                ).fetchall()
            ]
        finally:
            connection.close()
    if len({row["structure_id"] for row in structures}) != len(structures):
        raise IndependentSourceCaptureError("duplicate DrugCentral structure IDs")
    return {
        "capture_schema_version": "5.7.0",
        "adapter_version": "p5.7-drugcentral-independent-assertion-v1",
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "independent_source": {
            "name": "DrugCentral",
            "release": DRUGCENTRAL_RELEASE,
            "release_date": DRUGCENTRAL_RELEASE_DATE,
            "download_page": "https://www.drugcentral.org/download",
            "interaction_archive": interaction_archive,
            "structure_archive": structure_archive,
        },
        "identity_crosswalk": {
            "source": "Open Targets Platform",
            "release": OPENTARGETS_RELEASE,
            "release_date": "2025-09-17",
            "policy": (
                "exact_full_inchikey_to_chembl_and_exact_uniprot_swissprot_to_ensembl_"
                "identity_only_not_linkage_evidence"
            ),
            "archive_files": archive_files,
        },
        "interaction_row_count": len(interactions),
        "structure_row_count": len(structures),
        "drug_crosswalk_row_count": len(drug_crosswalk),
        "target_crosswalk_row_count": len(target_crosswalk),
        "interactions": interactions,
        "structures": structures,
        "drug_crosswalk": drug_crosswalk,
        "target_crosswalk": target_crosswalk,
        "complete_for_query": True,
    }
