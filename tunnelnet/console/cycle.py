"""One full tunnel control cycle walked in chain order.

The cycle pins the chain version active at start time. Every audit row it
writes and the persisted cycle instance carry that same :class:`ChainRef`,
and publishing a new chain while the cycle runs cannot change the stages the
instance was opened with.
"""

from __future__ import annotations

from .audit_log import record_event
from .http import Request, Response, json_response
from .runtime import Runtime


def run_cycle(rt: Runtime, request: Request) -> Response:
    """Walk the whole chain once, on the version pinned when it starts."""

    cabin_id = request.str_field("cabin_id")
    requester = request.str_field("requester", "operator")
    zone = request.str_field("zone")
    sensor_id = request.str_field("sensor_id", "sensor-1")
    samples = request.float_list("samples")
    fallback = request.float_field("value")
    at = request.str_field("at")
    watts = request.float_field("watts")

    reading = sum(samples) / len(samples) if samples else fallback

    # Pin before any stage action: the ref below never changes even if a new
    # chain version is published mid-cycle.
    instance = rt.chains.start_cycle(cabin_id)
    try:
        approval = rt.access.approve(cabin_id, requester)
        record_event(
            rt,
            "access_approved",
            approval.id,
            instance=instance,
            stage="access",
        )

        alarmed = rt.env.sample(sensor_id, reading, at)

        zones = rt.fire.activate_zones(zone)
        rt.fire.handle_smoke(zone)
        raised = rt.fire.raise_alarm(f"{zone}:{at}")

        rt.patrol.check_in(cabin_id, at)

        usage = rt.quota.add_usage(cabin_id, watts)

        rt.drain.start_drain(cabin_id)
        rt.drain.record_cycle(cabin_id, at)

        record_event(rt, "cycle", cabin_id, instance=instance, stage=instance.stages[-1])

        chain = rt.chains.chain_for_instance(instance.id)
        result = {
            "approval": approval.id,
            "alarmed": alarmed,
            "reading": reading,
            "zones": zones,
            "alarm_raised": raised,
            "patrol_route": rt.patrol.route_len(),
            "usage": usage,
            "drain_runs": rt.drain.run_count(),
            "audit_count": rt.audit.count(),
            "last_stage": chain.last() or "",
        }
        rt.chains.finish_cycle(instance, result)
    except Exception:
        rt.chains.fail_cycle(instance, "cycle aborted")
        raise

    payload: dict[str, object] = {
        **result,
        "cycle_id": instance.id,
        "chain": instance.chain.as_dict(),
    }
    return json_response(payload)
