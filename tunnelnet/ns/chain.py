"""Assembled, immutable control chains."""

from __future__ import annotations

from dataclasses import dataclass, field

from .definition import DEFAULT_STAGE_ACTIONS, StageSpec
from .stages import Stage


@dataclass(frozen=True)
class Step:
    """A stage paired with the action the operator performs there."""

    stage: Stage
    action: str

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage.value, "action": self.action}


@dataclass(frozen=True)
class Chain:
    """An ordered collection of control stages from one chain version."""

    name: str
    stages: tuple[Stage, ...]
    version: str = ""
    fingerprint: str = ""
    actions: dict[Stage, str] = field(default_factory=dict)

    @classmethod
    def from_spec(
        cls,
        name: str,
        stages: tuple[StageSpec, ...],
        version: str = "",
        fingerprint: str = "",
    ) -> "Chain":
        return cls(
            name=name,
            stages=tuple(spec.stage for spec in stages),
            version=version,
            fingerprint=fingerprint,
            actions={spec.stage: spec.action for spec in stages},
        )

    def ref(self) -> "ChainRef":
        return ChainRef(name=self.name, version=self.version, fingerprint=self.fingerprint)

    def index_of(self, stage: Stage | str) -> int:
        target = Stage.coerce(stage)
        for index, candidate in enumerate(self.stages):
            if candidate == target:
                return index
        return -1

    def before(self, first: Stage | str, second: Stage | str) -> bool:
        first_index = self.index_of(first)
        second_index = self.index_of(second)
        return first_index >= 0 and second_index >= 0 and first_index < second_index

    def contains(self, stage: Stage | str) -> bool:
        return self.index_of(stage) >= 0

    def count(self) -> int:
        return len(self.stages)

    def last(self) -> Stage | None:
        if not self.stages:
            return None
        return self.stages[-1]

    def action_for(self, stage: Stage | str) -> str:
        target = Stage.coerce(stage)
        return self.actions.get(target, DEFAULT_STAGE_ACTIONS.get(target, ""))

    def steps(self) -> list[Step]:
        return [Step(stage=stage, action=self.action_for(stage)) for stage in self.stages]

    def describe(self) -> str:
        return f"chain {self.name} version={self.version} has {len(self.stages)} stages"


@dataclass(frozen=True)
class ChainRef:
    """The immutable chain version shared by definitions, runs and audits."""

    name: str
    version: str
    fingerprint: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "fingerprint": self.fingerprint}
