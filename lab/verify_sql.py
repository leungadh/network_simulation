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


def num(v, default=0):
    """
    Coerce a ClickHouse value to a number.

    ClickHouse serialises UInt64/Int64 as *quoted strings* in JSON to avoid
    precision loss in consumers with 53-bit floats, so count() arrives as "0"
    rather than 0. The URL parameter below disables that, but this stays as a
    guard: one unquoted assumption is how `'>' not supported between str and
    int` got shipped.
    """
    if v is None or v == "":
        return default
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return default


def ch(query: str):
    """Run a query, return a list of dicts."""
    body = (query.rstrip().rstrip(";") + " FORMAT JSONEachRow").encode()
    # Ask ClickHouse not to quote 64-bit integers, so counts arrive as numbers.
    req = urllib.request.Request(
        CH + "?output_format_json_quote_64bit_integers=0",
        data=body, method="POST")
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
    """Raw first cell. Do NOT coerce here — run_id is a string, and coercing
    it turned a valid run into 0 and reported 'no runs in ClickHouse'."""
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

    raw_events = num(one(q("SELECT count() AS n FROM netsim.flows WHERE run_id = '{run}'", run), "n"))
    intents_n = num(one(q("SELECT count() AS n FROM netsim.intents WHERE run_id = '{run}'", run), "n"))

    print(f"  {raw_events} flow events ({num(totals['closes'])} worker closes), {intents_n} intents")
    if infra:
        print("  " + str(sum(num(r["n"]) for r in infra)) + " non-worker flow(s) excluded: "
              + ", ".join(f"{r['ip']} x{r['n']}" for r in infra))
    print()

    if raw_events == 0 and intents_n == 0:
        print(f"{RED}Nothing ingested for this run.{RESET}\n")
        others = ch("SELECT run_id, count() AS n FROM netsim.flows "
                    "GROUP BY run_id ORDER BY max(ts) DESC LIMIT 5")
        if others:
            print("  Runs that DO have flows:")
            for r in others:
                print(f"    {r['run_id']}  {num(r['n'])} events")
            print("\n  The run id comes from out/current_run_id, written by")
            print("  `make traffic`. If it is not listed above, Vector stamped a")
            print("  different id — it must be recreated with the same RUN_ID.")
        else:
            print("  netsim.flows is empty: Vector is not ingesting at all.")
            print("    docker logs netsim-vector | tail -40")
            print("    cat out/parse_failures.log")
            print("    docker exec netsim-csrx cli -c "
                  "'show configuration system syslog'")
        return 1

    # 1 — ingestion
    check("flow events ingested", raw_events > 0)
    check("session_close events ingested", num(totals["closes"]) > 0,
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
    check("≥3 distinct source IPs", num(totals["sources"]) >= 3,
          "\n".join(f"{r['ip']}  {r['worker_name'] or '(unmatched)'}: {r['n']} sessions"
                    for r in per_worker))

    # 3 — classification
    apps = ch(q(f"""
        SELECT application, count() AS n FROM netsim.labelled_flows
        WHERE {scope} GROUP BY application ORDER BY n DESC
    """, run))
    classified = sum(num(r["n"]) for r in apps
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
    rate = 100 * num(ports["with_port"]) / num(ports["ok_n"]) if num(ports["ok_n"]) else 0
    if num(ports["failed"]):
        print(f"  ({num(ports['failed'])} failed request(s) excluded from capture rate)")
    check(f"source-port capture rate ({rate:.1f}%)", rate >= 95,
          hint="Below 95% means the httpx accessor in adapters/https.py has\n"
               "broken against the installed version. Run: make probe-port")

    # 5 — the join, as the view computes it
    jr = num(totals["join_rate"]) or 0
    detail = ""
    if jr < 98:
        detail = (f"{num(totals['closes']) - num(totals['unmatched']) - num(totals['out_of_window'])}"
                  f"/{num(totals['closes'])} sessions matched.\n"
                  f"{num(totals['unmatched'])} had no intent on (src_ip, src_port) — "
                  "source NAT or keep-alive.\n"
                  f"{num(totals['out_of_window'])} matched but fell outside the "
                  f"{JOIN_WINDOW_MS}ms window — clock skew, check NTP.")
    check(f"flow-to-intent join rate ({jr:.1f}%)", jr >= 98, hint=detail)

    # duration, for the sustained-run criterion
    span = num(ch(q(f"""
        SELECT dateDiff('second', min(ts), max(ts)) AS secs
        FROM netsim.labelled_flows WHERE {scope}
    """, run))[0]["secs"])
    mins = (span or 0) / 60
    # 29 rather than 30: the span is measured from the first flow to the last,
    # which is always shorter than DURATION_S — the first request lands after
    # startup and the last before the engine exits. A 1800s run reports ~29.9,
    # so a 30.0 threshold could never be met.
    check(f"sustained run ({mins:.1f} min)", mins >= 29, warn=True,
          hint="Stage 2 wants a ~30 minute run to call the join rate trustworthy.\n"
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
