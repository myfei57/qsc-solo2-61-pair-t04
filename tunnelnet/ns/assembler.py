"""Validate and assemble chain definitions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .chain import Chain
from .definition import ChainDefinition
from .stages import Stage


SUPPORTED_STAGES = frozenset(
    (
        Stage.ACCESS,
        Stage.ENVIRONMENT,
        Stage.VENTILATION,
        Stage.FIRE,
        Stage.PATROL,
        Stage.ENERGY,
        Stage.AUDIT,
    )
)


class ChainAssemblyError(ValueError):
    """Raised when a chain definition cannot safely be started."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class AssemblyResult:
    """The assembled chain and all validation findings."""

    chain: Chain
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> Chain:
        if self.errors:
            raise ChainAssemblyError(self.errors)
        return self.chain


def validate_definition(definition: ChainDefinition) -> list[str]:
    """Check completeness, uniqueness, relation validity, order and cycles."""

    errors: list[str] = []
    stages = definition.stage_ids()
    if not stages:
        errors.append("chain must contain at least one stage")

    seen: set[Stage] = set()
    duplicated: set[Stage] = set()
    for stage in stages:
        if stage in seen:
            duplicated.add(stage)
        seen.add(stage)
    if duplicated:
        errors.append("duplicate stages: " + ", ".join(stage.value for stage in sorted(duplicated, key=str)))

    configured = set(stages)
    missing = sorted(definition.required_stages - configured, key=lambda stage: stage.value)
    if missing:
        errors.append("missing required stages: " + ", ".join(stage.value for stage in missing))

    unsupported = sorted(configured - SUPPORTED_STAGES, key=lambda stage: stage.value)
    if unsupported:
        errors.append("unsupported stages: " + ", ".join(stage.value for stage in unsupported))

    positions = {stage: index for index, stage in enumerate(stages)}
    unknown: set[Stage] = set()
    relations: dict[Stage, set[Stage]] = defaultdict(set)
    for first, second in definition.before:
        if first not in configured:
            unknown.add(first)
        if second not in configured:
            unknown.add(second)
        if first in configured and second in configured:
            relations[first].add(second)

    if unknown:
        errors.append("before constraints reference unknown stages: " + ", ".join(stage.value for stage in sorted(unknown, key=str)))

    for first, seconds in relations.items():
        for second in seconds:
            if positions[first] >= positions[second]:
                errors.append(
                    f"stage order violates relation: {first.value} must be before {second.value}"
                )

    cycle = _find_cycle(configured, relations)
    if cycle:
        errors.append("stage relations form a cycle: " + " -> ".join(stage.value for stage in cycle))

    return errors


def assemble(definition: ChainDefinition) -> AssemblyResult:
    """Validate a definition and assemble its immutable runtime chain."""

    errors = validate_definition(definition)
    chain = Chain.from_spec(
        name=definition.name,
        stages=definition.stages,
        version=definition.version,
        fingerprint=definition.fingerprint,
    )
    return AssemblyResult(chain=chain, errors=errors)


def assemble_or_raise(definition: ChainDefinition) -> Chain:
    """Assemble a chain or reject startup with every validation error."""

    return assemble(definition).raise_if_invalid()


def _find_cycle(stages: set[Stage], relations: dict[Stage, set[Stage]]) -> list[Stage]:
    visiting: set[Stage] = set()
    visited: set[Stage] = set()
    stack: list[Stage] = []

    def visit(stage: Stage) -> list[Stage] | None:
        if stage in visiting:
            start = stack.index(stage)
            return stack[start:] + [stage]
        if stage in visited:
            return None

        visiting.add(stage)
        stack.append(stage)
        for candidate in sorted(relations.get(stage, set()), key=lambda item: item.value):
            cycle = visit(candidate)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(stage)
        visited.add(stage)
        return None

    for stage in sorted(stages, key=lambda item: item.value):
        cycle = visit(stage)
        if cycle is not None:
            return cycle
    return []
