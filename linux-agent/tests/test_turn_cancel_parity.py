"""Linux turn cancellation matches the Desktop protocol."""
import asyncio
from types import SimpleNamespace
from mcptoai_linux.relay_client import RelayClient


def _client():
    c=object.__new__(RelayClient)
    c._turn_tasks={}
    c._cancel_requested=set()
    events=[]
    async def emit(sid, event): events.append((sid,event))
    c._send_event=emit
    return c,events


def test_cancel_active_turn_and_duplicate_request():
    async def check():
        c,events=_client()
        ready=asyncio.Event()
        async def running():
            ready.set()
            await asyncio.Event().wait()
        task=asyncio.create_task(running())
        await ready.wait()
        c._turn_tasks['session']=('turn',task)
        await c._cancel_turn({'session_id':'session','turn_id':'turn'})
        await c._cancel_turn({'session_id':'session','turn_id':'turn'})
        assert c._cancel_requested=={'turn'}
        assert not events
        try: await task
        except asyncio.CancelledError: pass
        else: assert False, 'task was not cancelled'
    asyncio.run(check())


def test_wrong_turn_does_not_cancel_and_returns_not_running():
    async def check():
        c,events=_client()
        task=asyncio.create_task(asyncio.sleep(30))
        c._turn_tasks['session']=('turn',task)
        await c._cancel_turn({'session_id':'session','turn_id':'other'})
        assert not task.cancelled()
        assert events==[('session',{'type':'cancelled','status':'not_running'})]
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    asyncio.run(check())
