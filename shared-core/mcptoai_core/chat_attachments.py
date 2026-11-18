"""Ephemeral chat receiver on the authenticated device socket; never workspace IO."""
import asyncio
import base64
import hashlib
import logging
import re
import tempfile
import time
import uuid
from pathlib import Path
from . import documents as d

LOG = logging.getLogger('mcptoai.chat_attachments')
CAPABILITY = 'chat_attachments_v1'
CHAT_SUFFIXES = frozenset('png jpg jpeg webp gif heic pdf txt md rtf csv tsv json xml html yaml yml log docx doc xlsx xls pptx ppt odt ods odp js jsx ts tsx py rb go rs java c h cpp hpp cs swift kt kts m mm php css scss sql sh bash zsh toml ini conf vue svelte'.split())


def _id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('id')
    return value


class ChatAttachments:
    def __init__(self):
        self.entries = {}
        self.timers = {}

    def drop(self, tid):
        timer = self.timers.pop(tid, None)
        if timer: timer.cancel()
        entry = self.entries.pop(tid, None)
        if entry: entry['file'].close()

    def close(self):
        for tid in list(self.entries): self.drop(tid)

    def touch(self, tid):
        self.entries[tid]['expires'] = time.monotonic() + 120
        timer = self.timers.pop(tid, None)
        if timer: timer.cancel()
        self.timers[tid] = asyncio.get_running_loop().call_later(120, self.drop, tid)

    def expire(self):
        for tid, entry in list(self.entries.items()):
            if entry['expires'] <= time.monotonic(): self.drop(tid)

    async def handle(self, msg):
        """None means not a chat transfer: leave workspace dispatch untouched."""
        kind, tid = msg.get('type'), msg.get('transfer_id')
        if kind == 'file_offer' and msg.get('purpose') != 'chat': return None
        if kind not in {'file_offer', 'file_chunk', 'file_finish', 'file_cancel'}: return None
        self.expire()
        # The chat receiver owns only a purpose=chat offer and the transfer IDs
        # it accepted. Device-upload file_* frames use the SAME protocol type
        # names, but must not cause an error/ACK from the chat receiver.
        if kind != 'file_offer' and (not isinstance(tid, str) or tid not in self.entries):
            return None
        try:
            _id(tid)
            if kind == 'file_offer':
                sid, turn = _id(msg.get('session_id')), _id(msg.get('turn_id'))
                name, size, digest = msg.get('name'), msg.get('size'), msg.get('sha256')
                if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,119}', name)
                    or name.rsplit('.', 1)[-1].lower() not in CHAT_SUFFIXES
                    or type(size) is not int or not 0 < size <= d.MAX_FILE_BYTES
                    or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)
                    or 'workspace' in msg or 'path' in msg):
                    raise ValueError('offer')
                if tid in self.entries: raise ValueError('duplicate')
                batch = [e for e in self.entries.values() if (e['session_id'], e['turn_id']) == (sid, turn)]
                if len(batch) >= 4 or sum(e['size'] for e in batch) + size > d.MAX_TURN_BYTES or len(self.entries) >= 64:
                    raise d.DocumentError('attachment_quota', 'Attachment quota exceeded.')
                self.entries[tid] = dict(session_id=sid, turn_id=turn, name=name, size=size, sha256=digest,
                                         file=tempfile.TemporaryFile(), index=0, received=0, completed=False)
                self.touch(tid)
                LOG.info('chat_attachment_received transfer_id=%s size=%d type=%s', tid, size, name.rsplit('.',1)[-1].lower())
                return dict(type='file_ready', transfer_id=tid, status='ready')
            entry = self.entries.get(tid)
            if entry is None: raise ValueError('missing')
            if kind == 'file_cancel':
                LOG.info('chat_attachment_cancelled transfer_id=%s bytes=%d', tid, entry['received'])
                self.drop(tid)
                return dict(type='file_result', transfer_id=tid, status='cancelled', reason='cancelled')
            if entry['completed']: raise ValueError('completed')
            if kind == 'file_chunk':
                index, encoded = msg.get('index'), msg.get('data')
                if type(index) is not int or index != entry['index'] or index >= 80 or not isinstance(encoded, str) or len(encoded) > 4*((128*1024+2)//3):
                    raise ValueError('chunk')
                data = base64.b64decode(encoded, validate=True)
                if not 0 < len(data) <= 128*1024 or entry['received'] + len(data) > entry['size']: raise ValueError('size')
                entry['file'].write(data)
                entry['received'] += len(data)
                entry['index'] += 1
                self.touch(tid)
                return dict(type='file_ack', transfer_id=tid, index=index)
            entry['file'].seek(0)
            data = entry['file'].read()
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']: raise ValueError('integrity')
            # Synchronous validation keeps cancellation/disconnect from racing a parser
            # that still owns staging. Size and parser expansion are strictly bounded.
            entry['media_type'] = d.validate_complete(data, entry['name'].rsplit('.', 1)[-1].lower())
            entry['completed'] = True
            LOG.info('chat_attachment_verified transfer_id=%s bytes=%d type=%s', tid, len(data), entry['media_type'])
            self.touch(tid)
            return dict(type='file_result', transfer_id=tid, status='completed', attachment_id=tid, sha256=entry['sha256'])
        except Exception as exc:
            LOG.info('chat_attachment_rejected transfer_id=%s stage=%s error_type=%s', tid, kind, type(exc).__name__)
            if isinstance(tid, str): self.drop(tid)
            return dict(type='file_ready' if kind == 'file_offer' else 'file_result', transfer_id=tid,
                        status='denied' if kind == 'file_offer' else 'failed',
                        reason=exc.code if isinstance(exc, d.DocumentError) else 'invalid_transfer')

    def consume(self, ids, session_id, turn_id):
        self.expire()
        selected = []
        try:
            _id(session_id); _id(turn_id)
            if not isinstance(ids, list) or not 1 <= len(ids) <= 4: raise ValueError('ids')
            if any(not isinstance(tid, str) for tid in ids) or len(set(ids)) != len(ids): raise ValueError('ids')
            for tid in ids:
                _id(tid)
                e = self.entries.get(tid)
                if not e or not e['completed'] or (e['session_id'], e['turn_id']) != (session_id, turn_id): raise ValueError('receipt')
                selected.append(e)
            if sum(e['size'] for e in selected) > d.MAX_TURN_BYTES: raise ValueError('quota')
            files = []
            for e in selected:
                e['file'].seek(0)
                files.append({k: e[k] for k in ('name', 'size', 'media_type')} | {'data_base64': base64.b64encode(e['file'].read()).decode('ascii')})
            return {'version': 1, 'files': files}
        except Exception:
            raise d.DocumentError('invalid_attachments', 'Attachments are missing, expired, or invalid. Files were not sent to the model.') from None
        finally:
            # Release the entire turn even on atomic validation failure.
            for tid, e in list(self.entries.items()):
                if (e['session_id'], e['turn_id']) == (session_id, turn_id): self.drop(tid)
