#!/usr/bin/env python3
"""
Stage 1 syslog sink.

Listens for cSRX RT_FLOW messages on UDP/514, writes:
    /out/syslog_raw.log     every line received, verbatim
    /out/flows.csv          parsed RT_FLOW_SESSION_CLOSE records

Stage 2 replaces this with Vector -> ClickHouse. The CSV column names here are
deliberately the same as the `flows` table in section 5.1 of the plan, so the
verification script and any early analysis carry over unchanged.

Requires `structured-data` on the cSRX syslog host stanza, which emits
key="value" pairs rather than the positional format.
"""

import csv
import os
import re
import signal
import socket
import sys
from datetime import datetime, timezone

OUT_DIR = "/out"
RAW_PATH = os.path.join(OUT_DIR, "syslog_raw.log")
CSV_PATH = os.path.join(OUT_DIR, "flows.csv")
RUN_ID = os.environ.get("RUN_ID", "stage1-dev")
LISTEN = ("0.0.0.0", 514)

# structured-data payloads look like:  key="value" key2="value2"
KV = re.compile(r'(\S+?)="([^"]*)"')

# RFC5424 header timestamp, e.g. <14>1 2026-08-13T02:15:33.123Z csrx-lab ...
# Using the firewall's own timestamp rather than our receive time matters:
# the intent<->flow join has a 5s window, and receive-time jitter eats into it.
TS = re.compile(r'^<\d+>\d\s+(\S+)')

# RT_FLOW reports protocol-id numerically. Map the ones we care about so the
# column is readable; anything else passes through as the raw number.
PROTO = {"1": "ICMP", "6": "TCP", "17": "UDP", "47": "GRE", "50": "ESP"}

FIELDS = [
    "run_id", "ts", "event_type",
    "src_ip", "src_port", "dst_ip", "dst_port",
    "protocol", "application", "nested_app",
    "policy_name", "src_zone", "dst_zone",
    "bytes_in", "bytes_out", "packets_in", "packets_out",
    "duration_ms", "session_id", "reason",
    "nat_src_ip", "nat_src_port",
]

# RT_FLOW field name -> our column name.
MAP = {
    "source-address": "src_ip",
    "source-port": "src_port",
    "destination-address": "dst_ip",
    "destination-port": "dst_port",
    "protocol-id": "protocol",
    "application": "application",
    "nested-application": "nested_app",
    "policy-name": "policy_name",
    "source-zone-name": "src_zone",
    "destination-zone-name": "dst_zone",
    "bytes-from-client": "bytes_in",
    "bytes-from-server": "bytes_out",
    "packets-from-client": "packets_in",
    "packets-from-server": "packets_out",
    "session-id-32": "session_id",
    "session-id": "session_id",
    "reason": "reason",
    "nat-source-address": "nat_src_ip",
    "nat-source-port": "nat_src_port",
}


def parse(line: str):
    """Return a flow dict, or None if this is not an RT_FLOW session event."""
    if "RT_FLOW_SESSION_CLOSE" in line:
        event = "session_close"
    elif "RT_FLOW_SESSION_CREATE" in line:
        event = "session_create"
    else:
        return None

    row = {f: "" for f in FIELDS}
    row["run_id"] = RUN_ID
    row["event_type"] = event

    # Prefer the firewall's timestamp; fall back to receive time only if the
    # header is malformed or `structured-data` was not enabled.
    m = TS.match(line)
    if m:
        row["ts"] = m.group(1)
    else:
        row["ts"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    for key, val in KV.findall(line):
        col = MAP.get(key)
        if col:
            row[col] = val

    if row["protocol"]:
        row["protocol"] = PROTO.get(row["protocol"], row["protocol"])

    # elapsed-time is seconds in RT_FLOW; our schema stores milliseconds.
    m = re.search(r'elapsed-time="(\d+)"', line)
    if m:
        row["duration_ms"] = str(int(m.group(1)) * 1000)

    return row


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(LISTEN)

    raw = open(RAW_PATH, "a", buffering=1)
    csv_new = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
    csv_fh = open(CSV_PATH, "a", newline="", buffering=1)
    writer = csv.DictWriter(csv_fh, fieldnames=FIELDS)
    if csv_new:
        writer.writeheader()

    def shutdown(*_):
        raw.close()
        csv_fh.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"syslog sink listening on {LISTEN[0]}:{LISTEN[1]}  run_id={RUN_ID}", flush=True)
    parsed = 0
    received = 0

    while True:
        data, _addr = sock.recvfrom(65535)
        line = data.decode("utf-8", errors="replace").rstrip("\n")
        raw.write(line + "\n")
        received += 1

        row = parse(line)
        if row:
            writer.writerow(row)
            parsed += 1

        if received % 50 == 0:
            print(f"  received={received} rt_flow={parsed}", flush=True)


if __name__ == "__main__":
    main()
