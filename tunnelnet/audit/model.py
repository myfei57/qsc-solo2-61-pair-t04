"""Audit records written for every linkage event."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    """One linkage audit entry.

    ``chain_id``/``chain_digest`` identify the exact chain version active when
    the row was written; ``cycle_id`` ties the row to one running cycle and
    ``stage`` to the stage that emitted it. Older rows leave them empty, and
    :meth:`as_dict` omits empty fields so the on disk shape is unchanged for
    chains written before versioning existed.
    """

    id: str
    event: str
    at: str
    chain_id: str = ""
    chain_digest: str = ""
    cycle_id: str = ""
    stage: str = ""

    def as_dict(self) -> dict[str, str]:
        payload = {"id": self.id, "event": self.event, "at": self.at}
        if self.chain_id:
            payload["chain_id"] = self.chain_id
        if self.chain_digest:
            payload["chain_digest"] = self.chain_digest
        if self.cycle_id:
            payload["cycle_id"] = self.cycle_id
        if self.stage:
            payload["stage"] = self.stage
        return payload
