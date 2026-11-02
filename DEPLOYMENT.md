# TargetIdeator deployment

These instructions deploy the code-only `v0.32.0` release. External research
data is not distributed with the repository or Python package.

## 1. Prerequisites

- Linux or another Python 3.11+ environment;
- `git`;
- `uv` for locked dependency installation;
- an optional, separately governed TargetIdeator data root for the full demo.

## 2. Deploy from the tagged source

```bash
git clone --branch v0.32.0 --depth 1 \
  https://github.com/Zimiao1025/TargetIdeator.git
cd TargetIdeator
uv sync --frozen
uv run targetideator validate
uv run targetideator show-seed
```

Start the synthetic, code-only demo:

```bash
uv run targetideator serve --host 127.0.0.1 --port 8000
curl --fail http://127.0.0.1:8000/
```

The aggregate `/health` endpoint intentionally requires the full governed data
root and is not a code-only liveness probe.

## 3. Deploy a built wheel

Build from the tag:

```bash
uv build --wheel --sdist
sha256sum dist/targetideator-0.32.0-*.whl \
  dist/targetideator-0.32.0.tar.gz
```

Install in an isolated environment:

```bash
uv venv /opt/targetideator/.venv --python 3.11
uv pip install --python /opt/targetideator/.venv/bin/python \
  dist/targetideator-0.32.0-py3-none-any.whl
/opt/targetideator/.venv/bin/targetideator validate
```

Run the service:

```bash
/opt/targetideator/.venv/bin/targetideator serve \
  --host 127.0.0.1 --port 8000
```

## 4. Mount governed data for the full demo

The data directory may contain files directly or below a `data/` subdirectory.
It must be obtained independently under the terms in
`DATA_REDISTRIBUTION_LEDGER.md`.

```bash
export TARGETIDEATOR_DATA_ROOT=/srv/targetideator-data
test -d "$TARGETIDEATOR_DATA_ROOT"
uv run targetideator serve --host 127.0.0.1 --port 8000
curl --fail http://127.0.0.1:8000/health
```

Operational rules:

- mount the data directory read-only for the serving process;
- do not place it below a web server's document root;
- pin upstream release/snapshot identifiers and verify local checksums;
- never copy the governed data into the wheel, container layer or Git history;
- use a new versioned redistribution review before publishing any data bundle.

## 5. Example systemd unit

```ini
[Unit]
Description=TargetIdeator research demo
After=network.target

[Service]
Type=simple
User=targetideator
Group=targetideator
WorkingDirectory=/opt/targetideator/app
Environment=TARGETIDEATOR_DATA_ROOT=/srv/targetideator-data
ExecStart=/opt/targetideator/.venv/bin/targetideator serve --host 127.0.0.1 --port 8000
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadOnlyPaths=/srv/targetideator-data

[Install]
WantedBy=multi-user.target
```

Terminate TLS and add authentication in a reverse proxy before making the
service reachable by other users.

## 6. Upgrade and rollback

Deploy immutable tags. Build the new tag in a separate virtual environment,
run `targetideator validate`, then switch the service. Roll back by restoring
the previous environment and its matching data-root snapshot. Do not reuse a
mutable external data root across temporal-replay releases.
