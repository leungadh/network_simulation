# Stage 1 — Walking Skeleton

**Status:** Complete — all exit criteria met
**Date:** 27 August 2026
**Code:** [`lab/`](../lab/) · **Plan:** [`architecture_and_staging_plan.md`](architecture_and_staging_plan.md) §6

---

## 1. What this milestone proves

One question, deliberately narrow:

> **Can the firewall see individual workers, classify what they are doing, and
> can every flow it logs be tied back to the intent that produced it?**

Everything in the later stages assumes yes. Rather than assume it, this stage
builds the thinnest possible end-to-end path and measures it.

Nothing here is meant to be realistic. Three workers, one website, one activity
mix. Realism arrives in Stage 3; what matters now is that the plumbing is sound
and, critically, that the **labelling is trustworthy**.

---

## 2. Topology

![Stage 1 topology](topology/topology.svg)

```
netsim-workstation          netsim-csrx            netsim-web
 10.20.0.100                cSRX 26.2R1.7          203.0.113.10
 ├ worker-0000 10.20.1.1    eth1 → ge-0/0/0        nginx 1.27 + TLS
 ├ worker-0001 10.20.1.2      10.20.0.1/16         www.example-corp.internal
 └ worker-0002 10.20.1.3    eth2 → ge-0/0/1
                              203.0.113.1/24
        │                          │                     │
   br-ns-trust ───────────────────►│◄──────────── br-ns-untrust
   10.20.0.0/16                    │              203.0.113.0/24
   internal                        │              internal, TEST-NET-3
                                   │
                          eth0 → fxp0 172.30.0.10
                                   │
                              br-ns-mgmt  172.30.0.0/24
                                   │
                          netsim-syslog-sink 172.30.0.20
```

### Addressing

| Zone | Bridge | Subnet | Docker bridge gw | Notes |
|---|---|---|---|---|
| Management | `br-ns-mgmt` | `172.30.0.0/24` | `.254` | egress optional, see §5.5 |
| Trust | `br-ns-trust` | `10.20.0.0/16` | `10.20.255.254` | `internal`, never routes out |
| Untrust | `br-ns-untrust` | `203.0.113.0/24` | `.254` | `internal`, TEST-NET-3 |

The Docker bridge gateway sits at the **top** of each range rather than `.1`,
because cSRX needs `.1` to act as the real gateway. Docker claims the first host
address by default, and the collision prevents the container from starting at
all (§6.5).

### Interface mapping

cSRX maps container interfaces **positionally**:

| Container | Junos | Address | Role |
|---|---|---|---|
| `eth0` | `fxp0` | `172.30.0.10` | management, container-managed |
| `eth1` | `ge-0/0/0` (`tap0`) | `10.20.0.1/16` | trust |
| `eth2` | `ge-0/0/1` (`tap1`) | `203.0.113.1/24` | untrust |

Once `srxpfe` starts it claims the revenue ports and their addresses move to
`tap0`/`tap1`, so `eth1`/`eth2` legitimately show no IPv4 a few seconds after
launch. Verification therefore matches by **MAC address**, which survives the
handover.

---

## 3. Components

| Container | Image | Role |
|---|---|---|
| `netsim-csrx` | `csrx:26.2R1.7` | firewall, AppID, RT_FLOW syslog source |
| `netsim-workstation` | built | asyncio engine hosting all workers |
| `netsim-web` | `nginx:1.27-alpine` + TLS | the fake internet |
| `netsim-syslog-sink` | `python:3.12-alpine` | RT_FLOW → `out/flows.csv` |

Everything is prefixed `netsim-*` / `br-ns-*` so the lab coexists with other
labs on the same host — the machine already runs a 5G lab with its own cSRX.

### The engine

A worker is a **coroutine plus a source IP**, not a container. Three workers or
three hundred use the same engine; only the address allocation changes. Each
worker runs a seeded state machine over a weighted activity mix
(`browse_small`, `browse_page`, `browse_medium`, `upload_report`) with
log-normal think time.

```
workstation/engine/
├── __main__.py      orchestrator, signal handling, run summary
├── worker.py        seeded state machine
├── ipalloc.py       deterministic worker → IP
├── intent.py        ground-truth record + JSONL writer
└── adapters/
    ├── base.py      ProtocolAdapter interface
    └── https.py     HTTP/HTTPS with source binding + port capture
```

Protocol adapters sit behind an interface so Stage 3 can add S3, SMB, HLS and
DNS without touching the scheduler.

---

## 4. The data model

This is the point of the whole stage.

### Two independent records

**`out/intents.jsonl`** — written by the engine. What each worker *meant* to do.

```
run_id, ts, worker_id, worker_name, persona, src_ip, src_port,
dst_host, dst_ip, dst_port, activity, protocol_adapter,
label, attack_family, bytes_intended, bytes_received, duration_ms, ok, error
```

**`out/flows.csv`** — parsed from cSRX `RT_FLOW`. What the firewall *saw*.

```
run_id, ts, event_type, src_ip, src_port, dst_ip, dst_port, protocol,
application, nested_app, policy_name, src_zone, dst_zone,
bytes_in, bytes_out, packets_in, packets_out, duration_ms,
session_id, reason, nat_src_ip, nat_src_port
```

Column names match the ClickHouse `flows` and `intents` tables in plan §5
exactly, so the next stage is a transport change rather than a schema change.

### The join

```
(src_ip, src_port) within a 5-second window
```

Three design decisions exist purely to keep that key unambiguous:

1. **No source NAT.** NAT would rewrite the port and destroy the key. The
   `nat_*` columns exist for when NAT is eventually introduced.
2. **Keep-alive disabled.** Connection reuse would collapse several requests
   into one TCP session, so the firewall would log one flow for many intents.
   One request per connection keeps the mapping 1:1.
3. **The health check does not impersonate a worker.** The startup connectivity
   probe uses the workstation's own address, so it never produces a session
   without a matching intent.

### Reproducibility

```
run_id = f(scenario, seed, image digests, engine version)
```

Workers are **seeded state machines, not LLM agents**. The same seed replays the
same traffic, which is what makes clean-versus-attack comparison meaningful
later. Adding a fourth worker does not perturb the first three, because each
worker's RNG is derived independently from the run seed.

`run_id` is minted **once**, by `make traffic`, and both the sink and the engine
are recreated with it. Two containers minting their own ids was a real defect
(§6.4).

---

## 5. Design decisions

### 5.1 A worker is not a container

One container per worker would cost 300MB–1GB each and cap out around twenty.
Workers are coroutines sharing one container, each bound to its own source
address, which is what the firewall needs to attribute traffic. Scaling path:
one workstation container → N sharded containers → multiple hosts, with no
rewrite at any step.

### 5.2 Self-contained fake internet

All three bridges are `internal`, and the untrust subnet is TEST-NET-3
(`203.0.113.0/24`), unroutable by design. Two independent guarantees that the
simulation cannot reach or leak to the real internet.

This also means cSRX's AppID signature database cannot be downloaded in the
normal way — see §5.5.

### 5.3 Addressing lives in one place

`TRUST_PREFIX`, `MGMT_PREFIX` and `UNTRUST_PREFIX` in `.env` feed the compose
networks, the Junos interface and syslog config (via placeholders substituted at
apply time), the worker IP allocator, the return route, and the certificate
SANs. Moving the lab off a colliding subnet is a one-line change.

This was not academic: the default `10.10.0.0/16` collided with the existing
5G lab's `fw-left`/`fw-right` networks on the same host.

### 5.4 cSRX is launched by a script, not compose

Docker does not guarantee the order networks are attached at container creation,
and Compose's `priority` field does not reliably control it. Since cSRX maps
interfaces positionally, a wrong order produces a firewall wired back-to-front
with healthy-looking logs and no traffic.

`csrx/launch.sh` follows Juniper's documented procedure — start on management
alone, then `docker network connect` each data network in turn — and then
**verifies** the mapping by MAC, refusing to continue if it is wrong.

### 5.5 AppID signatures

cSRX ships with no signature database. The engine runs but has nothing to match,
so every session is classified `UNKNOWN` — correct behaviour, not a fault. Two
supported paths:

- **Offline** — drop the package in `csrx/signatures/`, run `make signatures`.
  Keeps the lab airgapped.
- **Online** — `MGMT_EGRESS=true` gives *only* the management bridge egress and
  NAT; trust and untrust stay internal. Then `make signatures-online`.

The database lives in the container filesystem, so `make down` destroys it.
`make up` reinstalls automatically when a package is present.

### 5.6 TX checksum offload is disabled

Required, not tuning. See §6.1.

---

## 6. Defects found and fixed

Every one of these would have produced a **plausible but wrong dataset** rather
than an obvious failure. That is why the exit criteria are strict and why the
verifier was written before the thing it verifies.

### 6.1 TX checksum offload — the hard one

**Symptom:** connections time out with no response. cSRX pings both neighbours
fine, interfaces/zones/policy all committed, sessions created and permitted,
`tcpdump` shows the SYN arriving at the destination, the destination is
listening — and no reply, no RST, no log entry.

**Cause:** with offload enabled the kernel does not compute the TCP checksum. It
writes a pseudo-header value and marks the buffer `CHECKSUM_PARTIAL` for
hardware to finish. That metadata survives veth and bridges — which is why
ordinary container traffic works and `tcpdump` routinely reports "incorrect"
checksums on healthy hosts.

It does **not** survive cSRX's dataplane, which reads raw frames in userspace and
re-emits them. What arrives carries an unfinished checksum with nothing saying
so, and the receiving kernel drops it silently, after `tcpdump` has captured it
and before the socket sees it.

**Fingerprint:** `cksum 0x474e (incorrect -> 0xe9ef)` where the first value
repeats across retransmits while the second changes.

**Fix:** `ethtool -K eth0 tx off` in both endpoint entrypoints. Any service added
in Stage 3 needs the same.

### 6.2 `verify=` silently ignored by httpx

Passing an explicit `AsyncHTTPTransport` — required for per-worker source
binding — means the transport builds its own SSL context and the client's
`verify` argument does nothing. Every request failed against the lab CA, and
confusingly it failed identically with `verify=False`. `verify` belongs on the
transport.

### 6.3 Source-port capture returned zero

Disabling keep-alive tears the connection down the instant the body is read, so
the socket's file descriptor is already `-1` when introspected. The two
requirements were in direct conflict. Fixed by issuing requests via
`client.stream()` and reading the port before consuming the body, using
httpcore's `client_addr` accessor which survives the TLS wrapper.

### 6.4 Split `run_id`

The sink and the engine were each minting a run id from separate `make`
invocations, so the two halves of the ground truth could never correlate. Now
minted once by `make traffic`, with both containers recreated to carry it.

### 6.5 Docker collisions

Four in sequence, all from the same root cause — the lab assuming it owned an
empty host:

| Collision | Fix |
|---|---|
| Image tag `csrx:26.2R1` vs `26.2R1.7` | `pull_policy: never`, required `CSRX_IMAGE` |
| Subnet overlap with the 5G lab | parameterized prefixes, moved to `10.20/16` |
| Container name `csrx` already in use | everything prefixed `netsim-*` |
| Bridge gateway claiming cSRX's `.1` | explicit `gateway:` at the top of each range |

---

## 7. Exit criteria — results

`make verify`, run 27 August 2026 (`run_id stage1-20260827-095833`):

| Check | Result |
|---|---|
| Flow events received | **PASS** — 88 events, 43 worker closes |
| `session_close` events received | **PASS** |
| ≥3 distinct source IPs | **PASS** — 13 / 14 / 16 across three workers |
| Flow IPs match intent IPs | **PASS** |
| AppSecure classified traffic | **PASS** — `SSL: 43` |
| Source-port capture rate | **PASS** — 100.0% |
| Flow-to-intent join rate | **PASS** — 100.0% |

**43 sessions, 43 intents, no orphans on either side.**

The verifier scopes to a single `run_id` (both output files are append-only) and
separates infrastructure traffic from worker traffic, so the numbers measure
what they claim to.

---

## 8. Running it

```bash
cp .env.example .env          # set CSRX_IMAGE to your loaded tag
make check-order              # confirm docker honours interface connect order
make up                       # networks, sink, cSRX (ordered), web
make config                   # push and verify the Junos config
make signatures               # install the AppID database
make traffic                  # run the workers
make verify                   # score the exit criteria
```

`make status` shows what is running and whether the signature database is
intact — the first thing to run when picking the lab up after a break.

**`make down` destroys the AppID signature database.** Avoid it unless changing
networking.

---

## 9. Deliberate limitations

Carried knowingly into later stages:

- **One service, one activity mix.** AppID reports the generic `SSL` class
  because there is only one HTTPS destination. Stage 3's distinct hostnames
  (`cloud.`, `files.`, `stream.`) are what make classification informative.
- **No TLS decryption.** AppID's granularity is bounded by what SNI reveals.
  Because the workers already trust the lab CA, adding SSL forward proxy later
  is a config change rather than a redesign.
- **No NAT.** Deliberate, to protect the join key.
- **CSV, not a database.** Replaced in the next stage.
- **`show route` and `show interfaces terse` are unavailable** — cSRX ships
  without a routing daemon. Diagnostics use the container view instead.

---

## 10. Next — Stage 2

The telemetry spine: Vector replacing the Python sink, ClickHouse replacing the
CSV, the `labelled_flows` view, and Grafana. Because the CSV columns already
match the target schema, this is a transport change rather than a schema change.

Exit criterion is the same ≥98% join rate, sustained over a 30-minute run and
measured in SQL rather than Python.
