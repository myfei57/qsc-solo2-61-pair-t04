"""Persistent helpers for versioned control chain definitions."""

from __future__ import annotations

from ..store import Store
from .definition import ChainDefinition

VERSION_KIND = "chain_version"
POINTER_KIND = "chain_pointer"
POINTER_ID = "active"


def save_definition(store: Store, definition: ChainDefinition) -> None:
    store.save(VERSION_KIND, definition.version, definition.as_dict())


def load_definition(store: Store, version: str) -> ChainDefinition | None:
    payload = store.load(VERSION_KIND, version)
    return None if payload is None else ChainDefinition.from_mapping(payload)


def list_definitions(store: Store) -> list[ChainDefinition]:
    definitions: list[ChainDefinition] = []
    for version in store.list(VERSION_KIND):
        payload = store.load(VERSION_KIND, version)
        if payload is not None:
            definitions.append(ChainDefinition.from_mapping(payload))
    return definitions


def save_active_version(store: Store, version: str) -> None:
    store.save(POINTER_KIND, POINTER_ID, {"version": version})


def load_active_version(store: Store) -> str:
    payload = store.load(POINTER_KIND, POINTER_ID)
    return "" if payload is None else str(payload.get("version", ""))


def restore_definitions(store: Store) -> tuple[list[ChainDefinition], str]:
    return list_definitions(store), load_active_version(store)
