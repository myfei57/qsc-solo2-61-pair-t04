"""Chain configuration model and content addressing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from .stages import Stage

DEFAULT_REQUIRED_STAGES: tuple[Stage, ...] = (
    Stage.ACCESS,
    Stage.ENVIRONMENT,
    Stage.VENTILATION,
    Stage.FIRE,
    Stage.PATROL,
    Stage.ENERGY,
    Stage.AUDIT,
)

DEFAULT_STAGE_ACTIONS: dict[Stage, str] = {
    Stage.ACCESS: "approve and release the cabin door",
    Stage.ENVIRONMENT: "sample the environment and route alarms",
    Stage.VENTILATION: "run the ventilation bank",
    Stage.FIRE: "link the fire zones",
    Stage.PATROL: "walk the patrol route",
    Stage.ENERGY: "meter cabin power",
    Stage.AUDIT: "record the linkage audit",
}


@dataclass(frozen=True)
class StageSpec:
    """A configured stage and the action assigned to it."""

    stage: Stage
    action: str = ""

    @classmethod
    def from_value(cls, value: Stage | str | Mapping[str, object]) -> "StageSpec":
        if isinstance(value, Mapping):
            stage = Stage.coerce(str(value.get("stage", "")))
            action = str(value.get("action", "") or "")
            return cls(stage=stage, action=action or DEFAULT_STAGE_ACTIONS.get(stage, ""))
        stage = Stage.coerce(value if isinstance(value, Stage) else str(value))
        return cls(stage=stage, action=DEFAULT_STAGE_ACTIONS.get(stage, ""))

    def as_dict(self) -> dict[str, str]:
        return {"stage": self.stage.value, "action": self.action}


@dataclass(frozen=True)
class ChainDefinition:
    """An immutable, content addressed definition of a control chain."""

    name: str
    stages: tuple[StageSpec, ...]
    required_stages: frozenset[Stage] = field(default_factory=lambda: frozenset(DEFAULT_REQUIRED_STAGES))
    before: tuple[tuple[Stage, Stage], ...] = ()
    version: str = ""
    fingerprint: str = ""

    def stage_ids(self) -> tuple[Stage, ...]:
        return tuple(spec.stage for spec in self.stages)

    def actions(self) -> dict[Stage, str]:
        return {spec.stage: spec.action for spec in self.stages}

    def canonical_document(self) -> dict[str, object]:
        """Return the stable document covered by the fingerprint."""

        return {
            "name": self.name,
            "stages": [spec.as_dict() for spec in self.stages],
            "required_stages": sorted(stage.value for stage in self.required_stages),
            "before": [[first.value, second.value] for first, second in self.before],
        }

    def calculate_fingerprint(self) -> str:
        payload = json.dumps(self.canonical_document(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def with_version(self, version: str | None = None) -> "ChainDefinition":
        fingerprint = self.calculate_fingerprint()
        return replace(self, version=version or f"chain-{fingerprint}", fingerprint=fingerprint)

    def as_dict(self) -> dict[str, object]:
        document = self.canonical_document()
        document["version"] = self.version
        document["fingerprint"] = self.fingerprint
        document["policy"] = {"activation": "cycle_boundary", "history": "all_versions"}
        return document

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ChainDefinition":
        """Build a definition from a plain JSON-like configuration document."""

        name = str(payload.get("name", "tunnel-control"))
        raw_stages = payload.get("stages")
        if not isinstance(raw_stages, Sequence) or isinstance(raw_stages, (str, bytes)):
            raise ValueError("chain stages must be a list")

        stages = tuple(StageSpec.from_value(item) for item in raw_stages)  # type: ignore[arg-type]

        raw_required = payload.get("required_stages", [stage.value for stage in DEFAULT_REQUIRED_STAGES])
        if not isinstance(raw_required, Sequence) or isinstance(raw_required, (str, bytes)):
            raise ValueError("required_stages must be a list")
        required = frozenset(Stage.coerce(str(item)) for item in raw_required)

        before = tuple(_parse_before(payload.get("before", [])))
        definition = cls(name=name, stages=stages, required_stages=required, before=before)
        version = payload.get("version")
        if version is not None:
            definition = replace(definition, version=str(version))
        fingerprint = payload.get("fingerprint")
        if fingerprint is not None:
            definition = replace(definition, fingerprint=str(fingerprint))
        if not definition.version or not definition.fingerprint:
            explicit_version = definition.version or None
            definition = definition.with_version(explicit_version)
        return definition


def _parse_before(value: object) -> list[tuple[Stage, Stage]]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("chain before constraints must be a list")

    constraints: list[tuple[Stage, Stage]] = []
    for item in value:
        if isinstance(item, Mapping):
            first = item.get("first", item.get("before"))
            second = item.get("second", item.get("after"))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) == 2:
            first, second = item
        else:
            raise ValueError("each before constraint must be an object or two-item list")
        if first is None or second is None:
            raise ValueError("each before constraint needs first and second stages")
        constraints.append((Stage.coerce(str(first)), Stage.coerce(str(second))))
    return constraints
