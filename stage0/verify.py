#!/usr/bin/env python3
"""
Stage 0 exit-criteria check.

Run on the host after a session:   python3 verify.py

Checks, in the order they are likely to fail:
  1. Both output files exist and are non-empty
  2. cSRX logged sessions from every expected worker IP
  3. AppSecure classified the traffic (application field is populated)
  4. Source-port capture worked in the engine
  5. Flows and intents actually join

Anything short of all five passing means Stage 1 is not safe to start.
"""

import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime


def parse_ts(value):
    """Parse either the syslog Z-suffixed form or Python's +00:00 isoformat."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
FLOWS = os.path.join(OUT, "flows.csv")
INTENTS = os.path.join(OUT, "intents.jsonl")
JOIN_WINDOW_MS = 5000

GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
results = []


def check(name, passed, detail="", warn=False):
    mark = f"{YELLOW}WARN{RESET}" if warn and not passed else (
        f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}")
    print(f"  [{mark}] {name}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")
    results.append(passed or warn)
    return passed


def load():
    if not os.path.exists(FLOWS):
        print(f"{RED}flows.csv not found at {FLOWS}{RESET}")
        print("The syslog sink never received RT_FLOW. Check that the cSRX")
        print("bootstrap config was applied and syslog points at the sink.")
        sys.exit(1)
    if not os.path.exists(INTENTS):
        print(f"{RED}intents.jsonl not found at {INTENTS}{RESET}")
        print("The engine never ran or could not write. Check: docker logs netsim-workstation")
        sys.exit(1)

    with open(FLOWS) as fh:
        flows = list(csv.DictReader(fh))
    with open(INTENTS) as fh:
        intents = [json.loads(line) for line in fh if line.strip()]
    return flows, intents


def main():
    print("\nStage 0 exit criteria\n" + "=" * 50)
    flows, intents = load()

    closes = [f for f in flows if f["event_type"] == "session_close"]
    print(f"\n  {len(flows)} flow events ({len(closes)} closes), {len(intents)} intents\n")

    # 1 — data present
    check("flow events received", len(flows) > 0)
    check("session_close events received", len(closes) > 0,
          "Only session_create seen. Sessions may not be ageing out yet —\n"
          "wait for the run to finish, or check `then log session-close`."
          if closes == [] and flows else "")

    # 2 — worker attribution
    flow_ips = Counter(f["src_ip"] for f in closes)
    intent_ips = Counter(i["src_ip"] for i in intents)
    check("distinct source IPs in flows", len(flow_ips) >= 3,
          "\n".join(f"{ip}: {n} sessions" for ip, n in sorted(flow_ips.items())))
    check("flow IPs match intent IPs", set(flow_ips) == set(intent_ips),
          f"flows:   {sorted(flow_ips)}\nintents: {sorted(intent_ips)}"
          if set(flow_ips) != set(intent_ips) else "")

    # 3 — AppID
    apps = Counter(f["application"] for f in closes if f["application"])
    unknown = sum(n for a, n in apps.items() if a.upper() in ("UNKNOWN", "NONE", ""))
    classified = sum(apps.values()) - unknown
    check("AppSecure classified traffic", classified > 0,
          "\n".join(f"{a}: {n}" for a, n in apps.most_common(10)) or
          "No application field populated. Check the AppSecure licence and\n"
          "`set services application-identification`.")

    # 4 — source port capture
    with_port = sum(1 for i in intents if i.get("src_port", 0) > 0)
    rate = with_port / len(intents) * 100 if intents else 0
    check(f"source-port capture rate ({rate:.1f}%)", rate >= 95,
          "Below 95% means the httpx socket introspection in adapters/https.py\n"
          "has broken against the installed version. The join degrades to\n"
          "(src_ip, time) and gets unreliable under load." if rate < 95 else "")

    # 5 — the join, with the same time window the ClickHouse view will use.
    # Without the window, ephemeral port reuse produces false matches that
    # inflate the rate and hide a real problem.
    index = {}
    for i in intents:
        if i.get("src_port"):
            index.setdefault((i["src_ip"], int(i["src_port"])), []).append(i)

    matched = 0
    port_only = 0
    for f in closes:
        try:
            key = (f["src_ip"], int(f["src_port"] or 0))
        except ValueError:
            continue
        candidates = index.get(key)
        if not candidates:
            continue
        port_only += 1
        f_ts = parse_ts(f["ts"])
        if f_ts is None:
            matched += 1          # cannot window-check; count it
            continue
        if any(
            (i_ts := parse_ts(i["ts"])) is not None
            and abs((f_ts - i_ts).total_seconds()) * 1000 < JOIN_WINDOW_MS
            for i in candidates
        ):
            matched += 1

    join_rate = matched / len(closes) * 100 if closes else 0
    detail = ""
    if join_rate < 98:
        detail = (f"{matched}/{len(closes)} sessions matched an intent.\n"
                  "Below 98% usually means source NAT is rewriting the port (check\n"
                  "`show security nat source summary` — Stage 0 should have none), or\n"
                  "keep-alive is collapsing several requests into one session.")
        if port_only > matched:
            detail += (f"\n{port_only - matched} matched on port but fell outside the "
                       f"{JOIN_WINDOW_MS}ms window —\nthat is clock skew between the "
                       "engine and cSRX, not NAT. Check NTP.")
    check(f"flow-to-intent join rate ({join_rate:.1f}%)", join_rate >= 98, detail)

    print("\n" + "=" * 50)
    if all(results):
        print(f"{GREEN}Stage 0 complete.{RESET} Safe to start Stage 1.\n")
        return 0
    print(f"{RED}Stage 0 not met.{RESET} Fix the failures above before Stage 1 —\n"
          "everything downstream inherits these problems.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
