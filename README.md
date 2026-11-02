# TargetIdeator

TargetIdeator is an auditable research prototype for evidence-grounded drug
target ideation. It combines versioned evidence ingestion, claim graphs,
fixed-taxonomy falsification, multi-head decision support, temporal outcome
analysis, source-asserted trial/drug/target mappings, and robustness controls.

- Release: `v0.32.0`
- Python: `>=3.11`
- License: Apache-2.0

## Scientific boundary

This release is a reproducible software artifact, not a clinically validated
target-discovery product. It does not provide medical advice, establish target
causality, or unlock the project's C1/C4 scientific claims. The included
`crohns_seed.json` file is synthetic demonstration data.

## Install and run

With [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/Zimiao1025/TargetIdeator.git
cd TargetIdeator
git checkout v0.32.0
uv sync --frozen
uv run targetideator validate
uv run targetideator serve --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The synthetic P0 dossier works without external
data. Evidence, literature, outcome, mapping and full health endpoints require
an operator-provided data root:

```bash
export TARGETIDEATOR_DATA_ROOT=/absolute/path/to/targetideator-data
uv run targetideator serve --host 0.0.0.0 --port 8000
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for wheel installation, service deployment,
data mounting and smoke checks.

## Data is deliberately not bundled

The Git repository, wheel and source distribution do not contain Open Targets,
ChEMBL, ClinicalTrials.gov/AACT, Europe PMC or DrugCentral records or derived
research artifacts. Upstream data must be acquired and governed separately.
The exact release decisions and attribution requirements are recorded in
[DATA_REDISTRIBUTION_LEDGER.md](DATA_REDISTRIBUTION_LEDGER.md).

This separation is intentional:

- the Apache-2.0 project license covers original TargetIdeator code only;
- upstream licences and article-level copyrights are not overwritten;
- local data roots are never uploaded by the package or server;
- `TARGETIDEATOR_DATA_ROOT` is explicit and read-only during normal serving.

## Repository contents

- `src/targetideator/`: installable application and CLI source;
- `src/targetideator/fixtures/crohns_seed.json`: synthetic demonstration seed;
- `DEPLOYMENT.md`: deployment and smoke-check instructions;
- `DATA_REDISTRIBUTION_LEDGER.md`: source-by-source distribution decisions;
- `CITATION.cff`: citation metadata;
- `LICENSE` and `NOTICE`: Apache License 2.0 and copyright notice;
- `pyproject.toml` and `uv.lock`: reproducible package metadata and dependency lock.

Development outputs, expert-review files, raw data, replay staging directories,
test caches and historical wheels are intentionally absent from version control.

## Cite

Use the repository's [CITATION.cff](CITATION.cff). GitHub exposes it through the
“Cite this repository” action.

## Security and intended use

The server is a read-only research demo and has no built-in authentication or
TLS termination. Bind to localhost for individual use, or place it behind an
authenticated reverse proxy for shared deployments. Do not expose governed
data roots through a static file server.
