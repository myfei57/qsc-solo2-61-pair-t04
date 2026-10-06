"""Factory helpers for the default configured control chain."""

from __future__ import annotations

from .assembler import assemble_or_raise
from .chain import Chain
from .config import default_chain_document
from .definition import ChainDefinition


def control_chain_definition() -> ChainDefinition:
    """Return the content-versioned default chain definition."""

    return ChainDefinition.from_mapping(default_chain_document()).with_version()


def control_chain() -> Chain:
    """Assemble the default configured chain used by legacy callers."""

    return assemble_or_raise(control_chain_definition())
