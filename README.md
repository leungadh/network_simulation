<p align="center">
  <img src="docs/banner/banner.svg" alt="Enterprise Network Simulation Lab" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/licence-MIT-blue.svg" alt="MIT licence">
  <img src="https://img.shields.io/badge/stage-0%20walking%20skeleton-f5a524.svg" alt="Stage 1">
  <img src="https://img.shields.io/badge/host-x86__64%20only-important.svg" alt="x86_64 only">
</p>

# Enterprise Network Simulation Lab

A reproducible enterprise network simulator. Synthetic office workers generate
realistic application traffic through a containerised Juniper SRX (cSRX) into a
self-contained "fake internet". Every flow carries ground-truth labels, so the
resulting telemetry is a labelled dataset for building and evaluating network
anomaly detection.

```
workers  ->  br-trust  ->  cSRX  ->  br-untrust  ->  fake internet
                            |
                          syslog  ->  telemetry  ->  dashboards + detection
```

## Why

Labelled network traffic is a real gap. The public intrusion-detection datasets
are old, full of collection artifacts, and unrealistically separable. Here the
simulator knows what every worker intended, so every flow can be labelled with
worker, persona, activity, and benign/malicious — and the same day can be
replayed with and without an attack.

## Status

| Stage | Scope | State |
|---|---|---|
| 1 | Walking skeleton — 3 workers, 1 TLS site, cSRX, flows to CSV | **complete** |
| 2 | Telemetry spine — Vector, ClickHouse, Grafana, the labelled join | built, awaiting verification |
| 3 | Personas and the fake internet — 6 personas, 25 workers | not started |
| 4 | Network dashboard | not started |
| 5 | Pixel office — self-built Canvas 2D visualiser | not started |
| 6 | Adversary layer — beaconing, DNS tunnelling, exfil, scanning | not started |
| 7 | Detection — baselines, beacon finder, models, eval harness | not started |
| 8 | Response loop — alert to policy push | not started |

### Stage 1 results

All five exit criteria met: 43 firewall sessions against 43 engine intents,
**100% flow-to-intent join rate**, 100% source-port capture, even distribution
across three workers, and AppID classifying traffic once the signature database
was installed.

Five defects had to be fixed to get there, each of which would have silently
corrupted the labelled dataset rather than failing loudly:

- **TX checksum offload** — cSRX's userspace dataplane loses the
  `CHECKSUM_PARTIAL` marking, so offloaded checksums arrive unfinished and the
  receiving kernel drops them silently. Packets visible in `tcpdump`, listener
  up, no response.
- **`verify=` ignored by httpx** when an explicit transport is supplied, which
  the source-IP binding requires. Fails identically with `verify=False`.
- **Source-port capture** returned 0 with keep-alive disabled, because the
  socket closes before it can be read. Fixed by capturing during the stream.
- **Split `run_id`** — the sink and the engine each minted their own, so the
  two halves of the ground truth could never correlate.
- **Docker interface ordering** is not deterministic when several networks are
  attached at container creation, and cSRX maps `eth0/1/2` positionally.

Milestone write-up: [`docs/Stage_2.md`](docs/Stage_2.md) — architecture,
topology, defects fixed, and measured results.

Full design: [`docs/architecture_and_staging_plan.md`](docs/architecture_and_staging_plan.md)
Stage 1 topology: [`docs/topology/topology.svg`](docs/topology/topology.svg)

## Requirements

- **x86_64** Ubuntu host. cSRX has no ARM build — this is a hard constraint.
- Docker Engine with Compose v2
- cSRX 26.2R1 image, with AppSecure and IDP licensed
- Python 3.8+ on the host for the verification script

The engine, adapters, personas, visualiser and detection code are all
architecture-neutral and can be developed on any machine. Only full-stack
integration needs the x86_64 host.

## Quick start

```bash
cd stage1
cp .env.example .env        # set CSRX_IMAGE to your loaded image tag
make run                    # pki -> up -> config -> traffic -> verify
```

`make verify` must pass all five exit criteria before moving to Stage 2.

## Repository layout

```
docs/           architecture and staging plan
docs/Stage_2.md milestone write-up for the completed walking skeleton
docs/banner/    banner source + generator
docs/topology/  Stage 1 topology diagram + generator
lab/         walking skeleton (see lab/README.md)
```

The banner is generated, not hand-drawn — `python3 docs/banner/make_banner.py`
rebuilds it after an architecture change. A PNG is committed alongside the SVG;
swap the `img src` in this file if you prefer it.

## Note on the cSRX image

The image and licence keys are **not** in this repository and must never be
committed — they are licensed Juniper software. Load the image separately:

```bash
docker load -i <csrx-26.2R1-image>.tgz
docker images | grep csrx
```

## Development

The engine, protocol adapters, personas, visualiser and detection code are
architecture-neutral and can be developed anywhere. Only full-stack integration
against cSRX needs the x86_64 Ubuntu host.

Run outputs (`lab/out/`) are gitignored — they are regenerated each run and
grow quickly. To compare runs across machines, export the specific `run_id`
rather than committing raw output.

## Licence

MIT — see [LICENSE](LICENSE).

### Third-party components

This repository does **not** contain, and must never contain, the Juniper cSRX
image or any Juniper licence keys. Those are licensed separately and are
excluded by `.gitignore`.

Sprite assets for the Stage 5 pixel office are not yet included. When added,
their licences will be recorded here — likely MIT assets from
[pixel-agents](https://github.com/pixel-agents-hq/pixel-agents) (which requires
retaining the copyright notice) or CC0 assets from Kenney.nl. MIT on a
repository does not automatically cover third-party art it vendors, so each
asset pack needs checking individually.
# network_simulation
