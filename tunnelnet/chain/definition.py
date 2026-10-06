"""Immutable, content addressed chain versions produced by assembly."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from .config import ChainConfig
from .validation import InvalidChain, validate

DIGEST_PREFIX = 12


@dataclass(frozen=True)
class ChainVersion:
    """One assembled, validated and immutable chain definition.

    The digest is derived from the ordered stages and invariants, not the
    version label, so two definitions sharing a ``name@version`` but with
    different content have different digests and the tampering is detected.
    """

    name: str
    version: str
    digest: str
    stages: tuple[str, ...]
    required: frozenset[str]
    predecessors: Mapping[str, tuple[str, ...]]
    actions: Mapping[str, str]
    note: str = ""

    @property
    def chain_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def ref(self) -> "ChainRef":
        return ChainRef(name=self.name, version=self.version, digest=self.digest)

    def index_of(self, stage: str) -> int:
        for index, candidate in enumerate(self.stages):
            if candidate == stage:
                return index
        return -1

    def before(self, first: str, second: str) -> bool:
        first_index = self.index_of(first)
        second_index = self.index_of(second)
        return first_index >= 0 and second_index >= 0 and first_index < second_index

    def contains(self, stage: str) -> bool:
        return self.index_of(stage) >= 0

    def count(self) -> int:
        return len(self.stages)

    def last(self) -> str | None:
        return self.stages[-1] if self.stages else None

    def action_for(self, stage: str) -> str:
        return self.actions.get(stage, "")

    def steps(self) -> list[dict[str, str]]:
        return [{"stage": stage, "action": self.action_for(stage)} for stage in self.stages]

    def canonical_document(self) -> dict[str, object]:
        """Stable document used both for the digest and for persistence."""

        return {
            "name": self.name,
            "version": self.version,
            "stages": list(self.stages),
            "required": sorted(self.required),
            "predecessors": {
                stage: list(self.predecessors[stage])
                for stage in sorted(self.predecessors)
            },
            "actions": {stage: self.actions[stage] for stage in sorted(self.actions)},
            "note": self.note,
        }

    def as_dict(self) -> dict[str, object]:
        return {"ref": self.ref.as_dict(), **self.canonical_document()}


@dataclass(frozen=True)
class ChainRef:
    """The immutable pointer carried by running instances and audit rows."""

    name: str
    version: str
    digest: str

    @property
    def chain_id(self) -> str:
        return f"{self.name}@{self.version}"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version, "digest": self.digest}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "ChainRef":
        return cls(
            name=str(payload["name"]),
            version=str(payload["version"]),
            digest=str(payload["digest"]),
        )


def _structural_document(document: Mapping[str, object]) -> dict[str, object]:
    """Behaviour defining parts that identify a chain version.

    The digest covers the stage order, required stages and precedence
    invariants. Descriptive fields (``note``) and per-stage display text
    (``actions``) do not change what a cycle does, so they are excluded:
    re-issuing the same chain with an updated comment must stay idempotent.
    """

    return {
        "name": document["name"],
        "version": document["version"],
        "stages": list(document["stages"]),  # type: ignore[arg-type]
        "required": list(document["required"]),  # type: ignore[arg-type]
        "predecessors": dict(document["predecessors"]),  # type: ignore[arg-type]
    }


def compute_digest(document: Mapping[str, object]) -> str:
    """Content digest over the behaviour defining parts of a document."""

    structural = _structural_document(document)
    encoded = json.dumps(structural, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:DIGEST_PREFIX]


def assemble(config: ChainConfig) -> ChainVersion:
    """Validate a configuration and, when valid, freeze it into a version.

    Missing stages, ordering violations and cycles all raise
    :class:`~tunnelnet.chain.validation.InvalidChain`, which the boot path
    converts into a refused start.
    """

    report = validate(config)
    report.raise_for_chain(config.chain_id)

    predecessors = {
        stage: tuple(predecessors)
        for stage, predecessors in sorted(config.predecessors.items())
    }
    actions = dict(config.actions)
    document = {
        "name": config.name,
        "version": config.version,
        "stages": list(config.stages),
        "required": sorted(config.required),
        "predecessors": {stage: list(values) for stage, values in predecessors.items()},
        "actions": actions,
        "note": config.note,
    }
    digest = compute_digest(document)
    return ChainVersion(
        name=config.name,
        version=config.version,
        digest=digest,
        stages=tuple(config.stages),
        required=config.required,
        predecessors=predecessors,
        actions=actions,
        note=config.note,
    )


def document_matches(document: Mapping[str, object], chain: ChainVersion) -> bool:
    """Verify a persisted definition document against an assembled version."""

    stored_digest = str(document.get("digest", ""))
    if stored_digest:
        return stored_digest == chain.digest
    return compute_digest(document) == chain.digest
