from mcptoai_core.journal_entry import safe_journal_event


def test_allowlist_excludes_sensitive_fields():
    event = {'type': 'text', 'text': 'answer', 'arguments': {'token': 'secret'}, 'password': 'secret'}
    assert safe_journal_event(event) == {'type': 'text', 'text': 'answer', 'model': ''}
    assert safe_journal_event({'type': 'tool_call', 'arguments': {'secret': 1}}) is None
    assert safe_journal_event({'type': 'approval_required', 'approval_id': 'a',
                               'tool': 'shell', 'approval_token': 'secret'}) == {
        'type': 'approval_interrupted', 'approval_id': 'a', 'tool': 'shell'}


def test_limits_and_resolved_approval():
    assert len(safe_journal_event({'type': 'error', 'message': 'x'*5000})['message']) == 2000
    assert len(safe_journal_event({'type': 'text', 'text': 'x'*120000})['text']) == 100000
    assert safe_journal_event({'type': 'approval_resolved', 'approval_id': 'a',
                               'status': 'denied'}) == {'type': 'approval_resolved', 'approval_id': 'a', 'status': 'denied'}
