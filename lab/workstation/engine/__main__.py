"""
Stage 1 engine entry point.

Runs WORKER_COUNT workers for DURATION_S seconds against the fake internet,
writing one intent record per action.
"""

import asyncio
import os
import signal
import sys

from .adapters import HttpsAdapter
from .intent import IntentWriter
from .worker import Worker


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        print(f"!! {name} is not an integer, using {default}", file=sys.stderr)
        return default


async def main() -> int:
    run_id = os.environ.get("RUN_ID", "stage1-dev")
    seed = env_int("SEED", 1337)
    count = env_int("WORKER_COUNT", 3)
    duration = env_int("DURATION_S", 300)
    target_host = os.environ.get("TARGET_HOST", "www.example-corp.internal")
    target_ip = os.environ.get("TARGET_IP", "203.0.113.10")

    print(f"run_id={run_id} seed={seed} workers={count} duration={duration}s")
    print(f"target={target_host} ({target_ip})")

    writer = IntentWriter("/out/intents.jsonl")
    adapter = HttpsAdapter(ca_bundle="/pki/ca.crt")

    workers = [
        Worker(i, run_id, seed, target_host, target_ip, adapter, writer)
        for i in range(count)
    ]
    for w in workers:
        print(f"  {w.name}  {w.src_ip}  persona={w.persona}")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    if duration > 0:
        loop.call_later(duration, stop.set)

    tasks = [asyncio.create_task(w.run(stop)) for w in workers]
    await asyncio.gather(*tasks, return_exceptions=True)

    total = sum(w.actions_done for w in workers)
    failed = sum(w.actions_failed for w in workers)
    writer.close()

    print(f"\ncomplete: {total} actions, {failed} failed, "
          f"{writer.count} intents written to /out/intents.jsonl")

    if total == 0:
        print("!! no actions completed — the path is not working", file=sys.stderr)
        return 1
    if failed == total:
        print("!! every action failed — check firewall policy and routing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
