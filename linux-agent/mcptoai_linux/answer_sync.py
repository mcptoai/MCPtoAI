"""Retry completed assistant answers independently of the browser connection."""
import asyncio
import logging
from .local_history import LocalHistoryStore

logger=logging.getLogger('mcptoai.answer_sync')

async def sync_answers(cfg,journal):
    local=cfg.user_settings.get('history_provider')=='local'
    for sid,items in list(journal.data.items()):
        for item in list(items):
            if item.get('history_saved') or item.get('event',{}).get('type')!='text':continue
            ev=item['event'];key=f"{sid}:{item.get('event_epoch','')}:{item.get('turn_id','')}:{item.get('seq','')}"
            try:
                if local:
                    store=LocalHistoryStore()
                    chat=store.get_chat(sid)
                    if chat is None:continue
                    if not any((m.get('tool_data') or {}).get('mcptoai_event_key')==key for m in chat.get('messages',[])):
                        store.add_message(sid,role='assistant',content=ev.get('text',''),model=ev.get('model',''),tool_data={'mcptoai_event_key':key})
                else:
                    from .relay_client import handle_cloud_chat_request
                    result=await handle_cloud_chat_request(cfg,{'action':'cloud_chat_add_message','session_id':sid,'role':'assistant','content':ev.get('text',''),'model':ev.get('model',''),'tool_data':{'mcptoai_event_key':key}})
                    if not result.get('ok'):continue
                item['history_saved']=True
                journal._save()
            except Exception as exc:
                logger.warning('Answer history sync pending for %s: %s',sid,type(exc).__name__)

async def answer_sync_loop(cfg,journal):
    while True:
        await sync_answers(cfg,journal)
        await asyncio.sleep(10)
