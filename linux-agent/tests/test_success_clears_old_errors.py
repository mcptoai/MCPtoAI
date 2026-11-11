from mcptoai_linux.event_journal import EventJournal


def test_success_clears_old_errors(tmp_path):
    journal=EventJournal(tmp_path/'events.json')
    for tid,kind in [('old','error'),('new','text'),('new','done')]:
        journal.append('chat',{'type':'event','session_id':'chat','turn_id':tid,'event':{'type':kind,'text':'ok'}})
    assert [e['event']['type'] for e in journal.data['chat']]==['text','done']
