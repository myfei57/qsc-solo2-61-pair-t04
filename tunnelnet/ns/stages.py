"""Named stages used by configurable control chains."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, unsafe_hash=True)
class Stage:
    """A single control step on a tunnel control chain."""

    value: str

    def __str__(self) -> str:
        return self.value

    @classmethod
    def coerce(cls, value: "Stage | str") -> "Stage":
        if isinstance(value, Stage):
            return value
        if not isinstance(value, str) or not value.strip():
            raise ValueError("stage id must be a non-empty string")
        return cls(value.strip())


Stage.ACCESS = Stage("access")
Stage.ENVIRONMENT = Stage("environment")
Stage.VENTILATION = Stage("ventilation")
Stage.FIRE = Stage("fire")
Stage.PATROL = Stage("patrol")
Stage.ENERGY = Stage("energy")
Stage.AUDIT = Stage("audit")
