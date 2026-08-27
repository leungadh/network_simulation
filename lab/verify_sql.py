#!/usr/bin/env python3
"""
Stage 2 exit-criteria check, scored from ClickHouse.

Same criteria as Stage 1, but measured against `netsim.labelled_flows` — the
view every later stage consumes. Scoring the view rather than a private
calculation means the number reported here is the number the dashboards and the
detection work will see. A join that is broken in the view can no longer pass.

Run from the host:  python3 verify_sql.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

CH = os.environ.get("CLICKHOUSE_URL", "http://127.0.0.1:8123")
CH_USER = os.environ.get("CLICKHOUSE_USER", "netsim")
CH_PASS = os.environ.get("CLICKHOUSE_PASSWORD", "netsim")
RUN_ID = os.environ.get("RUN_ID", "")
JOIN_WINDOW_MS = 5000

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
results = []


def ch(query: str):
    """Run a query, return a list of dicts."""
    body = (query.rstrip().rstrip(";") + " FORMAT JSONEachRow").encode()
    req = urllib.request.Request(CH, data=body, method="POST")
    # The default user has no network access unless credentials are configured,
    # so authenticate explicitly rather than relying on an anonymous default.
    req.add_header("X-ClickHouse-User", CH_USER)
    req.add_header("X-ClickHouse-Key", CH_PASS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        print(f"{RED}ClickHouse rejected the query:{RESET}\n{detail}\n")
        print(f"query was:\n{query}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"{RED}Cannot reach ClickHouse at {CH}{RESET} — {exc.reason}")
        print("Is the stack up?  make up   (then check: docker logs netsim-clickhouse)")
        sys.exit(1)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def one(query, field, default=0):
    rows = ch(query)
    return rows[0][field] if rows else default


def check(name, passed, detail="", hint="", warn=False):
    """
    `detail` is context worth seeing either way — the per-worker breakdown, the
    application mix. `hint` explains a failure and is suppressed on success,
    because a PASS line followed by troubleshooting advice reads as a failure.
    """
    mark = (f"{YELLOW}WARN{RESET}" if warn and not passed
            else f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}")
    print(f"  [{mark}] {name}")
    for line in (detail or "").splitlines():
        if line:
            print(f"         {line}")
    if not passed:
        for line in (hint or "").splitlines():
            if line:
                print(f"         {line}")
    results.append(passed or warn)
    return passed


def q(sql_text, run):
    return sql_text.replace("{run}", run.replace("'", "''"))


def main():
    print("\nStage 2 exit criteria — scored from ClickHouse\n" + "=" * 56)

    # Which run? Newest unless pinned.
    run = RUN_ID or one(
        "SELECT run_id FROM netsim.flows GROUP BY run_id "
        "ORDER BY max(ts) DESC LIMIT 1", "run_id", "")
    if not run:
        print(f"\n{RED}No runs in ClickHouse.{RESET}")
        print("Vector may not be ingesting. Check:")
        print("  docker logs netsim-vector | tail -30")
        print("  cat out/parse_failures.log")
        return 1

    print(f"\n  run_id: {run}")

    # Worker traffic vs infrastructure. Infrastructure (the startup health
    # check) has no intent by definition and must not be scored.
    infra = ch(q("""
        SELECT IPv4NumToString(src_ip) AS ip, count() AS n
        FROM netsim.labelled_flows
        WHERE run_id = '{run}'
          AND src_ip NOT IN (SELECT src_ip FROM netsim.intents WHERE run_id = '{run}')
        GROUP BY src_ip ORDER BY n DESC
    """, run))

    scope = ("run_id = '{run}' AND src_ip IN "
             "(SELECT src_ip FROM netsim.intents WHERE run_id = '{run}')")

    totals = ch(q(f"""
        SELECT count() AS closes,
               uniqExact(src_ip) AS sources,
               round(100 * avg(joined), 2) AS join_rate,
               countIf(NOT joined AND worker_name != '') AS out_of_window,
               countIf(worker_name = '') AS unmatched
        FROM netsim.labelled_flows WHERE {scope}
    """, run))[0]

    raw_events = one(q("SELECT count() AS n FROM netsim.flows WHERE run_id = '{run}'", run), "n")
    intents_n = one(q("SELECT count() AS n FROM netsim.intents WHERE run_id = '{run}'", run), "n")

    print(f"  {raw_events} flow events ({totals['closes']} worker closes), {intents_n} intents")
    if infra:
        print("  " + str(sum(r["n"] for r in infra)) + " non-worker flow(s) excluded: "
              + ", ".join(f"{r['ip']} x{r['n']}" for r in infra))
    print()

    # 1 — ingestion
    check("flow events ingested", raw_events > 0)
    check("session_close events ingested", totals["closes"] > 0,
          hint="Only session_create seen. Check `then log session-close` "
               "in the policy.")
    check("intents ingested", intents_n > 0,
          hint="Vector tails out/intents.jsonl — check the file exists and\n"
               "`docker logs netsim-vector` for file-source errors.")

    # 2 — attribution
    per_worker = ch(q(f"""
        SELECT worker_name, IPv4NumToString(src_ip) AS ip, count() AS n
        FROM netsim.labelled_flows WHERE {scope}
        GROUP BY worker_name, src_ip ORDER BY ip
    """, run))
    check("≥3 distinct source IPs", totals["sources"] >= 3,
          "\n".join(f"{r['ip']}  {r['worker_name'] or '(unmatched)'}: {r['n']} sessions"
                    for r in per_worker))

    # 3 — classification
    apps = ch(q(f"""
        SELECT application, count() AS n FROM netsim.labelled_flows
        WHERE {scope} GROUP BY application ORDER BY n DESC
    """, run))
    classified = sum(r["n"] for r in apps
                     if r["application"] not in ("UNKNOWN", "NONE", ""))
    check("AppSecure classified traffic", classified > 0,
          detail="\n".join(f"{r['application'] or '(empty)'}: {r['n']}" for r in apps),
          hint="Every session UNKNOWN — the signature database is probably absent:\n"
               "  docker exec netsim-csrx cli -c "
               "'show services application-identification status'\n"
               "'Application package version 0' means none installed.")

    # 4 — source port capture, over requests that actually connected
    ports = ch(q("""
        SELECT countIf(ok = 1) AS ok_n,
               countIf(ok = 1 AND src_port > 0) AS with_port,
               countIf(ok = 0) AS failed
        FROM netsim.intents WHERE run_id = '{run}'
    """, run))[0]
    rate = 100 * ports["with_port"] / ports["ok_n"] if ports["ok_n"] else 0
    if ports["failed"]:
        print(f"  ({ports['failed']} failed request(s) excluded from capture rate)")
    check(f"source-port capture rate ({rate:.1f}%)", rate >= 95,
          hint="Below 95% means the httpx accessor in adapters/https.py has\n"
               "broken against the installed version. Run: make probe-port")

    # 5 — the join, as the view computes it
    jr = totals["join_rate"] or 0
    detail = ""
    if jr < 98:
        detail = (f"{totals['closes'] - totals['unmatched'] - totals['out_of_window']}"
                  f"/{totals['closes']} sessions matched.\n"
                  f"{totals['unmatched']} had no intent on (src_ip, src_port) — "
                  "source NAT or keep-alive.\n"
                  f"{totals['out_of_window']} matched but fell outside the "
                  f"{JOIN_WINDOW_MS}ms window — clock skew, check NTP.")
    check(f"flow-to-intent join rate ({jr:.1f}%)", jr >= 98, hint=detail)

    # duration, for the sustained-run criterion
    span = ch(q(f"""
        SELECT dateDiff('second', min(ts), max(ts)) AS secs
        FROM netsim.labelled_flows WHERE {scope}
    """, run))[0]["secs"]
    mins = (span or 0) / 60
    check(f"sustained run ({mins:.1f} min)", mins >= 30, warn=True,
          hint="Stage 2 wants ≥30 minutes to call the join rate trustworthy.\n"
               "Set DURATION_S=1800 in .env and re-run. Not fatal — the other\n"
               "checks are still meaningful on a short run.")

    print("\n" + "=" * 56)
    if all(results):
        print(f"{GREEN}Stage 2 complete.{RESET} Telemetry spine verified end to end.\n")
        print(f"  Grafana: http://localhost:{os.environ.get('GRAFANA_PORT', '3000')}\n")
        return 0
    print(f"{RED}Stage 2 not met.{RESET}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
