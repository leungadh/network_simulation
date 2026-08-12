"""
Worker — a seeded state machine, not an LLM agent (plan section 2.1).

Every decision comes from a per-worker RNG derived from the run seed, so the
same (seed, scenario) replays identically. That property is what makes clean
vs attack comparisons meaningful later.
"""

import asyncio
import random

from .adapters.base import Action
from .ipalloc import worker_ip, worker_name

# Stage 0 activity mix. Stage 2 moves this into persona YAML.
ACTIVITY_MIX = [
    ("browse_small", 50, {"path": "/small", "method": "GET", "payload": 0}),
    ("browse_page", 25, {"path": "/", "method": "GET", "payload": 0}),
    ("browse_medium", 15, {"path": "/medium", "method": "GET", "payload": 0}),
    ("upload_report", 10, {"path": "/upload", "method": "POST", "payload": 256 * 1024}),
]


class Worker:
    def __init__(self, worker_id, run_id, seed, target_host, target_ip,
                 adapter, writer, persona="office_generic"):
        self.worker_id = worker_id
        self.name = worker_name(worker_id)
        self.src_ip = worker_ip(worker_id)
        self.persona = persona
        self.run_id = run_id
        self.target_host = target_host
        self.target_ip = target_ip
        self.adapter = adapter
        self.writer = writer

        # Derived per-worker so adding a worker does not perturb the others'
        # decision streams — important for run-to-run comparability.
        self.rng = random.Random(seed * 100_003 + worker_id)

        self.actions_done = 0
        self.actions_failed = 0

    def _next_action(self) -> Action:
        activities = [a[0] for a in ACTIVITY_MIX]
        weights = [a[1] for a in ACTIVITY_MIX]
        params = {a[0]: a[2] for a in ACTIVITY_MIX}

        chosen = self.rng.choices(activities, weights=weights, k=1)[0]
        p = params[chosen]

        return Action(
            chosen,
            url=f"https://{self.target_host}{p['path']}",
            host=self.target_host,
            dst_ip=self.target_ip,
            port=443,
            method=p["method"],
            payload_bytes=p["payload"],
        )

    def _think_time(self) -> float:
        """Seconds between actions. Log-normal-ish: mostly short, occasionally long."""
        return min(30.0, self.rng.lognormvariate(0.6, 0.8))

    async def run(self, stop_event: asyncio.Event) -> None:
        # Stagger starts so all workers do not fire simultaneously at t=0.
        await asyncio.sleep(self.rng.uniform(0, 3.0))

        while not stop_event.is_set():
            action = self._next_action()
            record = await self.adapter.execute(self, action)
            self.writer.write(record)

            self.actions_done += 1
            if not record.ok:
                self.actions_failed += 1

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._think_time())
            except asyncio.TimeoutError:
                pass
