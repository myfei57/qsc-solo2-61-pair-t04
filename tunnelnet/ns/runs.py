"""Running chain instances pinned to immutable chain versions."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tunnelnet.drain import utc_now

from .chain import ChainRef

if TYPE_CHECKING:
    from tunnelnet.store import Store

RUN_KIND = "chain_run"


@dataclass(frozen=True)
class ChainRun:
    """One execution instance. Its chain reference never changes mid-run."""

    id: str
    chain: ChainRef
    stage: str
    status: str = "running"
    completed_stages: tuple[str, ...] = ()
    created_at: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "chain": self.chain.as_dict(),
            "stage": self.stage,
            "status": self.status,
            "completed_stages": list(self.completed_stages),
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, object]) -> "ChainRun":
        chain_payload = payload.get("chain", {})
        chain = chain_payload if isinstance(chain_payload, dict) else {}
        completed = payload.get("completed_stages", [])
        return cls(
            id=str(payload.get("id", "")),
            chain=ChainRef(
                name=str(chain.get("name", "")),
                version=str(chain.get("version", "")),
                fingerprint=str(chain.get("fingerprint", "")),
            ),
            stage=str(payload.get("stage", "")),
            status=str(payload.get("status", "")),
            completed_stages=tuple(str(item) for item in completed)  # type: ignore[arg-type]
            if isinstance(completed, list)
            else (),
            created_at=str(payload.get("created_at", "")),
        )


class RunRegistry:
    """Track live and finished instances without mutating their chain ref."""

    def __init__(self, store: "Store | None" = None) -> None:
        self._store = store
        self._runs: dict[str, ChainRun] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        if store is not None:
            self._restore()

    def _restore(self) -> None:
        assert self._store is not None
        for run_id in self._store.list(RUN_KIND):
            payload = self._store.load(RUN_KIND, run_id)
            if payload is not None:
                run = ChainRun.from_mapping(payload)
                self._runs[run.id] = run
                self._order.append(run.id)
        self._order.sort(key=lambda run_id: (self._runs[run_id].created_at, run_id))

    def _save(self, run: ChainRun) -> None:
        if self._store is not None:
            self._store.save(RUN_KIND, run.id, run.as_dict())

    def start(self, chain_ref: ChainRef, first_stage: str, run_id: str = "") -> ChainRun:
        run = ChainRun(
            id=run_id or f"run-{uuid.uuid4().hex}",
            chain=chain_ref,
            stage=first_stage,
            created_at=utc_now(),
        )
        with self._lock:
            if run.id in self._runs:
                raise ValueError(f"chain run {run.id} already exists")
            self._runs[run.id] = run
            self._order.append(run.id)
            self._save(run)
        return run

    def advance(self, run_id: str, stage: str) -> ChainRun:
        with self._lock:
            run = self._require(run_id)
            completed = (*run.completed_stages, run.stage)
            updated = ChainRun(
                id=run.id,
                chain=run.chain,
                stage=stage,
                status=run.status,
                completed_stages=completed,
                created_at=run.created_at,
            )
            self._runs[run_id] = updated
            self._save(updated)
            return updated

    def complete(self, run_id: str) -> ChainRun:
        with self._lock:
            run = self._require(run_id)
            completed = (*run.completed_stages, run.stage)
            updated = ChainRun(
                id=run.id,
                chain=run.chain,
                stage="",
                status="completed",
                completed_stages=completed,
            )
            self._runs[run_id] = updated
            self._save(updated)
            return updated

    def fail(self, run_id: str, stage: str | None = None) -> ChainRun:
        with self._lock:
            run = self._require(run_id)
            updated = ChainRun(
                id=run.id,
                chain=run.chain,
                stage=run.stage if stage is None else stage,
                status="failed",
                completed_stages=run.completed_stages,
                created_at=run.created_at,
            )
            self._runs[run_id] = updated
            self._save(updated)
            return updated

    def get(self, run_id: str) -> ChainRun:
        with self._lock:
            return self._require(run_id)

    def list(self) -> list[ChainRun]:
        with self._lock:
            return [self._runs[key] for key in self._order]

    def active(self) -> list[ChainRun]:
        return [run for run in self.list() if run.status == "running"]

    def for_version(self, version: str) -> list[ChainRun]:
        return [run for run in self.list() if run.chain.version == version]

    def replay(self, run_id: str) -> dict[str, object]:
        run = self.get(run_id)
        return {"run": run.as_dict(), "stages": list(run.completed_stages)}

    def _require(self, run_id: str) -> ChainRun:
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"chain run {run_id} not found")
        return run
