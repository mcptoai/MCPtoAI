"""Retryable final-answer history synchronization, independent of browser lifetime."""
from __future__ import annotations
import asyncio
import logging
from .history import history_provider, selected_history_provider_name

logger=logging.getLogger('mcptoai.answer_sync')

async def sync_answers(cfg, journal):
    provider=history_provider(cfg)
    managed=selected_history_provider_name(cfg)=='mcptoai'
    for sid, entries in list(journal.data.items()):
        for item in list(entries):
            if item.get('history_saved') or item.get('event',{}).get('type')!='text': continue
            ev=item['event']
            key=f"{sid}:{item.get('event_epoch','')}:{item.get('turn_id','')}:{item.get('seq','')}"
            try:
                if managed:
                    # Backend's unique event_key prevents duplicates when both web
                    # and device attempt to store the same response.
                    await provider._request('POST',f'{sid}/messages/',body={
                        'role':'assistant','content':ev.get('text',''),
                        'model':ev.get('model',''), 'event_key':key,
                        'tool_data':{'mcptoai_event_key':key}})
                else:
                    existing=await provider.get_chat(sid)
                    if not any((m.get('tool_data') or {}).get('mcptoai_event_key')==key for m in existing.get('messages',[])):
                        await provider.add_message(sid,role='assistant',content=ev.get('text',''),model=ev.get('model',''),tool_data={'mcptoai_event_key':key})
                item['history_saved']=True
                journal._save()
            except Exception as exc:
                logger.warning('Answer history sync pending for %s: %s',sid,type(exc).__name__)

async def answer_sync_loop(cfg,journal):
    while True:
        await sync_answers(cfg,journal)
        await asyncio.sleep(10)
