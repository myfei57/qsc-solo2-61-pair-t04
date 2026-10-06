"""Running cycle instances pinned to one immutable chain version."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from tunnelnet.drain import utc_now

from .definition import ChainRef

INSTANCE_KIND = "chain_instance"

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class CycleInstance:
    """One control cycle with the exact chain version it is running on.

    The ref is captured when the cycle starts and never changes afterwards,
    so publishing a new chain mid-cycle cannot tear the running instance in
    two: each stage, the completion record and every audit row refer to the
    version in effect at start time.
    """

    id: str
    chain: ChainRef
    cabin_id: str
    started_at: str
    status: str = STATUS_RUNNING
    completed_at: str = ""
    stages: tuple[str, ...] = field(default_factory=tuple)
    result: Mapping[str, object] = field(default_factory=dict)

    @property
    def chain_id(self) -> str:
        return self.chain.chain_id

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_RUNNING

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "chain": self.chain.as_dict(),
            "cabin_id": self.cabin_id,
            "started_at": self.started_at,
            "status": self.status,
            "completed_at": self.completed_at,
            "stages": list(self.stages),
            "result": dict(self.result),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CycleInstance":
        result = payload.get("result", {})
        if not isinstance(result, Mapping):
            result = {}
        return cls(
            id=str(payload["id"]),
            chain=ChainRef.from_mapping(payload["chain"]),  # type: ignore[arg-type]
            cabin_id=str(payload.get("cabin_id", "")),
            started_at=str(payload.get("started_at", "")),
            status=str(payload.get("status", STATUS_RUNNING)),
            completed_at=str(payload.get("completed_at", "")),
            stages=tuple(str(item) for item in payload.get("stages", [])),
            result=dict(result),
        )


def new_instance_id() -> str:
    return f"cycle-{uuid.uuid4().hex[:16]}"
