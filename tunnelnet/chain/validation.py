"""Assembly time validation for a chain configuration.

A chain is accepted only when every required stage is present exactly once
and every declared predecessor relation (1) references known stages and
(2) holds in the declared order, with no cycle. Failures are collected into
one :class:`ValidationReport` so an operator sees every problem at once
instead of fixing them one boot at a time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .config import ChainConfig


@dataclass(frozen=True)
class ValidationErrorItem:
    """One rejected rule and a human readable explanation."""

    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ValidationReport:
    """Every problem found while validating one chain configuration."""

    errors: tuple[ValidationErrorItem, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_chain(self, chain_id: str) -> None:
        if self.errors:
            raise InvalidChain(chain_id, self.errors)

    def as_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "errors": [error.as_dict() for error in self.errors]}


class InvalidChain(ValueError):
    """Raised when a chain cannot be assembled from its configuration."""

    def __init__(self, chain_id: str, errors: tuple[ValidationErrorItem, ...]) -> None:
        self.chain_id = chain_id
        self.errors = errors
        lines = "; ".join(f"{error.code}: {error.detail}" for error in errors)
        super().__init__(f"chain {chain_id} rejected at assembly: {lines}")


def validate(config: ChainConfig) -> ValidationReport:
    """Run every assembly check, collecting all failures."""

    errors: list[ValidationErrorItem] = []
    errors.extend(_check_required(config))
    errors.extend(_check_duplicates(config))
    errors.extend(_check_predecessor_refs(config))
    errors.extend(_check_ordering(config))
    errors.extend(_check_cycles(config))
    return ValidationReport(tuple(errors))


def _check_required(config: ChainConfig) -> list[ValidationErrorItem]:
    present = set(config.stages)
    return [
        ValidationErrorItem("missing_stage", f"required stage {stage!r} is absent")
        for stage in sorted(config.required)
        if stage not in present
    ]


def _check_duplicates(config: ChainConfig) -> list[ValidationErrorItem]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for stage in config.stages:
        if stage in seen:
            duplicates.add(stage)
        seen.add(stage)
    return [
        ValidationErrorItem("duplicate_stage", f"stage {stage!r} appears more than once")
        for stage in sorted(duplicates)
    ]


def _check_predecessor_refs(config: ChainConfig) -> list[ValidationErrorItem]:
    present = set(config.stages)
    errors: list[ValidationErrorItem] = []
    for stage in sorted(config.predecessors):
        if stage not in present:
            errors.append(
                ValidationErrorItem(
                    "unknown_stage",
                    f"predecessors declared for absent stage {stage!r}",
                )
            )
        for predecessor in config.predecessors[stage]:
            if predecessor not in present:
                errors.append(
                    ValidationErrorItem(
                        "unknown_stage",
                        f"stage {stage!r} requires absent predecessor {predecessor!r}",
                    )
                )
    return errors


def _check_ordering(config: ChainConfig) -> list[ValidationErrorItem]:
    position = {stage: index for index, stage in enumerate(config.stages)}
    errors: list[ValidationErrorItem] = []
    for stage in sorted(config.predecessors):
        if stage not in position:
            continue
        for predecessor in config.predecessors[stage]:
            if predecessor not in position:
                continue
            if predecessor == stage:
                errors.append(
                    ValidationErrorItem(
                        "self_loop", f"stage {stage!r} cannot precede itself"
                    )
                )
            elif not position[predecessor] < position[stage]:
                errors.append(
                    ValidationErrorItem(
                        "order_violation",
                        f"stage {predecessor!r} must run before {stage!r}",
                    )
                )
    return errors


def _check_cycles(config: ChainConfig) -> list[ValidationErrorItem]:
    """Detect a directed cycle among predecessor edges over known stages."""

    graph: dict[str, set[str]] = {stage: set() for stage in config.stages}
    for stage, predecessors in config.predecessors.items():
        if stage not in graph:
            continue
        for predecessor in predecessors:
            if predecessor in graph and predecessor != stage:
                graph[stage].add(predecessor)

    white, grey, black = 0, 1, 2
    colour: dict[str, int] = {stage: white for stage in config.stages}
    stack: list[str] = []
    cycle: list[str] | None = None

    def visit(node: str) -> bool:
        nonlocal cycle
        colour[node] = grey
        stack.append(node)
        for nxt in sorted(graph[node]):
            if colour[nxt] == grey:
                cycle = stack[stack.index(nxt) :] + [nxt]
                return True
            if colour[nxt] == white and visit(nxt):
                return True
        stack.pop()
        colour[node] = black
        return False

    for stage in sorted(graph):
        if colour[stage] == white and visit(stage):
            break
    if cycle is None:
        return []
    return [
        ValidationErrorItem(
            "cycle", "predecessor graph has a cycle: " + " -> ".join(cycle)
        )
    ]
