"""
Protocol adapter interface (plan section 4.3).

Adding a protocol must never require touching the scheduler. Stage 3 adds s3,
smb, hls and dns behind this same interface.
"""

from typing import Protocol, runtime_checkable

from ..intent import IntentRecord


class Action:
    """One unit of work a worker performs."""

    def __init__(self, activity: str, **params):
        self.activity = activity
        self.params = params

    def __repr__(self) -> str:
        return f"Action({self.activity!r}, {self.params!r})"


@runtime_checkable
class ProtocolAdapter(Protocol):
    name: str

    async def execute(self, worker, action: Action) -> IntentRecord:
        """Perform the action and return the resulting intent record."""
        ...
