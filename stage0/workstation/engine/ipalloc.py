"""
Deterministic source-IP allocation.

Stable across runs, so flow logs from different runs are directly comparable
and the intent<->flow join is unambiguous. See plan section 4.2.
"""

BASE_SECOND_OCTET = 10  # 10.10.x.y


def worker_ip(worker_id: int) -> str:
    """Map a worker id to its source address. worker_id 0 -> 10.10.1.1"""
    if worker_id < 0:
        raise ValueError("worker_id must be non-negative")
    third = worker_id // 254 + 1
    fourth = worker_id % 254 + 1
    if third > 254:
        raise ValueError(f"worker_id {worker_id} exceeds the 10.10.0.0/16 range")
    return f"10.{BASE_SECOND_OCTET}.{third}.{fourth}"


def worker_name(worker_id: int) -> str:
    return f"worker-{worker_id:04d}"
