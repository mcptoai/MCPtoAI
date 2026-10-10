"""Private bounded event journal; never persist actionable approvals or tool arguments."""
import json
import os
from pathlib import Path
from .paths import config_dir

class EventJournal:
    def __init__(self, path=None):
        self.path=Path(path) if path else config_dir()/'relay-events.json'
        self.data={}
        try:
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(raw,dict) and raw.get('version')==1:self.data=raw.get('sessions',{})
        except (OSError,ValueError,TypeError):pass
        if not isinstance(self.data,dict):self.data={}

    def append(self,sid,envelope):
        event=envelope.get('event') or {};typ=event.get('type')
        if typ not in ('text','done','error','approval_required','approval_resolved'):return
        if typ=='text':safe={'type':'text','text':str(event.get('text') or '')[:100000],'model':str(event.get('model') or '')[:160]}
        elif typ=='error':safe={'type':'error','message':str(event.get('message') or '')[:2000]}
        elif typ=='approval_required':safe={'type':'approval_interrupted','approval_id':str(event.get('approval_id') or ''),'tool':str(event.get('tool') or '')[:160]}
        elif typ=='approval_resolved':safe={'type':'approval_resolved','approval_id':str(event.get('approval_id') or ''),'status':str(event.get('status') or '')}
        else:safe={'type':'done','model':str(event.get('model') or '')[:160]}
        entry={k:envelope[k] for k in ('type','session_id','seq','event_epoch','turn_id') if k in envelope};entry['event']=safe
        records=self.data.setdefault(sid,[]);records.append(entry);self.data[sid]=records[-250:]
        while len(self.data)>50:self.data.pop(next(iter(self.data)))
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:
                json.dump({'version':1,'sessions':self.data},f,ensure_ascii=False)
                f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path);os.chmod(self.path,0o600)
        finally:
            if tmp.exists():tmp.unlink()
