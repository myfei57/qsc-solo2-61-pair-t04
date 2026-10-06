"""One full tunnel control cycle walked in chain order."""

from __future__ import annotations

from .executor import execute_cycle
from .http import Request, Response, json_response
from .runtime import Runtime


def run_cycle(rt: Runtime, request: Request) -> Response:
    """Walk the whole active chain once, pinned to its version for the run."""

    output, run = execute_cycle(rt, request)
    payload = output.as_dict()
    payload.update(
        {
            "audit_count": rt.audit.count(),
            "last_stage": run.stage if run.status != "completed" else (run.completed_stages[-1] if run.completed_stages else ""),
            "chain_version": run.chain.version,
            "chain_fingerprint": run.chain.fingerprint,
            "run_id": run.id,
        }
    )
    return json_response(payload)
