"""Stable, content-addressable identifiers used by the P0 contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ID_PATTERN = re.compile(r"^ti:[a-z][a-z0-9_-]*:[a-z0-9][a-z0-9._-]*$")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value deterministically."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def stable_id(kind: str, natural_key: str) -> str:
    """Build a readable stable ID from an immutable natural key."""

    normalized_kind = re.sub(r"[^a-z0-9_-]+", "-", kind.lower()).strip("-")
    normalized_key = re.sub(r"[^a-z0-9._-]+", "-", natural_key.lower()).strip("-")
    identifier = f"ti:{normalized_kind}:{normalized_key}"
    if not ID_PATTERN.fullmatch(identifier):
        raise ValueError(f"Cannot build a stable ID from {kind!r}, {natural_key!r}")
    return identifier
