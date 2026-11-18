"""Merge operator progress with engine events while the model awaits tool completion."""
import asyncio
from contextlib import aclosing
from dataclasses import dataclass

from app.mcp.types import MCPProgressUpdate


@dataclass(frozen=True)
class ToolProgressEvent:
    call_id: str
    name: str
    update: MCPProgressUpdate


async def operator_events(operation, state, call_id, name):
    from app.mcp.progress import progress_scope
    async def execute():
        with progress_scope(lambda update: state.progress_callback(call_id, name, update)):
            yield await operation()
    async with aclosing(execute()) as source, aclosing(stream_with_progress(source, state)) as events:
        async for event in events:
            yield (event.update, None) if isinstance(event, ToolProgressEvent) else (None, event)


async def stream_with_progress(source, state):
    queue = asyncio.Queue(maxsize=128)
    previous = state.progress_callback

    def emit(call_id, name, update):
        if not queue.full():
            queue.put_nowait((False, ToolProgressEvent(call_id, name, update), None))

    async def produce():
        try:
            async for event in source:
                resume = asyncio.get_running_loop().create_future()
                await queue.put((False, event, resume))
                await resume
        except BaseException as error:
            if not closing:
                await queue.put((True, error, None))
        else:
            await queue.put((True, None, None))

    closing = False
    state.progress_callback = emit
    task = asyncio.create_task(produce())
    try:
        while True:
            done, item, resume = await queue.get()
            if done:
                if item is not None:
                    raise item
                return
            yield item
            if resume and not resume.done():
                resume.set_result(None)
    finally:
        closing = True
        state.progress_callback = previous
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
