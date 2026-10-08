from __future__ import annotations
import asyncio,json,time
from .config import settings
from .providers import make_provider
from .providers.base import ToolSpec

async def probe():
    started=time.monotonic(); p=make_provider(settings)
    models=await p.list_models()
    result={"ok":True,"provider":settings.provider,"models":models,"latency_ms":round((time.monotonic()-started)*1000),"tool_calling":None}
    if settings.model:
        try:
            tool=ToolSpec("mcptoai_capability_probe","A harmless capability probe. Call this tool now.",{"type":"object","properties":{},"additionalProperties":False})
            turn=await p.complete("You are testing tool-call capability. You must call mcptoai_capability_probe and do nothing else.",[{"role":"user","content":"Run the capability probe tool now."}],[tool])
            result["tool_calling"]=any(c.name=="mcptoai_capability_probe" for c in turn.tool_calls)
        except Exception as exc:
            result["tool_calling"]=False; result["tool_error"]=f"{type(exc).__name__}: {exc}"[:240]
    return result

def run(): print(json.dumps(asyncio.run(probe())),flush=True)
