"""Private bounded event journal; never persist actionable approvals or tool arguments."""
import json
import time
import os
from pathlib import Path
from .paths import config_dir

JOURNAL_TTL_SECONDS = 24 * 60 * 60

from mcptoai_core.journal import prune_expired, JOURNAL_TTL_SECONDS

from mcptoai_core.journal_entry import safe_journal_event as _safe_journal_event

from mcptoai_core.persistence import load_journal_payload as _load_journal_payload

class EventJournal:
    def __init__(self, path=None):
        self.path=Path(path) if path else config_dir()/'relay-events.json'
        self.data={}
        try:
            raw=json.loads(self.path.read_text(encoding='utf-8'))
            self.data = _load_journal_payload(raw)
        except (OSError,ValueError,TypeError):pass
        self.data=prune_expired(self.data)

    def append(self,sid,envelope):
        event=envelope.get('event') or {};typ=event.get('type')
        safe=_safe_journal_event(event)
        if safe is None:return
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
