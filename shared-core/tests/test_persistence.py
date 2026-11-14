from mcptoai_core.persistence import (
    load_journal_payload, load_receipt_payload, interrupt_running_receipts,
)


def test_journal_restart_version_and_ttl():
    entry = {'recorded_at': 1000, 'event': {'type': 'done'}}
    raw = {'version': 1, 'sessions': {'s': [entry]}}
    assert load_journal_payload(raw, now=1000) == {'s': [entry]}
    assert load_journal_payload(raw, now=1000 + 86401) == {}
    assert load_journal_payload({'version': 2, 'sessions': raw['sessions']}, now=1000) == {}
    assert load_journal_payload(None, now=1000) == {}


def test_receipts_restart_interrupt_and_preserve_order():
    raw = {'version': 1, 'items': {'first': {'status': 'running'}, 'second': {'status': 'completed'}}}
    items = load_receipt_payload(raw)
    assert list(items) == ['first', 'second']
    assert interrupt_running_receipts(items, 1234)
    assert items['first'] == {'status': 'interrupted', 'updated_at': 1234}
    assert items['second'] == {'status': 'completed'}
    assert not interrupt_running_receipts(items, 1235)


def test_receipts_ignore_invalid_entries():
    assert list(load_receipt_payload({'items': {'valid': {}, 'bad': 123}})) == ['valid']
    assert not load_receipt_payload({'items': []})
    assert not load_receipt_payload(None)
