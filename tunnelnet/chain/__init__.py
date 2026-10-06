"""Configurable, versioned control chains.

Stage order is assembled from configuration, validated for completeness and
ordering at assembly time, and frozen into immutable, content addressed
versions. Running cycles pin the version active when they start, and the
full version history is retained for replay.
"""

from .catalog import ChainCatalog, VersionExists, VersionMissing
from .config import ChainConfig, default_config, load_config
from .definition import ChainRef, ChainVersion, assemble, compute_digest
from .instance import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    CycleInstance,
)
from .manager import (
    ChainBootError,
    ChainManager,
    InvalidChainAtRest,
    NoActiveChain,
)
from .replay import ReplayResult, replay, replay_version
from .validation import InvalidChain, ValidationErrorItem, ValidationReport, validate

__all__ = [
    "ChainBootError",
    "ChainCatalog",
    "ChainConfig",
    "ChainManager",
    "ChainRef",
    "ChainVersion",
    "CycleInstance",
    "InvalidChain",
    "InvalidChainAtRest",
    "NoActiveChain",
    "ReplayResult",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_RUNNING",
    "ValidationErrorItem",
    "ValidationReport",
    "VersionExists",
    "VersionMissing",
    "assemble",
    "compute_digest",
    "default_config",
    "load_config",
    "replay",
    "replay_version",
    "validate",
]
