"""Execute a configured chain while pinning the run to one chain version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from tunnelnet.ns import Stage

from .audit_log import record_event
from .http import Request

if TYPE_CHECKING:
    from .runtime import Runtime


@dataclass(frozen=True)
class CycleInput:
    """Validated input shared by the stage handlers."""

    cabin_id: str
    requester: str
    zone: str
    sensor_id: str
    reading: float
    at: str
    watts: float


@dataclass(frozen=True)
class CycleOutput:
    """Result fields preserved by the existing console contract."""

    approval: str
    alarmed: bool
    reading: float
    zones: list[str]
    alarm_raised: bool
    patrol_route: int
    usage: float
    drain_runs: int

    def as_dict(self) -> dict[str, object]:
        return {
            "approval": self.approval,
            "alarmed": self.alarmed,
            "reading": self.reading,
            "zones": self.zones,
            "alarm_raised": self.alarm_raised,
            "patrol_route": self.patrol_route,
            "usage": self.usage,
            "drain_runs": self.drain_runs,
        }


StageHandler = Callable[["Runtime", "CycleContext", object], None]


@dataclass
class CycleContext:
    """Mutable state shared as a chain run moves through its stages."""

    input: CycleInput
    approval: str = ""
    alarmed: bool = False
    zones: list[str] | None = None
    alarm_raised: bool = False
    patrol_route: int = 0
    usage: float = 0.0
    drain_runs: int = 0

    def output(self) -> CycleOutput:
        return CycleOutput(
            approval=self.approval,
            alarmed=self.alarmed,
            reading=self.input.reading,
            zones=list(self.zones or []),
            alarm_raised=self.alarm_raised,
            patrol_route=self.patrol_route,
            usage=self.usage,
            drain_runs=self.drain_runs,
        )


def cycle_input(request: Request) -> CycleInput:
    samples = request.float_list("samples")
    fallback = request.float_field("value")
    reading = sum(samples) / len(samples) if samples else fallback
    return CycleInput(
        cabin_id=request.str_field("cabin_id"),
        requester=request.str_field("requester", "operator"),
        zone=request.str_field("zone"),
        sensor_id=request.str_field("sensor_id", "sensor-1"),
        reading=reading,
        at=request.str_field("at"),
        watts=request.float_field("watts"),
    )


def execute_cycle(rt: "Runtime", request: Request) -> tuple[CycleOutput, object]:
    """Start a run at the active version and execute every stage in order.

    The active chain is read once before the run starts. Publishing a new
    version during the run cannot change the stages or order of that run.
    """

    chain = rt.chains.get()
    data = cycle_input(request)
    context = CycleContext(input=data)
    run = rt.runs.start(chain.ref(), chain.stages[0].value)

    try:
        for index, stage in enumerate(chain.stages):
            if index > 0:
                run = rt.runs.advance(run.id, stage.value)
            handler = STAGE_HANDLERS.get(stage)
            if handler is None:
                raise ValueError(f"no runtime handler registered for stage {stage.value}")
            handler(rt, context, run)
        completed = rt.runs.complete(run.id)
    except Exception:
        rt.runs.fail(run.id)
        raise

    return context.output(), completed


def _access(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    approval = rt.access.approve(ctx.input.cabin_id, ctx.input.requester)
    ctx.approval = approval.id
    record_event(rt, "access_approved", approval.id, run=run, stage=Stage.ACCESS.value)


def _environment(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    ctx.alarmed = rt.env.sample(ctx.input.sensor_id, ctx.input.reading, ctx.input.at)


def _ventilation(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    # The ventilation bank remains available for the fire linkage below.
    if not rt.ventilation.running():
        rt.ventilation.start()


def _fire(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    zones = rt.fire.activate_zones(ctx.input.zone)
    rt.fire.handle_smoke(ctx.input.zone)
    raised = rt.fire.raise_alarm(f"{ctx.input.zone}:{ctx.input.at}")
    ctx.zones = zones
    ctx.alarm_raised = raised


def _patrol(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    rt.patrol.check_in(ctx.input.cabin_id, ctx.input.at)
    ctx.patrol_route = rt.patrol.route_len()


def _energy(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    ctx.usage = rt.quota.add_usage(ctx.input.cabin_id, ctx.input.watts)


def _audit(rt: "Runtime", ctx: CycleContext, run: object) -> None:
    rt.drain.start_drain(ctx.input.cabin_id)
    rt.drain.record_cycle(ctx.input.cabin_id, ctx.input.at)
    ctx.drain_runs = rt.drain.run_count()
    record_event(rt, "cycle", ctx.input.cabin_id, run=run, stage=Stage.AUDIT.value)


STAGE_HANDLERS: dict[Stage, StageHandler] = {
    Stage.ACCESS: _access,
    Stage.ENVIRONMENT: _environment,
    Stage.VENTILATION: _ventilation,
    Stage.FIRE: _fire,
    Stage.PATROL: _patrol,
    Stage.ENERGY: _energy,
    Stage.AUDIT: _audit,
}
