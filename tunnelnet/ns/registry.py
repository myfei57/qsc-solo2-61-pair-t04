"""Versioned control chain registry."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .assembler import assemble_or_raise
from .chain import Chain, ChainRef
from .config import default_chain_document
from .definition import ChainDefinition
from . import persistence
from .stages import Stage

if TYPE_CHECKING:
    from tunnelnet.store import Store


@dataclass(frozen=True)
class InstallationResult:
    """Result of installing a version; repeated installation is idempotent."""

    chain: Chain
    created: bool
    activated: bool


@dataclass
class ChainRegistry:
    """Keep the complete immutable history of accepted chain versions."""

    active_version: str = ""
    _store: "Store | None" = field(default=None, init=False, repr=False, compare=False)
    _versions: dict[str, ChainDefinition] = field(default_factory=dict, init=False)
    _chains: dict[str, Chain] = field(default_factory=dict, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    @classmethod
    def from_store(
        cls,
        store: "Store | None",
        bootstrap: dict[str, object] | ChainDefinition | None = None,
    ) -> "ChainRegistry":
        """Restore complete chain history, or install the bootstrap chain."""

        registry = cls()
        registry._store = store
        if store is not None:
            definitions, active_version = persistence.restore_definitions(store)
            for definition in definitions:
                chain = assemble_or_raise(definition)
                registry._versions[definition.version] = definition
                registry._chains[definition.version] = chain
            if active_version in registry._chains:
                registry.active_version = active_version
            elif registry._chains:
                registry._set_active(sorted(registry._chains)[0])

        if registry._versions:
            if bootstrap is not None:
                registry.install(bootstrap, activate=True)
        elif bootstrap is None:
            bootstrap = default_chain_document()
            registry.install(bootstrap)
        else:
            registry.install(bootstrap)
        return registry

    def bind_store(self, store: "Store | None") -> None:
        with self._lock:
            self._store = store

    def install(
        self,
        payload: dict[str, object] | ChainDefinition,
        *,
        activate: bool = True,
    ) -> InstallationResult:
        """Validate, content-address, and install one chain definition.

        Installing the same supplied version and content twice has no extra
        effect. Reusing a version identifier with changed content is rejected.
        All accepted versions are retained for later audit replay.
        """

        definition = (
            payload
            if isinstance(payload, ChainDefinition)
            else ChainDefinition.from_mapping(payload)
        )
        definition = definition.with_version(definition.version or None)

        with self._lock:
            existing = self._versions.get(definition.version)
            if existing is not None:
                if existing.fingerprint != definition.fingerprint:
                    raise ValueError(
                        f"chain version {definition.version} already exists with a different fingerprint"
                    )
                chain = self._chains[definition.version]
                return InstallationResult(
                    chain=chain,
                    created=False,
                    activated=False,
                )

            chain = assemble_or_raise(definition)
            self._versions[definition.version] = definition
            self._chains[definition.version] = chain
            if self._store is not None:
                persistence.save_definition(self._store, definition)
            should_activate = activate or not self.active_version
            if should_activate:
                self._set_active(definition.version)
            return InstallationResult(chain=chain, created=True, activated=should_activate)

    def activate(self, version: str) -> Chain:
        """Set the version picked by the next cycle that starts."""

        with self._lock:
            chain = self._chains.get(version)
            if chain is None:
                raise ValueError(f"chain version {version} is not installed")
            self._set_active(version)
            return chain

    def get(self, version: str | None = None) -> Chain:
        with self._lock:
            selected = version or self.active_version
            if not selected:
                raise ValueError("no active chain version")
            chain = self._chains.get(selected)
            if chain is None:
                raise ValueError(f"chain version {selected} is not installed")
            return chain

    def definition(self, version: str | None = None) -> ChainDefinition:
        selected = version or self.active_version
        with self._lock:
            if not selected:
                raise ValueError("no active chain version")
            definition = self._versions.get(selected)
            if definition is None:
                raise ValueError(f"chain version {selected} is not installed")
            return definition

    def ref(self, version: str | None = None) -> ChainRef:
        return self.get(version).ref()

    def versions(self) -> list[ChainDefinition]:
        with self._lock:
            return [self._versions[key] for key in sorted(self._versions)]

    def history(self) -> list[dict[str, object]]:
        with self._lock:
            return [
                {**definition.as_dict(), "active": definition.version == self.active_version}
                for definition in self.versions()
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._versions)

    def contains_stage(self, stage: Stage | str) -> bool:
        return self.get().contains(stage)

    def _set_active(self, version: str) -> None:
        self.active_version = version
        if self._store is not None:
            persistence.save_active_version(self._store, version)
