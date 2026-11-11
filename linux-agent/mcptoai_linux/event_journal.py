"""Private bounded event journal; never persist actionable approvals or tool arguments."""
import json
import time
import os
from pathlib import Path
from .paths import config_dir

JOURNAL_TTL_SECONDS = 24 * 60 * 60

def prune_expired(data, now=None):
    now = time.time() if now is None else now
    if not isinstance(data, dict):
        return {}
    result = {}
    for sid, entries in data.items():
        if not isinstance(sid, str) or not isinstance(entries, list):
            continue
        kept = [e for e in entries if isinstance(e, dict)
                and isinstance(e.get('recorded_at'), (int, float))
                and not isinstance(e.get('recorded_at'), bool)
                and now - JOURNAL_TTL_SECONDS <= e['recorded_at'] <= now + 60]
        if kept:
            result[sid] = kept[-250:]
    return dict(list(result.items())[-50:])

class EventJournal:
    def __init__(self, path=None):
        self.path=Path(path) if path else config_dir()/'relay-events.json'
        self.data={}
        try:
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw,dict) and raw.get('version')==1:self.data=raw.get('sessions',{})
        except (OSError,ValueError,TypeError):pass
        self.data=prune_expired(self.data)

    def append(self,sid,envelope):
        event=envelope.get('event') or {};typ=event.get('type')
        if typ not in ('text','done','error','approval_required','approval_resolved'):return
        if typ=='text':safe={'type':'text','text':str(event.get('text') or '')[:100000],'model':str(event.get('model') or '')[:160]}
        elif typ=='error':safe={'type':'error','message':str(event.get('message') or '')[:2000]}
        elif typ=='approval_required':safe={'type':'approval_interrupted','approval_id':str(event.get('approval_id') or ''),'tool':str(event.get('tool') or '')[:160]}
        elif typ=='approval_resolved':safe={'type':'approval_resolved','approval_id':str(event.get('approval_id') or ''),'status':str(event.get('status') or '')}
        else:safe={'type':'done','model':str(event.get('model') or '')[:160]}
        entry={k:envelope[k] for k in ('type','session_id','seq','event_epoch','turn_id') if k in envelope};entry['event']=safe
        entry['recorded_at']=envelope.get('recorded_at',time.time())
        self.data=prune_expired(self.data)
        records=self.data.setdefault(sid,[])
        if typ=='done' and envelope.get('turn_id') and any(
            r.get('turn_id')==envelope['turn_id'] and r.get('event',{}).get('type')=='text'
            for r in records
        ):
            records[:]=[r for r in records if not (
                r.get('event',{}).get('type')=='error' and r.get('turn_id')!=envelope['turn_id'])]
        records.append(entry);self.data[sid]=records[-250:]
        while len(self.data)>50:self.data.pop(next(iter(self.data)))
        self._save()

    def _save(self):
        self.data=prune_expired(self.data)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump({'version':1,'sessions':self.data},f,ensure_ascii=False)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path);os.chmod(self.path,0o600)
        finally:
            if tmp.exists():tmp.unlink()
