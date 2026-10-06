"""Control chain configuration assembled for a tunnel.

The stage order is no longer hard coded. A tunnel ships one JSON document
describing the stage sequence and the ordering invariants it must satisfy;
:func:`load_config` turns that document into a :class:`ChainConfig` and
:func:`default_config` provides the canonical seven stage chain that the
service boots with when nothing is configured.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

DEFAULT_CHAIN_NAME = "tunnel-control"
DEFAULT_VERSION = "1"


@dataclass(frozen=True)
class ChainConfig:
    """An assembled but not yet validated chain definition.

    ``stages`` are stage identifiers in execution order. ``required`` lists
    the stages every chain must contain (a safety net so a tunnel cannot
    silently drop, for example, the terminal audit). ``predecessors`` maps a
    stage to the stages that must run before it; these are the ordering
    invariants checked at assembly time, not merely the declared order.
    """

    name: str
    version: str
    stages: tuple[str, ...]
    required: frozenset[str] = field(default_factory=frozenset)
    predecessors: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    actions: Mapping[str, str] = field(default_factory=dict)
    note: str = ""

    @property
    def chain_id(self) -> str:
        return f"{self.name}@{self.version}"


DEFAULT_STAGE_ACTIONS: dict[str, str] = {
    "access": "approve and release the cabin door",
    "environment": "sample the environment and route alarms",
    "ventilation": "run the ventilation bank",
    "fire": "link the fire zones",
    "patrol": "walk the patrol route",
    "energy": "meter cabin power",
    "audit": "record the linkage audit",
}

# Stages a tunnel control chain is never allowed to omit.
DEFAULT_REQUIRED: tuple[str, ...] = ("access", "environment", "fire", "energy", "audit")

# Invariants across every tunnel: nothing runs before entry, and the
# linkage audit must close the chain after every acting stage.
DEFAULT_PREDECESSORS: dict[str, tuple[str, ...]] = {
    "environment": ("access",),
    "ventilation": ("environment",),
    "fire": ("environment",),
    "patrol": ("access",),
    "energy": ("access",),
    "audit": ("access", "environment", "ventilation", "fire", "patrol", "energy"),
}

DEFAULT_STAGE_ORDER: tuple[str, ...] = (
    "access",
    "environment",
    "ventilation",
    "fire",
    "patrol",
    "energy",
    "audit",
)


def default_config() -> ChainConfig:
    """Return the canonical seven stage chain baked into the service."""

    return ChainConfig(
        name=DEFAULT_CHAIN_NAME,
        version=DEFAULT_VERSION,
        stages=DEFAULT_STAGE_ORDER,
        required=frozenset(DEFAULT_REQUIRED),
        predecessors={
            stage: tuple(predecessors) for stage, predecessors in DEFAULT_PREDECESSORS.items()
        },
        actions=dict(DEFAULT_STAGE_ACTIONS),
        note="canonical entry-to-audit chain",
    )


def load_config(text: str) -> ChainConfig:
    """Parse a chain configuration document.

    Only the stage order is mandatory; the invariants and actions fall back
    to the canonical defaults so a minimal tunnel document only needs
    ``name``, ``version`` and ``stages``. Structural problems raise
    :class:`ValueError`; ordering problems are reported later by validation
    so they can be collected into one report.
    """

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"chain config is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("chain config must be a JSON object")
    return from_mapping(payload)


def from_mapping(payload: Mapping[str, object]) -> ChainConfig:
    """Build a config from a decoded JSON object."""

    name = _string(payload, "name", DEFAULT_CHAIN_NAME)
    if not name:
        raise ValueError("chain config field 'name' must not be empty")
    version = _string(payload, "version", DEFAULT_VERSION)
    if not version:
        raise ValueError("chain config field 'version' must not be empty")

    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("chain config field 'stages' must be a non-empty list")
    stages: list[str] = []
    for item in raw_stages:
        if not isinstance(item, str) or not item:
            raise ValueError("every stage must be a non-empty string")
        stages.append(item)

    raw_required = payload.get("required", list(DEFAULT_REQUIRED))
    if not isinstance(raw_required, list) or not all(isinstance(item, str) for item in raw_required):
        raise ValueError("chain config field 'required' must be a list of strings")
    required = frozenset(str(item) for item in raw_required)
    if not required:
        raise ValueError("chain config field 'required' must not be empty")

    raw_predecessors = payload.get("predecessors", {})
    if not isinstance(raw_predecessors, dict):
        raise ValueError("chain config field 'predecessors' must be an object")
    predecessors: dict[str, tuple[str, ...]] = {}
    for stage, before in raw_predecessors.items():
        if not isinstance(stage, str) or not isinstance(before, list) or not all(
            isinstance(item, str) for item in before
        ):
            raise ValueError(
                f"predecessors for {stage!r} must be a list of stage strings"
            )
        predecessors[stage] = tuple(str(item) for item in before)

    raw_actions = payload.get("actions")
    if raw_actions is not None:
        if not isinstance(raw_actions, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_actions.items()
        ):
            raise ValueError("chain config field 'actions' must be an object of strings")

    note = _string(payload, "note", "")
    if raw_actions is None:
        # A tunnel document only needs to order stages; display text for the
        # standard stages falls back to the canonical actions.
        actions = {
            stage: DEFAULT_STAGE_ACTIONS[stage]
            for stage in stages
            if stage in DEFAULT_STAGE_ACTIONS
        }
    else:
        actions = {str(key): str(value) for key, value in raw_actions.items()}
    return ChainConfig(
        name=name,
        version=version,
        stages=tuple(stages),
        required=required,
        predecessors=predecessors,
        actions=actions,
        note=note,
    )


def _string(payload: Mapping[str, object], key: str, fallback: str) -> str:
    value = payload.get(key, fallback)
    if not isinstance(value, str):
        raise ValueError(f"chain config field {key!r} must be a string")
    return value
