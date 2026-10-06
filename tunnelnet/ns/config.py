"""Built-in and file loaded chain configurations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .definition import DEFAULT_REQUIRED_STAGES, DEFAULT_STAGE_ACTIONS
from .stages import Stage


def default_chain_document() -> dict[str, object]:
    """Return the standard seven-stage tunnel chain."""

    return {
        "name": "tunnel-control",
        "required_stages": [stage.value for stage in DEFAULT_REQUIRED_STAGES],
        "before": [
            {"first": Stage.ACCESS.value, "second": Stage.FIRE.value},
            {"first": Stage.ENVIRONMENT.value, "second": Stage.VENTILATION.value},
            {"first": Stage.FIRE.value, "second": Stage.PATROL.value},
            {"first": Stage.PATROL.value, "second": Stage.ENERGY.value},
            {"first": Stage.ENERGY.value, "second": Stage.AUDIT.value},
        ],
        "stages": [
            {"stage": stage.value, "action": DEFAULT_STAGE_ACTIONS[stage]}
            for stage in DEFAULT_REQUIRED_STAGES
        ],
    }


def load_chain_document(path: str | Path) -> dict[str, object]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("chain configuration must be a JSON object")
    return dict(payload)
