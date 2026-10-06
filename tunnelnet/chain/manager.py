"""Assembly, activation and runtime pinning for control chains.

The manager is the single place the console talks to when it needs a chain:

* :meth:`bootstrap` assembles the configured chain at boot, validates it and
  activates it, refusing to start when validation fails;
* :meth:`publish` / :meth:`activate` handle runtime chain changes, keeping
  the full version history and only moving the active pointer;
* :meth:`start_cycle` pins every running instance to the chain active at
  start time, so in-flight cycles are never torn apart by a new version;
* instances are persisted, so instances still open after a restart finish on
  their pinned version and stay replayable.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping

from tunnelnet.store import Store

from .catalog import ChainCatalog
from .config import ChainConfig, default_config
from .definition import ChainRef, ChainVersion, assemble
from .instance import (
    INSTANCE_KIND,
    STATUS_COMPLETED,
    STATUS_FAILED,
    CycleInstance,
    new_instance_id,
)

Clock = Callable[[], str]


class NoActiveChain(RuntimeError):
    """Raised when a cycle starts before any chain was activated."""


class ChainBootError(RuntimeError):
    """Raised at start up when the configured chain cannot be assembled."""


class InvalidChainAtRest(RuntimeError):
    """Raised when a persisted chain document no longer matches its digest."""


class ChainManager:
    """Owns the catalog, the active pointer and the running instances."""

    def __init__(self, store: Store, clock: Clock | None = None) -> None:
        self._store = store
        self._catalog = ChainCatalog(store)
        self._clock = clock or _utc_now
        self._active: ChainVersion | None = None
        self._instances: dict[str, CycleInstance] = {}
        self._lock = threading.RLock()
        self._restore()

    def _restore(self) -> None:
        """Load the active version and persisted instances from the store."""

        ref = self._catalog.active_ref()
        if ref is not None:
            self._active = self._catalog.get(ref.chain_id)
            if self._active.digest != ref.digest:
                raise InvalidChainAtRest(ref.chain_id)
        for record_id in self._store.list(INSTANCE_KIND):
            document = self._store.load(INSTANCE_KIND, record_id)
            if document is not None:
                instance = CycleInstance.from_mapping(document)
                self._instances[instance.id] = instance

    # -- bootstrap ---------------------------------------------------------

    def bootstrap(self, config: ChainConfig | None = None) -> tuple[ChainVersion, bool]:
        """Assemble and activate the boot chain.

        Returns the active chain and whether this boot published a new
        version. When an active pointer already exists (a warm restart) it is
        preserved, and the configured chain is merely assured into the
        catalog idempotently.
        """

        chain = assemble(config or default_config())
        with self._lock:
            added = self._catalog.publish(chain)
            if self._active is None:
                ref = self._catalog.active_ref()
                if ref is None:
                    self._catalog.set_active(chain)
                    self._active = chain
                else:
                    self._active = self._catalog.get(ref.chain_id)
            return self._active, added

    # -- runtime changes ---------------------------------------------------

    def publish(self, config: ChainConfig) -> tuple[ChainVersion, bool]:
        """Assemble, validate and store a new version without activating it."""

        chain = assemble(config)
        with self._lock:
            added = self._catalog.publish(chain)
        return chain, added

    def activate(self, config_or_chain: ChainConfig | ChainVersion) -> tuple[ChainVersion, bool]:
        """Publish then activate a version; future cycles use it.

        Running cycles keep their pinned versions, so this never tears an
        in-flight instance.
        """

        chain = (
            config_or_chain
            if isinstance(config_or_chain, ChainVersion)
            else assemble(config_or_chain)
        )
        with self._lock:
            added = self._catalog.activate(chain)
            self._active = chain
        return chain, added

    def activate_version(self, chain_id: str) -> ChainVersion:
        with self._lock:
            chain = self._catalog.get(chain_id)
            self._catalog.set_active(chain)
            self._active = chain
            return chain

    # -- reads -------------------------------------------------------------

    def active(self) -> ChainVersion:
        if self._active is None:
            raise NoActiveChain("no control chain has been activated")
        return self._active

    def active_ref(self) -> ChainRef | None:
        return None if self._active is None else self._active.ref

    def catalog(self) -> ChainCatalog:
        return self._catalog

    def history(self) -> list[ChainVersion]:
        return self._catalog.list()

    def get_version(self, chain_id: str) -> ChainVersion:
        return self._catalog.get(chain_id)

    # -- running instances -------------------------------------------------

    def start_cycle(self, cabin_id: str) -> CycleInstance:
        """Pin a new cycle to the chain active at this instant."""

        with self._lock:
            chain = self.active()
            instance = CycleInstance(
                id=new_instance_id(),
                chain=chain.ref,
                cabin_id=cabin_id,
                started_at=self._clock(),
                stages=chain.stages,
            )
            self._save_instance(instance)
            return instance

    def finish_cycle(self, instance: CycleInstance, result: Mapping[str, object]) -> CycleInstance:
        return self._close(instance, STATUS_COMPLETED, result)

    def fail_cycle(self, instance: CycleInstance, reason: str) -> CycleInstance:
        return self._close(instance, STATUS_FAILED, {"error": reason})

    def _close(
        self, instance: CycleInstance, status: str, result: Mapping[str, object]
    ) -> CycleInstance:
        with self._lock:
            closed = CycleInstance(
                id=instance.id,
                chain=instance.chain,
                cabin_id=instance.cabin_id,
                started_at=instance.started_at,
                status=status,
                completed_at=self._clock(),
                stages=instance.stages,
                result=dict(result),
            )
            self._save_instance(closed)
            return closed

    def instance(self, instance_id: str) -> CycleInstance:
        return self._instances[instance_id]

    def instances(self) -> list[CycleInstance]:
        return [self._instances[key] for key in sorted(self._instances)]

    def open_instances(self) -> list[CycleInstance]:
        return [instance for instance in self.instances() if instance.is_open]

    def chain_for_instance(self, instance_id: str) -> ChainVersion:
        """Resolve the exact (possibly superseded) chain an instance ran on."""

        instance = self._instances[instance_id]
        chain = self._catalog.get(instance.chain.chain_id)
        if chain.digest != instance.chain.digest:
            raise InvalidChainAtRest(instance.chain.chain_id)
        return chain

    def _save_instance(self, instance: CycleInstance) -> None:
        self._store.save(INSTANCE_KIND, instance.id, instance.as_dict())
        self._instances[instance.id] = instance


def _utc_now() -> str:
    # Local import avoids making the whole chain package depend on drain.
    from tunnelnet.drain import utc_now

    return utc_now()
