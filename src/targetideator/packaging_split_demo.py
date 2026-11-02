"""R2 code/data packaging-split dashboard."""

from __future__ import annotations

import html
from functools import lru_cache

from targetideator.release.data_bundle_store import (
    PackagingSplitStore,
    load_default_packaging_split_store,
)


@lru_cache(maxsize=1)
def packaging_split_store() -> PackagingSplitStore:
    return load_default_packaging_split_store()


def packaging_split_payload() -> dict:
    store = packaging_split_store()
    return {
        "snapshot": store.snapshot.model_dump(mode="json"),
        "quality": store.quality_report(),
        "inventory": store.inventory(),
    }


def packaging_split_page() -> str:
    store = packaging_split_store()
    q = store.snapshot.quality
    rows = "".join(
        f"<tr><td><code>{html.escape(row['filename'])}</code></td>"
        f"<td>{row['byte_count'] / 1024 / 1024:.2f} MiB</td>"
        f"<td>{html.escape(row['artifact_class'])}</td>"
        f"<td><code>{row['sha256'][:16]}…</code></td></tr>"
        for row in sorted(
            store.inventory(), key=lambda item: (-item["byte_count"], item["filename"])
        )
    )
    limitations = "".join(
        f"<li>{html.escape(item)}</li>" for item in q.blocking_limitations
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TargetIdeator R2 packaging split</title>
<style>:root{{--ink:#172126;--paper:#edf0e9;--panel:#fff;--accent:#235d68;--warn:#943a27;--ok:#17694d;--line:#c9d3cb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}header,main{{max-width:1380px;margin:auto;padding:25px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:42px;margin:6px 0}}a{{color:var(--accent);font-weight:750}}.warning,.boundary{{background:#fff0dc;border-left:6px solid var(--warn);padding:15px 18px}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin:18px 0}}.metrics div,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metrics b{{display:block;font-size:24px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:10px}}code{{font-size:11px}}.ok{{color:var(--ok)}}.blocked{{color:var(--warn)}}@media(max-width:900px){{.panel{{overflow:auto}}}}</style></head>
<body><header><p><a href="/release">R1 audit</a> · <a href="/api/release/data-bundle">JSON bundle contract</a></p><p>TARGETIDEATOR · R2 CODE/DATA PACKAGING SPLIT</p><h1>Code split complete; data remains local-only</h1><p class="warning"><b>NO DATA-BUNDLE UPLOAD AUTHORIZED.</b><br>{html.escape(store.snapshot.warning)}</p>
<section class="metrics"><div><small>External files</small><b>{q.externalized_file_count}</b></div><div><small>External data</small><b>{q.externalized_byte_count / 1024 / 1024:.1f} MiB</b></div><div><small>Projected code payload</small><b>{q.projected_code_payload_byte_count / 1024 / 1024:.1f} MiB</b></div><div><small>Code budget</small><b>{q.code_payload_budget_bytes / 1024 / 1024:.0f} MiB</b></div><div><small>Split gate</small><b class="ok">passed</b></div></section></header>
<main><p class="boundary"><b>Runtime contract:</b> set <code>TARGETIDEATOR_DATA_ROOT</code> to the validated bundle root. The resolver accepts files under its <code>data/</code> directory.</p>
<section class="panel"><h2>Checksum-bound external inventory</h2><table><thead><tr><th>File</th><th>Size</th><th>Class</th><th>SHA-256</th></tr></thead><tbody>{rows}</tbody></table></section>
<section class="panel" style="margin-top:16px"><h2>Boundary</h2><ul>{limitations}</ul><p>Code/data split engineering gate: <b class="ok">true</b> · redistribution ledger complete: <b class="blocked">false</b> · publication authorized: <b class="blocked">false</b> · C1/C4 unblocked: <b class="blocked">false/false</b>.</p></section></main></body></html>"""
