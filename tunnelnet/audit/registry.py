"""Append only audit registry."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .model import Record
from .report import AuditState
from .summary import count_by_event, summary

if TYPE_CHECKING:
    from tunnelnet.store import Store

AUDIT_RECORD_KIND = "audit_record"


def record_to_document(record: Record) -> dict[str, str]:
    return {
        "id": record.id,
        "event": record.event,
        "at": record.at,
        "chain_version": record.chain_version,
        "chain_name": record.chain_name,
        "chain_fingerprint": record.chain_fingerprint,
        "run_id": record.run_id,
        "stage": record.stage,
    }


def record_from_document(payload: dict[str, object]) -> Record:
    return Record(
        id=str(payload.get("id", "")),
        event=str(payload.get("event", "")),
        at=str(payload.get("at", "")),
        chain_version=str(payload.get("chain_version", "")),
        chain_name=str(payload.get("chain_name", "")),
        chain_fingerprint=str(payload.get("chain_fingerprint", "")),
        run_id=str(payload.get("run_id", "")),
        stage=str(payload.get("stage", "")),
    )


class AuditRegistry:
    """Keeps every linkage audit record in the order it was written."""

    def __init__(self, store: "Store | None" = None) -> None:
        self._records: list[Record] = []
        self._store = store
        self._lock = threading.RLock()
        if store is not None:
            self._restore()

    def _restore(self) -> None:
        assert self._store is not None
        for record_id in self._store.list(AUDIT_RECORD_KIND):
            payload = self._store.load(AUDIT_RECORD_KIND, record_id)
            if payload is not None:
                self._records.append(record_from_document(payload))
        self._records.sort(key=lambda record: (record.at, record.id))

    def append(self, record: Record) -> Record:
        with self._lock:
            self._records.append(record)
            if self._store is not None:
                self._store.save(AUDIT_RECORD_KIND, record.id, record_to_document(record))
        return record

    def records(self) -> list[Record]:
        with self._lock:
            return list(self._records)

    def list(self) -> list[Record]:
        """Records sorted by identifier, for stable console output."""

        return sorted(self.records(), key=lambda record: record.id)

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> int:
        with self._lock:
            if self._store is not None:
                for record in self._records:
                    self._store.delete(AUDIT_RECORD_KIND, record.id)
            self._records = []
        return 0

    def latest_id(self) -> str:
        with self._lock:
            if not self._records:
                return ""
            return self._records[-1].id

    def state(self) -> AuditState:
        return AuditState(entries=[record.as_dict() for record in self.list()], count=self.count())

    def count_by_event(self) -> dict[str, int]:
        return count_by_event(self.records())

    def summary(self) -> dict[str, int]:
        return summary(self.records())

    def describe(self) -> str:
        return f"audit records={self.count()}"
