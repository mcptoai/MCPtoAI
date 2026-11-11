import json
import time
from mcptoai_agent.event_journal import EventJournal, JOURNAL_TTL_SECONDS, prune_expired


def test_prune_expired_and_legacy_fail_closed(tmp_path):
    now = time.time()
    good = {'seq': 2, 'event': {'type': 'text'}, 'recorded_at': now - 10}
    old = {'seq': 1, 'event': {'type': 'text'}, 'recorded_at': now - JOURNAL_TTL_SECONDS - 1}
    legacy = {'seq': 3, 'event': {'type': 'text'}}
    assert prune_expired({'session': [old, legacy, good]}, now) == {'session': [good]}
    path = tmp_path / 'relay-events.json'
    path.write_text(json.dumps({'version': 1, 'sessions': {'session': [old, legacy, good]}}))
    journal = EventJournal(path)
    assert journal.data == {'session': [good]}
    journal.append('session', {'type': 'event', 'session_id': 'session', 'seq': 4, 'event': {'type': 'done'}})
    journal.flush()
    assert len(json.loads(path.read_text())['sessions']['session']) == 2


def test_expired_sessions_not_restored(tmp_path):
    path = tmp_path / 'relay-events.json'
    path.write_text(json.dumps({'version': 1, 'sessions': {'stale': [{'recorded_at': time.time() - JOURNAL_TTL_SECONDS - 5}]}}))
    assert EventJournal(path).data == {}
