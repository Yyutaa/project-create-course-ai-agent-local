"""SSE invalidation notices for a Run's public read models."""

from collections.abc import AsyncIterator

import anyio
from fastapi import APIRouter, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.run_routes import RunnerDep
from app.v0.storage import FactStore


router = APIRouter(prefix="/api/v0/runs", tags=["v0-runs"])


async def watch_run(
    store: FactStore, run_id: str, interval: float = 1.0,
) -> AsyncIterator[ServerSentEvent]:
    previous = -1
    idle_checks = 0
    while True:
        revision = await anyio.to_thread.run_sync(store.change_seq, run_id)
        if revision != previous:
            yield ServerSentEvent(
                data={"run_id": run_id, "revision": revision},
                event="run.changed", id=str(revision),
            )
            previous = revision
            idle_checks = 0
        else:
            idle_checks += 1
            if idle_checks >= 15:
                yield ServerSentEvent(comment="keepalive")
                idle_checks = 0
        await anyio.sleep(interval)


@router.get("/{run_id}/stream", response_class=EventSourceResponse)
def stream_run(run_id: str, runner: RunnerDep) -> EventSourceResponse:
    try:
        runner.store.change_seq(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run 不存在") from error
    return EventSourceResponse(
        watch_run(runner.store, run_id), headers={"Cache-Control": "no-cache"}
    )
