"""Replay of historical cycles against the exact chain version they ran on.

Old chain versions are retained in full, so a cycle from weeks ago can be
re-walked on the identical stage order and its audit rows filtered back to
that same version. The definition, the instance and the audit trail thus
always resolve through one :class:`~tunnelnet.chain.definition.ChainRef`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .definition import ChainVersion
from .instance import CycleInstance
from .manager import ChainManager


@dataclass(frozen=True)
class ReplayResult:
    """One historical cycle resolved back onto its chain version."""

    instance: CycleInstance
    chain: ChainVersion
    audit_events: tuple[Mapping[str, str], ...] = field(default_factory=tuple)
    matched: bool = True

    @property
    def chain_id(self) -> str:
        return self.instance.chain.chain_id

    def as_dict(self) -> dict[str, object]:
        return {
            "instance": self.instance.as_dict(),
            "chain_id": self.chain.chain_id,
            "digest": self.chain.digest,
            "stages": list(self.chain.stages),
            "steps": self.chain.steps(),
            "matched": self.matched,
            "audit_events": [dict(event) for event in self.audit_events],
        }


def replay(
    manager: ChainManager,
    instance_id: str,
    audit_rows: Iterable[Mapping[str, str]] | None = None,
) -> ReplayResult:
    """Resolve an old instance to its pinned chain and collect its audit rows."""

    instance = manager.instance(instance_id)
    chain = manager.chain_for_instance(instance_id)
    events: tuple[Mapping[str, str], ...] = ()
    if audit_rows is not None:
        events = tuple(
            row
            for row in audit_rows
            if str(row.get("chain_id", "")) == instance.chain.chain_id
            and str(row.get("cycle_id", "")) == instance.id
        )
    return ReplayResult(instance=instance, chain=chain, audit_events=events)


def replay_version(
    manager: ChainManager,
    chain_id: str,
    audit_rows: Iterable[Mapping[str, str]] | None = None,
) -> list[ReplayResult]:
    """Replay every persisted instance that ran on one chain version."""

    results = []
    for instance in manager.instances():
        if instance.chain.chain_id != chain_id:
            continue
        results.append(replay(manager, instance.id, audit_rows))
    return results
