"""Persistent catalog of every chain version ever assembled.

Versions are append-only and immutable: the full history is retained so old
cycles stay replayable and old audit rows always resolve to the exact chain
they ran on. Publishing the same version twice is idempotent; publishing a
changed definition under an existing ``name@version`` is rejected.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from tunnelnet.store import Store

from .config import from_mapping
from .definition import ChainRef, ChainVersion, compute_digest, document_matches

CHAIN_KIND = "chain"
CURSOR_KIND = "chain_cursor"
CURSOR_ID = "active"


class VersionExists(ValueError):
    """Raised when an existing version label would change content."""


class VersionMissing(KeyError):
    """Raised when a referenced chain version is not in the catalog."""


class ChainCatalog:
    """File backed, thread safe store of immutable chain definitions."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self._lock = threading.RLock()

    def publish(self, chain: ChainVersion) -> bool:
        """Persist a chain version.

        Returns ``True`` when this call added the document and ``False`` when
        the identical version was already present, making repeated assembly
        of the same version idempotent.
        """

        with self._lock:
            record_id = chain.chain_id
            existing = self._store.load(CHAIN_KIND, record_id)
            if existing is not None:
                if not document_matches(existing, chain):
                    raise VersionExists(
                        f"chain {record_id} already exists with different content; "
                        "bump the version instead of changing it in place"
                    )
                return False
            document = {"digest": chain.digest, **chain.canonical_document()}
            self._store.save(CHAIN_KIND, record_id, document)
            return True

    def get(self, chain_id: str) -> ChainVersion:
        document = self._store.load(CHAIN_KIND, chain_id)
        if document is None:
            raise VersionMissing(f"chain {chain_id} is not in the catalog")
        return _from_document(document)

    def exists(self, chain_id: str) -> bool:
        return self._store.exists(CHAIN_KIND, chain_id)

    def list(self) -> list[ChainVersion]:
        return [self.get(record_id) for record_id in self._store.list(CHAIN_KIND)]

    def versions(self) -> list[str]:
        return self._store.list(CHAIN_KIND)

    def count(self) -> int:
        return self._store.count(CHAIN_KIND)

    # -- activation cursor -------------------------------------------------

    def active_ref(self) -> ChainRef | None:
        document = self._store.load(CURSOR_KIND, CURSOR_ID)
        if document is None:
            return None
        return ChainRef.from_mapping(document)

    def set_active(self, chain: ChainVersion) -> None:
        with self._lock:
            if not self._store.exists(CHAIN_KIND, chain.chain_id):
                raise VersionMissing(
                    f"cannot activate {chain.chain_id}: publish it into the catalog first"
                )
            self._store.save(CURSOR_KIND, CURSOR_ID, chain.ref.as_dict())

    def activate(self, chain: ChainVersion) -> bool:
        """Publish (idempotently) then point the cursor at the chain."""

        with self._lock:
            added = self.publish(chain)
            current = self.active_ref()
            if current is not None and current == chain.ref:
                return added
            self.set_active(chain)
            return added


def _from_document(document: Mapping[str, object]) -> ChainVersion:
    config = from_mapping(document)
    predecessors = {
        stage: tuple(values)
        for stage, values in config.predecessors.items()
    }
    digest = str(document.get("digest") or compute_digest(document))
    return ChainVersion(
        name=config.name,
        version=config.version,
        digest=digest,
        stages=config.stages,
        required=config.required,
        predecessors=predecessors,
        actions=dict(config.actions),
        note=config.note,
    )
