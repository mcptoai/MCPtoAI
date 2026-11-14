"""Desktop MCP SDK 2.x stdio owner-task lifecycle.

Linux SDK 2.x uses the same owner-task lifecycle as Desktop.
"""
from __future__ import annotations
import asyncio
import logging
from mcp import ClientSession
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)
STDIO_CLOSE_TIMEOUT = 10

class StdioRuntime:
    """Tek bir stdio MCP sunucusunun yaşam döngüsü.

    AnyIO cancel scope'ları açıldıkları görevde kapatılmalıdır (aksi halde
    "Attempted to exit cancel scope in a different task" hatası). Bu yüzden
    stdio_client ve ClientSession bu sınıfın SAHİP görevinde 'async with' ile
    açılır ve kapanış da aynı görevde yapılır. Diğer görevler yalnızca hazır
    oturumu kullanır; araç çağrıları görevden bağımsızdır ve paralel yapılabilir.
    """

    def __init__(self, sid, params, fingerprint):
        self.sid=sid; self.params=params; self.fingerprint=fingerprint
        self.session=None
        self._task=None
        self._stop=asyncio.Event()
        self._ready=asyncio.get_running_loop().create_future()
        # Başlatma zaman aşımına uğrarsa geç gelen hata "never retrieved" uyarısı üretmesin.
        self._ready.add_done_callback(lambda f: f.cancelled() or f.exception())

    @property
    def alive(self):
        return self._task is not None and not self._task.done() and self.session is not None

    async def start(self, timeout=None):
        self._task=asyncio.create_task(self._own(),name=f"mcp-stdio:{self.sid}")
        try:
            if timeout: await asyncio.wait_for(asyncio.shield(self._ready),timeout)
            else: await asyncio.shield(self._ready)
        except BaseException:
            await self.close()
            raise
        return self.session

    async def _own(self):
        try:
            async with stdio_client(self.params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.session=session
                    if not self._ready.done(): self._ready.set_result(session)
                    await self._stop.wait()
        except asyncio.CancelledError:
            if not self._ready.done(): self._ready.set_exception(RuntimeError(f"MCP stdio server {self.sid} start was cancelled"))
            raise
        except Exception as exc:
            if not self._ready.done(): self._ready.set_exception(exc)
            else: logger.warning("MCP stdio server %s stopped: %s",self.sid,exc)
        finally:
            self.session=None

    async def close(self, timeout=STDIO_CLOSE_TIMEOUT):
        self._stop.set()
        task=self._task
        if task is None or task.done(): return
        try:
            await asyncio.wait_for(asyncio.shield(task),timeout)
        except asyncio.TimeoutError:
            logger.warning("MCP stdio server %s did not stop in %ss; cancelling its owner task",self.sid,timeout)
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        except Exception as exc:
            logger.debug("MCP stdio server %s close: %s",self.sid,exc)
