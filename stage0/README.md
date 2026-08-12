# Stage 0 — Walking Skeleton

Proves the whole path end to end at minimum width:

```
3 workers  ->  br-trust  ->  cSRX 26.2R1  ->  br-untrust  ->  nginx (TLS)
                                 |
                              br-mgmt  ->  syslog sink  ->  out/flows.csv
```

Nothing here is meant to be realistic. The only question Stage 0 answers is
**can the firewall see individual workers and classify what they are doing** —
because everything in Stages 1–7 assumes it can.

---

## Prerequisites

- x86_64 Ubuntu host (cSRX has no ARM build — see plan §1.1)
- Docker Engine with Compose v2
- The cSRX 26.2R1 image loaded locally
- AppSecure licence installed (without it the `application` field stays `UNKNOWN`)
- Python 3.8+ on the host, for `verify.py`

Load the image and confirm the tag:

```bash
docker load -i <csrx-26.2R1-image>.tgz
docker images | grep csrx
```

---

## Run it

```bash
cp .env.example .env      # set CSRX_IMAGE to match the tag above
make run
```

`make run` chains: generate PKI → build and start → push Junos config → run
traffic for `DURATION_S` → verify.

Or step by step:

```bash
make pki       # lab CA + server cert (once)
make up        # build and start everything
make config    # push the Junos bootstrap config
make traffic   # follow the engine until it finishes
make verify    # check the exit criteria
```

---

## Exit criteria

`make verify` must pass all five checks:

| Check | Meaning if it fails |
|---|---|
| Flow events received | Syslog never arrived. cSRX config or mgmt network. |
| session_close events received | Sessions not ageing out, or `then log session-close` missing. |
| ≥3 distinct source IPs | Worker IP allocation or the trust bridge. |
| AppSecure classified traffic | Licence not installed, or AppID not enabled. |
| Join rate ≥98% | Source NAT rewriting ports, clock skew, or keep-alive collapsing sessions. |

Do not start Stage 1 until all five pass. Everything downstream inherits
these problems, and they get much harder to diagnose once there are 25
workers and six services in the picture.

---

## Deliberate design choices

**No source NAT.** The engine records the source port immediately after socket
bind, and cSRX logs the same port. That is the join key between intent and
flow. Introducing NAT means capturing the `nat_*` fields and joining on the
original tuple instead — worth doing eventually, not in Stage 0.

**Keep-alive disabled.** With connection reuse, several requests collapse into
one TCP session, so cSRX logs one flow for many intents and the join silently
under-reports. One request per connection keeps the mapping 1:1. See the note
in `workstation/engine/adapters/https.py`.

**`CSRX_PACKET_DRIVER=interrupt`.** The Juniper default is `poll`, which spins
a CPU core continuously and looks like a runaway process. Switch to `poll` or
`dpdk` only when you actually want throughput numbers.

**A worker is a coroutine plus a source IP, not a container.** This is what
lets the same engine go from 3 workers to hundreds without a rewrite. See
plan §4.1.

**`internal: true` on all three networks.** Guarantees the lab cannot reach the
real internet, and the untrust subnet is TEST-NET-3 (`203.0.113.0/24`), which
is unroutable by design. Two independent safeguards.

**Structured-data syslog.** RT_FLOW then emits `key="value"` pairs instead of
the positional format. Stage 1's Vector config depends on this.

---

## Interface ordering — the most likely thing to break

cSRX maps container interfaces in attachment order:

```
eth0 -> fxp0       management   172.30.0.10
eth1 -> ge-0/0/0   trust        10.10.0.1
eth2 -> ge-0/0/1   untrust      203.0.113.1
```

Docker Compose's `priority` field controls that order (higher attaches first).
Declaration order is *not* reliable. If this is wrong, traffic will not pass
and the logs look completely normal — which is why `apply-config.sh` prints the
actual mapping before pushing config.

Check it manually:

```bash
docker exec csrx ip -br addr show
```

---

## Troubleshooting

**No flows at all.** Check syslog is leaving cSRX:

```bash
docker exec -it csrx cli -c 'show configuration system syslog'
docker logs syslog-sink
```

**Workers cannot reach the web server.** The workstation entrypoint runs a
curl check at startup — read `docker logs workstation`. Then confirm the
firewall is passing:

```bash
docker exec -it csrx cli -c 'show security flow session'
docker exec -it csrx cli -c 'show security policies detail'
```

**`application` is UNKNOWN.** Confirm the licence and that AppID is running:

```bash
docker exec -it csrx cli -c 'show system license'
docker exec -it csrx cli -c 'show services application-identification status'
```

**Join rate below 98%.** `verify.py` distinguishes the two causes: matched-on-
port-but-outside-the-window means clock skew, no port match at all means NAT
or keep-alive.

---

## Layout

```
stage0/
├── docker-compose.yml       networks, interface priority, service wiring
├── Makefile                 pki / up / config / traffic / verify
├── .env.example
├── verify.py                exit-criteria check
├── csrx/
│   ├── bootstrap.set        Junos config (zones, AppID, syslog, policy)
│   └── apply-config.sh      pushes it after the container is healthy
├── internet/                nginx + TLS, the fake internet
├── pki/make-ca.sh           lab CA and server certificate
├── telemetry/syslog_sink.py RT_FLOW -> flows.csv
├── workstation/
│   ├── entrypoint.sh        per-worker IPs, default route via cSRX
│   └── engine/
│       ├── __main__.py      orchestrator
│       ├── worker.py        seeded state machine
│       ├── ipalloc.py       deterministic worker -> IP
│       ├── intent.py        ground-truth log
│       └── adapters/https.py
└── out/                     flows.csv, intents.jsonl, syslog_raw.log
```

---

## What Stage 1 adds

Vector replacing the Python sink, ClickHouse replacing the CSV, the
`labelled_flows` view, and Grafana. The CSV columns here already match the
`flows` table in plan §5.1, and `intents.jsonl` already matches `intents` in
§5.2 — so Stage 1 is a transport change, not a schema change.
