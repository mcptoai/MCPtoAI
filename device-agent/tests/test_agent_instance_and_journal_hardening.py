"""Tek agent kilidi ve dayanıklı olay kaydı regresyon testleri."""
import json
from mcptoai_agent.event_journal import EventJournal


def test_event_journal_flush_and_restart(tmp_path):
    path = tmp_path / 'relay-events.json'
    journal = EventJournal(path)
    journal.append('chat', {'event': {'type': 'text', 'text': 'hello'}})
    journal.flush()
    assert path.exists()
    assert json.loads(path.read_text())['sessions']['chat']
    restored = EventJournal(path)
    assert restored.data['chat']


def test_event_journal_failed_write_does_not_raise(tmp_path, monkeypatch):
    journal = EventJournal(tmp_path / 'relay-events.json')
    def broken():
        raise OSError('disk unavailable')
    monkeypatch.setattr(journal, '_save_locked', broken)
    journal.append('chat', {'event': {'type': 'done'}})
    assert journal._failures == 1
