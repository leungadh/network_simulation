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
make pki          # lab CA + server cert (once)
make check-order  # prove docker honours interface connect order (~10s)
make up           # networks, syslog sink, cSRX (ordered), web
make config       # push the Junos bootstrap config
make traffic      # run the workers and follow them
make verify       # check the exit criteria
```

`make check-order` is worth running once on a new host. It attaches three
networks to a throwaway alpine container and prints the resulting interface
map. If that does not come out in order, cSRX has no chance either, and you
want to know before debugging a firewall.

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

**The docker bridge is moved off `.1`.** Docker assigns the first host address
of each subnet to the bridge interface itself. That is the address cSRX needs,
since in a firewall lab the firewall should be the gateway — so each network
sets an explicit `gateway:` at the top of its range (`.255.254` on the /16,
`.254` on the /24s). Without this, starting cSRX fails with
`failed to set up container networking: Address already in use`. The bridge
address is never used: all three networks are `internal`, so it routes nowhere.

**Everything is name-prefixed.** Containers are `netsim-*` and bridges
`br-ns-*` so the lab can coexist with other labs on the same host. Bare names
like `csrx` or `web` collide with anything else already running.

**Addressing lives in `.env` only.** `TRUST_PREFIX`, `MGMT_PREFIX` and
`UNTRUST_PREFIX` feed the compose networks, the Junos interface config (via
placeholders in `bootstrap.set` substituted at apply time), the worker IP
allocator, and the certificate SANs. Moving the lab off a colliding subnet is
a one-line change, and it can run alongside other labs on the same host.

**Structured-data syslog.** RT_FLOW then emits `key="value"` pairs instead of
the positional format. Stage 1's Vector config depends on this.

---

## Interface ordering — the most likely thing to break

cSRX maps container interfaces **positionally**:

```
eth0 -> fxp0       management   ${MGMT_PREFIX}.10      default 172.30.0.10
eth1 -> ge-0/0/0   trust        ${TRUST_PREFIX}.0.1    default 10.20.0.1
eth2 -> ge-0/0/1   untrust      ${UNTRUST_PREFIX}.1    default 203.0.113.1
```

Get this wrong and you have a firewall wired back-to-front: containers healthy,
logs clean, no traffic. It is the single most expensive failure in Stage 0
because nothing looks broken.

**Docker will not give you this order reliably.** When several networks are
declared at container creation, the attach order is not guaranteed
([moby#25181](https://github.com/moby/moby/issues/25181)), and Compose's
`priority` field does not dependably control it either. This was observed
first-hand here: with `priority` set, `eth0` came up holding the *trust*
address and the management address was absent entirely.

**So cSRX is not a compose service.** `csrx/launch.sh` follows Juniper's
documented procedure instead — start the container attached to the management
network alone, then `docker network connect` the data networks one at a time.
Each connect on a running container adds exactly one interface, in call order.
The script then *verifies* the mapping and refuses to continue if it is wrong,
rather than leaving you to discover it after a traffic run.

Everything else stays in compose; only cSRX needs the special handling.

Check the mapping by hand any time:

```bash
docker exec netsim-csrx ip -o -4 addr show
```

Note that `eth1` and `eth2` showing no address *after cSRX has started* is
normal — within about ten seconds `srxpfe` claims the revenue ports and their
addresses move to `tap0` and `tap1`. Checking `ethN` for an IPv4 address is
therefore racy and will report a false failure.

`launch.sh` verifies by **MAC address** instead: each `ethN`'s MAC is matched
against the docker endpoint it should belong to, which survives the dataplane
takeover. It then separately confirms `tap0` carries the trust address and
`tap1` the untrust address, giving two independent checks of the same mapping.

---

## Troubleshooting

**`pull access denied for csrx`.** The tag in `.env` does not match the image
you loaded. Docker cannot find it locally, assumes it is a registry image, and
tries to pull — there is no cSRX in any public registry, so the error is about
credentials rather than the real cause. Juniper tags include the build number:

```bash
docker images | grep csrx          # e.g. csrx  26.2R1.7
sed -i 's|^CSRX_IMAGE=.*|CSRX_IMAGE=csrx:26.2R1.7|' .env
```

**`Pool overlaps with other one on this address space`.** A subnet here
collides with an existing docker network or host route. Find the culprit:

```bash
docker network ls -q | xargs -n1 docker network inspect \
  --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'
ip -br route
```

If it is a stale network, `docker network prune`. If it belongs to something
you need, move this lab instead — the three prefixes in `.env` are the only
place addressing is defined:

```bash
TRUST_PREFIX=10.30            # expands to 10.30.0.0/16
MGMT_PREFIX=172.31.0          # expands to 172.31.0.0/24
UNTRUST_PREFIX=198.51.100     # expands to 198.51.100.0/24
```

Regenerate the PKI after moving — the server certificate carries the untrust
address as an IP SAN, so a stale cert fails TLS:

```bash
rm -f pki/*.crt pki/*.key pki/*.srl && make pki && make down && make run
```

**`Address already in use` when cSRX starts.** A container address collides
with the docker bridge's own gateway. Check what the bridge holds:

```bash
docker network inspect netsim-stage0_trust \
  --format '{{range .IPAM.Config}}subnet={{.Subnet}} gateway={{.Gateway}}{{end}}'
```

The gateway must not equal any `ipv4_address` in `docker-compose.yml`.

**No flows at all.** Check syslog is leaving cSRX:

```bash
docker exec -it netsim-csrx cli -c 'show configuration system syslog'
docker logs netsim-syslog-sink
```

**Workers cannot reach the web server.** The workstation entrypoint runs a
curl check at startup — read `docker logs netsim-workstation`. Then confirm the
firewall is passing:

```bash
docker exec -it netsim-csrx cli -c 'show security flow session'
docker exec -it netsim-csrx cli -c 'show security policies detail'
```

**`application` is UNKNOWN.** Confirm the licence and that AppID is running:

```bash
docker exec -it netsim-csrx cli -c 'show system license'
docker exec -it netsim-csrx cli -c 'show services application-identification status'
```

**Join rate below 98%.** `verify.py` distinguishes the two causes: matched-on-
port-but-outside-the-window means clock skew, no port match at all means NAT
or keep-alive.

---

## Layout

```
stage0/
├── docker-compose.yml       networks and the non-cSRX services
├── Makefile                 pki / up / config / traffic / verify
├── .env.example
├── verify.py                exit-criteria check
├── csrx/
│   ├── bootstrap.set        Junos config (zones, AppID, syslog, policy)
│   ├── launch.sh            ordered launch + interface-mapping verification
│   └── apply-config.sh      pushes config after the container is healthy
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
