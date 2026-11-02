"""Europe PMC capture and deterministic passage normalization for P2.2."""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any

from targetideator.ids import canonical_json_bytes

EUROPE_PMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
LITERATURE_CAPTURE_VERSION = "europepmc-abstract-capture-v1"
PARAGRAPH_NORMALIZATION_VERSION = "abstract-html-to-text-v1"
CAPTURE_CUTOFF = date(2025, 9, 17)
TARGET_QUOTAS = {"IL23A": 13, "JAK1": 13, "TNFSF15": 12, "NOD2": 12}
TARGET_ALIASES = {
    "IL23A": ("il23a", "il-23", "il 23", "interleukin-23", "interleukin 23"),
    "JAK1": ("jak1", "jak-1", "janus kinase 1"),
    "TNFSF15": ("tnfsf15", "tl1a", "tl-1a", "tnf-like ligand 1a"),
    "NOD2": ("nod2", "card15"),
}
TARGET_QUERY = {
    "IL23A": '(TITLE_ABS:IL23A OR TITLE_ABS:"IL-23" OR TITLE_ABS:"interleukin-23")',
    "JAK1": '(TITLE_ABS:JAK1 OR TITLE_ABS:"Janus kinase 1")',
    "TNFSF15": '(TITLE_ABS:TNFSF15 OR TITLE_ABS:TL1A OR TITLE_ABS:"TL-1A")',
    "NOD2": '(TITLE_ABS:NOD2 OR TITLE_ABS:CARD15)',
}
DISEASE_QUERY = '(TITLE_ABS:"Crohn" OR TITLE_ABS:"inflammatory bowel disease")'


class LiteratureCaptureError(RuntimeError):
    """Raised when a balanced literature capture cannot be completed."""


def _utc_timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)


def normalize_abstract(value: str) -> str:
    """Convert Europe PMC's small abstract HTML subset into stable plain text."""

    with_breaks = re.sub(r"</?(?:h\d|p|br)[^>]*>", " ", value, flags=re.IGNORECASE)
    without_tags = re.sub(r"<[^>]+>", " ", with_breaks)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """Return conservative sentence spans without changing the paragraph text."""

    boundaries = [0]
    for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text):
        boundaries.append(match.end())
    boundaries.append(len(text))
    spans: list[tuple[int, int, str]] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end - start >= 35:
            spans.append((start, end, text[start:end]))
    return spans


def _query_for(target: str) -> str:
    return (
        f"{DISEASE_QUERY} AND {TARGET_QUERY[target]} AND HAS_ABSTRACT:Y AND LANG:eng "
        f"AND FIRST_PDATE:[1900-01-01 TO {CAPTURE_CUTOFF.isoformat()}]"
    )


def _search(target: str, *, page_size: int = 100) -> tuple[dict[str, Any], str]:
    query = _query_for(target)
    url = EUROPE_PMC_SEARCH + "?" + urllib.parse.urlencode(
        {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": page_size,
            "sort": "CITED desc",
        }
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TargetIdeator-P2.2/0.6 (versioned literature prototype)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response), response.geturl()
    except (OSError, json.JSONDecodeError) as exc:
        raise LiteratureCaptureError(f"unable to query Europe PMC for {target}: {exc}") from exc


def _has_target(record: dict[str, Any], target: str) -> bool:
    text = normalize_abstract(
        f"{record.get('title') or ''} {record.get('abstractText') or ''}"
    ).casefold()
    return any(alias in text for alias in TARGET_ALIASES[target])


def _publication_date(record: dict[str, Any]) -> date | None:
    for value in (
        record.get("firstPublicationDate"),
        record.get("electronicPublicationDate"),
        record.get("dateOfCreation"),
    ):
        if value:
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
    return None


def capture_europepmc_corpus(*, captured_at: datetime | None = None) -> dict[str, Any]:
    """Capture a balanced 50-document abstract corpus for the four-target panel."""

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    routes: list[dict[str, Any]] = []
    api_versions: set[str] = set()
    for target, quota in TARGET_QUOTAS.items():
        payload, url = _search(target)
        api_versions.add(str(payload["version"]))
        target_selected: list[dict[str, Any]] = []
        for rank, record in enumerate(payload["resultList"]["result"], start=1):
            source = str(record.get("source") or "MED")
            identifier = str(record.get("id") or "")
            key = (source, identifier)
            publication_date = _publication_date(record)
            abstract = normalize_abstract(record.get("abstractText") or "")
            if (
                not identifier
                or key in seen
                or publication_date is None
                or publication_date > CAPTURE_CUTOFF
                or not _has_target(record, target)
                or len(sentence_spans(abstract)) < 3
            ):
                continue
            target_selected.append(
                {
                    "assigned_target": target,
                    "selection_rank": rank,
                    "raw_record_sha256": hashlib.sha256(
                        canonical_json_bytes(record)
                    ).hexdigest(),
                    "record": record,
                }
            )
            seen.add(key)
            if len(target_selected) == quota:
                break
        if len(target_selected) != quota:
            raise LiteratureCaptureError(
                f"Europe PMC route {target} yielded {len(target_selected)}/{quota} eligible documents"
            )
        selected.extend(target_selected)
        routes.append(
            {
                "target_label": target,
                "query": _query_for(target),
                "api_url": url,
                "hit_count": int(payload["hitCount"]),
                "selected_count": len(target_selected),
            }
        )
    if len(api_versions) != 1 or len(selected) != sum(TARGET_QUOTAS.values()):
        raise LiteratureCaptureError("Europe PMC capture is incomplete or mixes API versions")
    return {
        "capture_schema_version": "2.2.0",
        "capture_adapter_version": LITERATURE_CAPTURE_VERSION,
        "captured_at": _utc_timestamp(captured_at).isoformat(),
        "capture_cutoff": CAPTURE_CUTOFF.isoformat(),
        "source_api_version": api_versions.pop(),
        "query_routes": routes,
        "documents": selected,
    }
