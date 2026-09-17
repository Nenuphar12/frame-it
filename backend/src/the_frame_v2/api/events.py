from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from sse_starlette import EventSourceResponse, ServerSentEvent

from the_frame_v2.api.deps import Ctx, Uploader

router = APIRouter(tags=["events"])


@router.get("/events", response_class=EventSourceResponse)
async def events(principal: Uploader, ctx: Ctx) -> EventSourceResponse:
    """Server-sent events: `photo.ingested`, `photo.ingest_failed`, `job.progress`, `job.failed`."""

    async def stream() -> AsyncIterator[ServerSentEvent]:
        yield ServerSentEvent(event="ready", data="{}")
        async for event in ctx.broker.subscribe(
            is_admin=principal.is_admin, device_key=principal.device_key
        ):
            yield ServerSentEvent(event=event.name, data=json.dumps(event.data))

    return EventSourceResponse(stream(), ping=15, headers={"Cache-Control": "no-store"})
