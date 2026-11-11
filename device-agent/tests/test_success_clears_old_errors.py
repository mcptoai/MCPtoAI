from mcptoai_agent.event_journal import EventJournal


def test_successful_turn_clears_prior_errors_only_for_same_chat(tmp_path):
    journal=EventJournal(tmp_path/'events.json')
    def add(sid,tid,seq,kind):
        journal.append(sid,{'type':'event','session_id':sid,'turn_id':tid,'seq':seq,
                            'event':{'type':kind,'text':'answer','message':'failure'}})
    add('chat','old',1,'error');add('other','old',1,'error')
    add('chat','new',2,'text');add('chat','new',3,'done');journal.flush()
    loaded=EventJournal(tmp_path/'events.json')
    assert [e['event']['type'] for e in loaded.data['chat']]==['text','done']
    assert loaded.data['other'][0]['event']['type']=='error'


def test_failed_turn_does_not_clear_errors(tmp_path):
    journal=EventJournal(tmp_path/'events.json')
    for tid,kind in [('old','error'),('new','done')]:
        journal.append('chat',{'type':'event','session_id':'chat','turn_id':tid,'event':{'type':kind}})
    assert any(e['event']['type']=='error' for e in journal.data['chat'])
