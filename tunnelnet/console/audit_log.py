"""Audit entries written by console actions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from tunnelnet.audit import Record
from tunnelnet.drain import utc_now

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from tunnelnet.chain import ChainRef, CycleInstance

    from .runtime import Runtime


def record_event(
    rt: "Runtime",
    event: str,
    ref: str = "",
    *,
    instance: "CycleInstance | None" = None,
    chain: "ChainRef | None" = None,
    stage: str = "",
) -> list[Record]:
    """Append an audit event and, when a reference is given, its ``_ref`` twin.

    When ``instance`` (or an explicit ``chain``) is supplied the rows carry
    the exact chain version and cycle they belong to, so the audit trail, the
    chain definition and the running instance resolve to one version.
    """

    chain_ref = instance.chain if instance is not None else chain
    chain_id = "" if chain_ref is None else chain_ref.chain_id
    digest = "" if chain_ref is None else chain_ref.digest
    cycle_id = "" if instance is None else instance.id

    stamp = utc_now()
    entries = [
        Record(
            id=uuid.uuid4().hex,
            event=event,
            at=stamp,
            chain_id=chain_id,
            chain_digest=digest,
            cycle_id=cycle_id,
            stage=stage,
        )
    ]
    if ref:
        entries.append(
            Record(
                id=uuid.uuid4().hex,
                event=f"{event}_ref",
                at=stamp,
                chain_id=chain_id,
                chain_digest=digest,
                cycle_id=cycle_id,
                stage=stage,
            )
        )
    for entry in entries:
        rt.audit.append(entry)
    return entries
