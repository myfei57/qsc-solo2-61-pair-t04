"""Ordered control chain and the action performed at each stage.

Kept for compatibility with components still referring to the :class:`Stage`
enum; the canonical order now comes from the configurable chain package
(:mod:`tunnelnet.chain`) so this legacy view can never drift out of sync. New
code should use ``runtime.chains.active()`` instead of ``control_chain()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from tunnelnet.chain.config import DEFAULT_STAGE_ACTIONS, DEFAULT_STAGE_ORDER

from .stages import Stage

STAGE_ACTIONS: dict[Stage, str] = {
    Stage(value): DEFAULT_STAGE_ACTIONS[value] for value in DEFAULT_STAGE_ORDER
}


@dataclass(frozen=True)
class Step:
    """A stage paired with the action the operator performs there."""

    stage: Stage
    action: str

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage.value, "action": self.action}


@dataclass(frozen=True)
class Chain:
    """An ordered collection of control stages."""

    name: str
    stages: tuple[Stage, ...]

    def index_of(self, stage: Stage) -> int:
        for index, candidate in enumerate(self.stages):
            if candidate is stage or candidate == stage:
                return index
        return -1

    def before(self, first: Stage, second: Stage) -> bool:
        first_index = self.index_of(first)
        second_index = self.index_of(second)
        return first_index >= 0 and second_index >= 0 and first_index < second_index

    def contains(self, stage: Stage) -> bool:
        return self.index_of(stage) >= 0

    def count(self) -> int:
        return len(self.stages)

    def last(self) -> Stage | None:
        if not self.stages:
            return None
        return self.stages[-1]

    def steps(self) -> list[Step]:
        return [Step(stage=stage, action=STAGE_ACTIONS.get(stage, "")) for stage in self.stages]

    def describe(self) -> str:
        return f"chain {self.name} has {len(self.stages)} stages"


def control_chain() -> Chain:
    """Return the canonical ordering derived from the default chain config."""

    return Chain(
        name="tunnel-control",
        stages=tuple(Stage(value) for value in DEFAULT_STAGE_ORDER),
    )
