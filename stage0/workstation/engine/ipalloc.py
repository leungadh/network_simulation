"""
Deterministic source-IP allocation.

Stable across runs, so flow logs from different runs are directly comparable
and the intent<->flow join is unambiguous. See plan section 4.2.

The prefix is the first two octets; the third octet scales past 254 workers.
Set TRUST_PREFIX in .env to move the lab off a colliding subnet.
"""

import os

DEFAULT_PREFIX = "10.20"


def trust_prefix() -> str:
    return os.environ.get("TRUST_PREFIX", DEFAULT_PREFIX)


def worker_ip(worker_id: int, prefix: str = None) -> str:
    """Map a worker id to its source address. worker_id 0 -> <prefix>.1.1"""
    if worker_id < 0:
        raise ValueError("worker_id must be non-negative")
    third = worker_id // 254 + 1
    fourth = worker_id % 254 + 1
    if third > 254:
        raise ValueError(f"worker_id {worker_id} exceeds the /16 range")
    return f"{prefix or trust_prefix()}.{third}.{fourth}"


def worker_name(worker_id: int) -> str:
    return f"worker-{worker_id:04d}"
