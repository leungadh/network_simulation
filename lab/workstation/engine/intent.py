"""
Intent log — the ground truth that makes this a labelled dataset rather than
just a traffic generator (plan section 2.2).

Written as JSONL in Stage 1; Stage 2 loads the same fields into ClickHouse.
Field names match the `intents` table in plan section 5.2 exactly, so the
schema does not shift underneath the join.
"""

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Optional

SCHEMA_VERSION = 1


@dataclass
class IntentRecord:
    run_id: str
    ts: str
    worker_id: int
    worker_name: str
    persona: str
    src_ip: str
    dst_host: str
    dst_ip: str
    dst_port: int
    activity: str
    protocol_adapter: str
    label: str = "benign"
    attack_family: str = ""
    # Captured after socket bind. This is the join key to cSRX RT_FLOW.
    # 0 means capture failed — watch the rate of these, see verify.py.
    src_port: int = 0
    bytes_intended: int = 0
    # Actual response body size, for cross-checking against the firewall's
    # bytes_out. A large discrepancy means something is buffering or resetting.
    bytes_received: int = 0
    duration_ms: int = 0
    ok: bool = True
    error: str = ""
    schema_version: int = field(default=SCHEMA_VERSION)


class IntentWriter:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, path: str = "/out/intents.jsonl"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fh = open(path, "a", buffering=1)
        self._lock = threading.Lock()
        self.count = 0

    def write(self, record: IntentRecord) -> None:
        line = json.dumps(asdict(record), separators=(",", ":"))
        with self._lock:
            self._fh.write(line + "\n")
            self.count += 1

    def close(self) -> None:
        with self._lock:
            self._fh.close()
