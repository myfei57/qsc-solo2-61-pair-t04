"""Audit entries written by console actions."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from tunnelnet.audit import Record
from tunnelnet.drain import utc_now

if TYPE_CHECKING:  # pragma: no cover - imported only for type checkers
    from tunnelnet.ns import ChainRun
    from .runtime import Runtime


def record_event(
    rt: "Runtime",
    event: str,
    ref: str = "",
    *,
    run: "ChainRun | None" = None,
    stage: str = "",
) -> list[Record]:
    """Append an audit event and, when a reference is given, its ``_ref`` twin."""

    stamp = utc_now()
    chain_ref = None if run is None else run.chain
    entries = [
        Record(
            id=uuid.uuid4().hex,
            event=event,
            at=stamp,
            chain_version="" if chain_ref is None else chain_ref.version,
            chain_name="" if chain_ref is None else chain_ref.name,
            chain_fingerprint="" if chain_ref is None else chain_ref.fingerprint,
            run_id="" if run is None else run.id,
            stage=stage,
        )
    ]
    if ref:
        entries.append(
            Record(
                id=uuid.uuid4().hex,
                event=f"{event}_ref",
                at=stamp,
                chain_version="" if chain_ref is None else chain_ref.version,
                chain_name="" if chain_ref is None else chain_ref.name,
                chain_fingerprint="" if chain_ref is None else chain_ref.fingerprint,
                run_id="" if run is None else run.id,
                stage=stage,
            )
        )
    for entry in entries:
        rt.audit.append(entry)
    return entries
