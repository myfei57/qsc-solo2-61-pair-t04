"""Audit records written for every linkage event."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    """One linkage audit entry."""

    id: str
    event: str
    at: str
    chain_version: str = ""
    chain_name: str = ""
    chain_fingerprint: str = ""
    run_id: str = ""
    stage: str = ""

    def as_dict(self) -> dict[str, str]:
        payload = {"id": self.id, "event": self.event, "at": self.at}
        if self.chain_name:
            payload["chain_name"] = self.chain_name
        if self.chain_version:
            payload["chain_version"] = self.chain_version
        if self.chain_fingerprint:
            payload["chain_fingerprint"] = self.chain_fingerprint
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.stage:
            payload["stage"] = self.stage
        return payload
