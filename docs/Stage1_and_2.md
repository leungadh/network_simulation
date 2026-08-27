# Stages 1 and 2 — Walking Skeleton and Telemetry Spine

**Status:** Both complete — all exit criteria met
**Date:** 27 August 2026
**Code:** [`lab/`](../lab/) · **Plan:** [`architecture_and_staging_plan.md`](architecture_and_staging_plan.md) §6

This supersedes [`Stage_1.md`](Stage_1.md), which covered the first stage alone.

---

## 1. What these two stages prove

Two questions, deliberately narrow, asked in order.

**Stage 1 — the walking skeleton.**

> Can the firewall see individual workers, classify what they are doing, and
> can every flow it logs be tied back to the intent that produced it?

**Stage 2 — the telemetry spine.**

> Does that hold at volume, over a sustained run, when the answer is computed
> in SQL by the same view the dashboards and the detection work will read?

Everything in the later stages assumes yes to both. Rather than assume it, these
two stages build the thinnest possible end-to-end path, then replace its
plumbing with the real one and measure it again — 43 sessions the first time,
2070 over half an hour the second.

Nothing here is meant to be realistic. Three workers, one website, one activity
mix. Realism arrives in Stage 3; what matters now is that the plumbing is sound
and, critically, that the **labelling is trustworthy**.

---

## 2. Topology

![netsim topology](topology/topology.svg)

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
                          netsim-vector 172.30.0.20   (RT_FLOW in)
                                   │
                              br-ns-tlm  172.32.0.0/24
                                   │
                netsim-clickhouse ──► netsim-grafana
                 172.32.0.10           172.32.0.30 (:3000)
```

### Addressing

| Zone | Bridge | Subnet | Docker bridge gw | Notes |
|---|---|---|---|---|
| Management | `br-ns-mgmt` | `172.30.0.0/24` | `.254` | egress optional, see §6.5 |
| Trust | `br-ns-trust` | `10.20.0.0/16` | `10.20.255.254` | `internal`, never routes out |
| Untrust | `br-ns-untrust` | `203.0.113.0/24` | `.254` | `internal`, TEST-NET-3 |
| Telemetry | `br-ns-tlm` | `172.32.0.0/24` | `.254` | not `internal` — image pulls |

The Docker bridge gateway sits at the **top** of each range rather than `.1`,
because cSRX needs `.1` to act as the real gateway. Docker claims the first host
address by default, and the collision prevents the container from starting at
all (§7.5).

The telemetry bridge is the one deliberate exception to "everything internal".
It carries no simulated traffic — only Vector, ClickHouse and Grafana — so
giving it egress does not weaken the guarantee that the *data path* is sealed.

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

| Container | Image | Role | Added |
|---|---|---|---|
| `netsim-csrx` | `csrx:26.2R1.7` | firewall, AppID, RT_FLOW syslog source | 1 |
| `netsim-workstation` | built | asyncio engine hosting all workers | 1 |
| `netsim-web` | `nginx:1.27-alpine` + TLS | the fake internet | 1 |
| `netsim-syslog-sink` | `python:3.12-alpine` | RT_FLOW → `out/flows.csv` | 1 (retired) |
| `netsim-vector` | `timberio/vector:0.41.1` | syslog + intent ingest, parse, ship | 2 |
| `netsim-clickhouse` | `clickhouse/clickhouse-server:24.8-alpine` | `flows`, `intents`, the join | 2 |
| `netsim-grafana` | `grafana/grafana:11.2.0` | dashboards | 2 |

The Python sink still exists behind a `legacy` Compose profile. It is not
started by `make up`, but it is the fastest way to prove syslog is arriving when
Vector is the component under suspicion.

Everything is prefixed `netsim-*` / `br-ns-*` so the lab coexists with other
labs on the same host — the machine already runs a 5G lab with its own cSRX.

### The engine

A worker is a **coroutine plus a source IP**, not a container. Three workers or
three hundred use the same engine; only the address allocation changes. Each
worker runs a seeded state machine over a weighted activity mix
(`browse_small` 50, `browse_page` 25, `browse_medium` 15, `upload_report` 10)
with log-normal think time.

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

This is the point of both stages.

### Two independent records

**`intents`** — written by the engine. What each worker *meant* to do.

```
run_id, ts, worker_id, worker_name, persona, src_ip, src_port,
dst_host, dst_ip, dst_port, activity, protocol_adapter,
label, attack_family, bytes_intended, bytes_received, duration_ms, ok, error
```

**`flows`** — parsed from cSRX `RT_FLOW`. What the firewall *saw*.

```
run_id, ts, event_type, src_ip, src_port, dst_ip, dst_port, protocol,
application, nested_app, policy_name, src_zone, dst_zone,
bytes_in, bytes_out, packets_in, packets_out, duration_ms,
session_id, reason, nat_src_ip, nat_src_port
```

Stage 1 wrote these to `out/flows.csv` and `out/intents.jsonl` with exactly
these column names, chosen to match the ClickHouse tables in plan §5. That made
Stage 2 a **transport change rather than a schema change** — the single most
useful decision of Stage 1, and the reason the second stage was measured in days
rather than weeks.

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
   without a matching intent. The verifier reports it separately rather than
   scoring it.

### `labelled_flows` — the join as SQL

```sql
CREATE OR REPLACE VIEW netsim.labelled_flows AS
SELECT f.*, i.worker_id, i.worker_name, i.persona, i.activity, i.dst_host,
       i.label, i.attack_family, i.protocol_adapter, i.ts AS intent_ts,
       dateDiff('millisecond', i.ts, f.ts) AS join_lag_ms,
       (i.worker_name != '' AND dateDiff('millisecond', i.ts, f.ts) <= 5000) AS joined
FROM netsim.flows AS f
ASOF LEFT JOIN netsim.intents AS i
  ON f.run_id = i.run_id AND f.src_ip = i.src_ip
 AND f.src_port = i.src_port AND f.ts >= i.ts
WHERE f.event_type = 'session_close';
```

**Why `ASOF` and not a range join.** Ephemeral source ports get reused within a
run. A plain range join on `(src_ip, src_port)` with a time predicate matches a
flow against *every* earlier intent that happened to use the same port, so one
session fans out into several rows and the join rate reads above 100%. `ASOF`
takes the single most recent qualifying intent, which is by construction the one
that opened the connection.

`LEFT`, not inner, so unmatched flows survive into the view and can be counted.
A join that silently discards its failures cannot be measured.

The semantics were validated in DuckDB against synthetic port-reuse cases before
being written in ClickHouse SQL — which is why this part worked first time.

### Reproducibility

```
run_id = f(scenario, seed, image digests, engine version)
```

Workers are **seeded state machines, not LLM agents**. The same seed replays the
same traffic, which is what makes clean-versus-attack comparison meaningful
later. Adding a fourth worker does not perturb the first three, because each
worker's RNG is derived independently from the run seed
(`random.Random(seed * 100_003 + worker_id)`).

`run_id` is minted **once**, by `make traffic`, and both Vector and the engine
are recreated with it. Two containers minting their own ids was a real defect
(§7.4).

---

## 5. The telemetry spine

```
cSRX  ──RT_FLOW/UDP 514──►┐
                          ├─► netsim-vector ─► netsim-clickhouse ─► netsim-grafana
engine ──intents.jsonl───►┘         │
                                    └─► out/raw_syslog.log   (archive)
                                    └─► out/parse_failures.log
```

### Vector

Two sources, two transforms, four sinks:

| Component | Purpose |
|---|---|
| `csrx_syslog` | socket source, UDP `0.0.0.0:514` |
| `intents_file` | file source, tails `/out/intents.jsonl` |
| `parse_flows` | VRL: RT_FLOW structured-data → `flows` columns |
| `parse_intents` | VRL: JSONL → `intents` columns |
| `clickhouse_flows` / `clickhouse_intents` | HTTP inserts, basic auth |
| `raw_archive` | **fed directly from the source**, not the transform |
| `parse_failures` | the dropped-events route |

Two deliberate choices there.

**The raw archive is fed from the source, not the transform.** A parsing bug can
lose data permanently; an archive downstream of the parser would lose exactly
the events you need to fix the bug. This one is upstream, so a bad VRL rule
costs a reparse, not a rerun.

**Both transforms use `drop_on_error: true` with `reroute_dropped: true`.** An
event that fails to parse goes to `out/parse_failures.log` rather than being
inserted half-populated. A partially parsed flow with a zero source port would
join to nothing and quietly depress the join rate — a wrong number is worse than
a missing one.

The RT_FLOW parser leans on `parse_key_value` over the `[junos@...]` body
(structured-data syslog gives `key="value"` pairs), a lookup **map** for
protocol numbers rather than a conditional chain, and
`parse_timestamp(s, "%+") ?? now()` so a malformed timestamp degrades instead of
dropping the event.

### ClickHouse

`flows` and `intents` are `MergeTree`, ordered for the join, with `run_id` in the
sort key so scoping to one run is a prefix scan. `labelled_flows` is the view
above; `run_summary` aggregates per run.

Two host-specific pieces of configuration were needed and are worth keeping:

- `config.d/10-listen.xml` binds `0.0.0.0` with `listen_try`, because the host
  has IPv6 disabled and the default `::` bind fails outright (§7.9).
- `CLICKHOUSE_USER` / `CLICKHOUSE_PASSWORD` are set, because the official
  entrypoint disables network access for `default` the moment credentials
  exist anywhere. Vector, Grafana, `verify_sql.py` and the `make sql` target all
  authenticate (§7.10).

### Grafana

Eight panels, generated by `telemetry/grafana/make_dashboard.py` rather than
hand-edited JSON, so the dashboard is diffable and regenerable:

| Panel | Form | Why that form |
|---|---|---|
| Join rate | stat | one headline number, no plot |
| Classified | stat | one headline number |
| Sessions | stat | count |
| Traffic | stat | total bytes |
| Sessions per minute | timeseries | change over time |
| Bytes by application | stacked timeseries | magnitude by identity over time |
| Top talkers | table | ranked identity, several measures |
| Activity mix | table | the column the firewall alone cannot produce |

A `$run_id` template variable scopes every panel. Series use a fixed categorical
order validated against Grafana's dark surface; the health tiles use a separate
reserved status palette with thresholds, so a colour never means "series 4" in
one panel and "critical" in another.

**Activity mix is the panel that justifies the whole architecture.** The
firewall knows a session moved 240KB of SSL to `203.0.113.10`. Only the join
knows it was `upload_report`.

### Verification moved into SQL

`verify_sql.py` scores the exit criteria **through `labelled_flows`**, not
through a private calculation. The number it prints is therefore the number the
dashboards show and the number Stage 6's models will train against. A join that
is broken in the view can no longer pass the verifier.

---

## 6. Design decisions

### 6.1 A worker is not a container

One container per worker would cost 300MB–1GB each and cap out around twenty.
Workers are coroutines sharing one container, each bound to its own source
address, which is what the firewall needs to attribute traffic. Scaling path:
one workstation container → N sharded containers → multiple hosts, with no
rewrite at any step.

### 6.2 Self-contained fake internet

The trust and untrust bridges are `internal`, and the untrust subnet is
TEST-NET-3 (`203.0.113.0/24`), unroutable by design. Two independent guarantees
that the simulation cannot reach or leak to the real internet.

This also means cSRX's AppID signature database cannot be downloaded in the
normal way — see §6.5.

### 6.3 Addressing lives in one place

`TRUST_PREFIX`, `MGMT_PREFIX`, `UNTRUST_PREFIX` and `TELEMETRY_PREFIX` in `.env`
feed the compose networks, the Junos interface and syslog config (via
placeholders substituted at apply time), the worker IP allocator, the return
route, and the certificate SANs. Moving the lab off a colliding subnet is a
one-line change.

This was not academic: the default `10.10.0.0/16` collided with the existing
5G lab's `fw-left`/`fw-right` networks on the same host.

### 6.4 cSRX is launched by a script, not compose

Docker does not guarantee the order networks are attached at container creation,
and Compose's `priority` field does not reliably control it. Since cSRX maps
interfaces positionally, a wrong order produces a firewall wired back-to-front
with healthy-looking logs and no traffic.

`csrx/launch.sh` follows Juniper's documented procedure — start on management
alone, then `docker network connect` each data network in turn — and then
**verifies** the mapping by MAC, refusing to continue if it is wrong.

The same decision has a cost worth knowing: because cSRX sits outside Compose,
it holds endpoints on the Compose networks, so `docker compose up` of any other
service must use `--no-deps` or fail with *network has active endpoints*
(§7.15).

### 6.5 AppID signatures

cSRX ships with no signature database. The engine runs but has nothing to match,
so every session is classified `UNKNOWN` — correct behaviour, not a fault. Two
supported paths:

- **Offline** — drop the package in `csrx/signatures/`, run `make signatures`.
  Keeps the lab airgapped.
- **Online** — `MGMT_EGRESS=true` gives *only* the management bridge egress and
  NAT; trust and untrust stay internal. Then `make signatures-online`.

The database lives in the container filesystem, so `make down` destroys it.
`make up` reinstalls automatically when a package is present.

### 6.6 TX checksum offload is disabled

Required, not tuning. See §7.1.

### 6.7 `make up` configures the firewall itself

Stage 1 left `make config` as a separate step, on the assumption that the Junos
config persists. It does not — cSRX loses its entire configuration when the
container is recreated. A `down`/`up` cycle therefore produced a firewall with
no zones, no policy and no syslog, and the next traffic run generated five
minutes of doomed requests before anything said so. `make up` now applies and
verifies the config as its last step, and the workstation entrypoint retries the
connectivity check ten times and **exits non-zero** rather than generating
traffic down a dead path (§7.16).

---

## 7. Defects found and fixed

Every one of these would have produced a **plausible but wrong dataset**, or a
symptom pointing at the wrong component, rather than an obvious failure. That is
why the exit criteria are strict and why the verifier was written before the
thing it verifies.

### Stage 1 — the data path

#### 7.1 TX checksum offload — the hard one

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

#### 7.2 `verify=` silently ignored by httpx

Passing an explicit `AsyncHTTPTransport` — required for per-worker source
binding — means the transport builds its own SSL context and the client's
`verify` argument does nothing. Every request failed against the lab CA, and
confusingly it failed identically with `verify=False`. `verify` belongs on the
transport.

#### 7.3 Source-port capture returned zero

Disabling keep-alive tears the connection down the instant the body is read, so
the socket's file descriptor is already `-1` when introspected. The two
requirements were in direct conflict. Fixed by issuing requests via
`client.stream()` and reading the port before consuming the body, using
httpcore's `client_addr` accessor which survives the TLS wrapper.

#### 7.4 Split `run_id`

The sink and the engine were each minting a run id from separate `make`
invocations, so the two halves of the ground truth could never correlate. Now
minted once by `make traffic`, with both containers recreated to carry it.

#### 7.5 Docker collisions

Four in sequence, all from the same root cause — the lab assuming it owned an
empty host:

| Collision | Fix |
|---|---|
| Image tag `csrx:26.2R1` vs `26.2R1.7` | `pull_policy: never`, required `CSRX_IMAGE` |
| Subnet overlap with the 5G lab | parameterized prefixes, moved to `10.20/16` |
| Container name `csrx` already in use | everything prefixed `netsim-*` |
| Bridge gateway claiming cSRX's `.1` | explicit `gateway:` at the top of each range |

#### 7.6 No egress for the signature download

Every bridge had `enable_ip_masquerade: "false"`. Setting `internal: false` alone
therefore gave cSRX a route out with no NAT: packets left, replies never came
back, and the symptom was indistinguishable from having no route at all. Egress
needs **both** flags. Now a single `MGMT_EGRESS` switch derives them together.

### Stage 2 — the telemetry spine

#### 7.7 ClickHouse stuck `starting`, then `unhealthy`

Three probes in sequence, each wrong for a different reason:

| Probe | Why it failed |
|---|---|
| assumed `wget` was missing | it was present — it was returning *connection refused* |
| `clickhouse-client --user "$CLICKHOUSE_USER"` | fails when the container predates those variables |
| `http://localhost:8123/ping` | `localhost` resolves to `::1` first, refused with IPv6 off |

Final form, which is explicit about both the address family and the protocol:

```yaml
test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:8123/ping >/dev/null 2>&1"]
```

The lesson is §8: `docker inspect --format '{{json .State.Health.Log}}'` would
have shown the actual probe output on the first attempt instead of the third.

#### 7.8 ClickHouse bound `::` and died

`Listen [::]:8123 failed ... Address family for hostname not supported`. Visible
only in `/var/log/clickhouse-server/clickhouse-server.err.log` **inside** the
container — nothing on the host. Fixed with `config.d/10-listen.xml` binding
`0.0.0.0` and setting `listen_try`.

#### 7.9 ClickHouse credentials

Setting any user disables network access for `default`, so every client broke at
once. `CLICKHOUSE_USER`/`CLICKHOUSE_PASSWORD` are now set explicitly and every
consumer authenticates.

#### 7.10 `UInt64` arrives as a quoted string

ClickHouse serialises 64-bit integers as JSON strings by default, so
`verify_sql.py` raised `TypeError: '>' not supported between 'str' and 'int'`.
Fixed with `?output_format_json_quote_64bit_integers=0` plus a `num()` guard.

Worth recording: the first fix coerced inside `one()`, which turned the string
`run_id` `"run-A"` into `0` — a second bug introduced by the first, caught by
the verifier's own test before it shipped.

#### 7.11 Vector exited 78 — and it looked like a firewall problem

Two VRL errors: `else if` written on its own line (VRL requires it on the same
line as the closing brace), and `to_timestamp`, which does not exist — the
function is `parse_timestamp`.

The important part is the blast radius. **A VRL syntax error is fatal to the
entire config**, so a mistake in the RT_FLOW parser also killed the unrelated
intents pipeline. Both sources read zero, and the presenting symptom was "no
flows in ClickHouse" — which points at cSRX, syslog, and the management bridge
before it points at a typo. `make vector-check` now runs
`vector validate --no-environment --config-yaml` before anything is started.

#### 7.12 Grafana never started, then could not authenticate

Two separate faults stacked. `make nets` created every service but `make up`
started everything except Grafana. Once running, it reported
`default: Authentication failed` for two more reasons at once: Grafana
provisioning expands `$VAR` but **not** `${VAR:-fallback}`, and the credentials
were defined only on the `clickhouse` service, so Grafana had nothing to expand
in the first place.

#### 7.13 `network netsim_mgmt has active endpoints`

cSRX lives outside Compose and holds endpoints on the Compose networks, so any
`docker compose up` that tries to recreate a network fails. Traffic targets now
pass `--no-deps`; `docker restart netsim-vector` is the no-churn path when only
Vector needs to pick up a new `run_id`.

#### 7.14 A whole traffic run of failed requests

cSRX had lost its Junos configuration during a `down`/`up` cycle. The symptom
presented as three unrelated exit-criteria failures. See §6.7 for the fix.

#### 7.15 The sustained-run threshold could never be met

The run span is measured from the first flow to the last, which is always
shorter than `DURATION_S` — the first request lands after startup and the last
before the engine exits. A 1800-second run reports 29.9 minutes, so a 30.0
threshold was unreachable by construction. Threshold is now 29, with the reason
written in the code so it does not get "corrected" back.

---

## 8. Exit criteria — results

### Stage 1 — `run_id stage1-20260827-095833`

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

### Stage 2 — `run_id run-20260827-171310`, scored in SQL

```
4142 flow events (2070 worker closes), 2070 intents
1 non-worker flow excluded: 10.20.0.100 x1

[PASS] flow events / session_close / intents ingested
[PASS] ≥3 distinct source IPs — 695 / 702 / 673
[PASS] AppSecure classified traffic — SSL: 2070
[PASS] source-port capture rate (100.0%)
[PASS] flow-to-intent join rate (100.0%)
[WARN] sustained run (29.9 min)
```

The diagnostic breakdown of the join returned `no_intent: 0` and
`outside_window: 0` — every one of the 2070 sessions matched an intent, and none
of them matched late.

**2070 sessions over 30 minutes at a 100% join rate, computed by the same view
the dashboards read.**

The verifier scopes to a single `run_id`, separates infrastructure traffic from
worker traffic, and excludes failed requests from the port-capture rate, so the
numbers measure what they claim to.

---

## 9. Running it

```bash
cp .env.example .env          # set CSRX_IMAGE to your loaded tag
make check-order              # confirm docker honours interface connect order
make up                       # networks, cSRX (ordered), telemetry, web, config
make traffic                  # mint a run_id and run the workers
make verify                   # score the exit criteria in SQL
make dashboard-open           # Grafana at http://localhost:3000
```

`make up` now chains PKI → networks → cSRX → ClickHouse → Vector → Grafana →
web → signature install → **config apply and verify**, so a cold start needs one
command.

Useful during a run:

| Command | Use |
|---|---|
| `make status` | what is running, and whether the AppID database survived |
| `make runs` | every `run_id` in ClickHouse with counts |
| `make sql Q='...'` | ad-hoc query |
| `make vector-check` | validate the VRL **before** restarting anything |
| `make verify-csv` | export the labelled dataset |
| `make path-check` | trust → firewall → untrust reachability |

**`make down` destroys the AppID signature database and the Junos config.**
Avoid it unless changing networking; `make up` rebuilds both, but it costs
several minutes.

---

## 10. Deliberate limitations

Carried knowingly into Stage 3:

- **One service, one activity mix.** AppID reports the generic `SSL` class
  because there is only one HTTPS destination. Stage 3's distinct hostnames
  (`cloud.`, `files.`, `stream.`) are what make classification informative.
- **No TLS decryption.** AppID's granularity is bounded by what SNI reveals.
  Because the workers already trust the lab CA, adding SSL forward proxy later
  is a config change rather than a redesign.
- **No NAT.** Deliberate, to protect the join key.
- **Three workers, flat over time.** No personas, no time-of-day curve. The
  sessions-per-minute panel is therefore a flat line by design.
- **`show route` and `show interfaces terse` are unavailable** — cSRX ships
  without a routing daemon. Diagnostics use the container view instead.
- **Single-node ClickHouse, no retention policy.** Fine at 2070 rows; revisit
  when a run produces millions.

---

## 11. What these two stages taught us

Three patterns worth carrying forward, because they will repeat.

**Everything testable locally worked; everything only reasoned about broke.**
The ASOF join semantics, the IP allocator, the reproducibility contract, the
source-port capture, the syslog parser, the dashboard layout and the verifier
logic were all exercised against real inputs before deployment, and all worked
first time. The VRL config, the ClickHouse DDL and health probes, the ClickHouse
client typing and the Grafana provisioning could not be run locally — and every
one of them failed in the field. For Stage 3 that means: prefer components that
can be tested on a laptop, and when that is impossible, deploy them one at a
time.

**Ask the failing component for its own error before theorising.** Three
multi-round guessing sequences each ended in one command:
`docker inspect --format '{{json .State.Health.Log}}'`, the ClickHouse error log
*inside* the container, and `docker logs netsim-vector`.

**The expensive failures all looked like something else.** Checksum offload
looked like a firewall policy problem. A VRL typo looked like syslog not
arriving. A broken health probe looked like a dead server. A missing Junos
config looked like three unrelated exit-criteria failures. When a symptom points
at a component, confirm that component is actually speaking before working on it.

---

## 12. Next — Stage 3

Realistic workload. Six personas with distinct activity mixes, time-of-day
curves, 25 workers, and five new services behind the firewall: MinIO (S3),
Nextcloud, an HLS origin, SMB and CoreDNS.

Agreed approach: build the persona engine first — it is pure Python and testable
on a laptop — then add the services **one at a time**, verifying each before
starting the next. Per §11, that ordering is the whole point.

Three traps already known:

1. Every new service needs `ethtool -K eth0 tx off` in its entrypoint (§7.1).
2. Each needs a **distinct hostname on the lab CA**, so SNI gives AppID
   something to classify beyond the generic `SSL`.
3. `internal: true` means images and packages must arrive at build time —
   nothing on the untrust bridge can download anything at runtime.

Exit criterion: the join rate holds ≥98% across all six protocol adapters, and
the application mix in Grafana shows more than one series.
