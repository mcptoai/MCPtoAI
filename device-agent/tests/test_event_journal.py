from mcptoai_agent.event_journal import EventJournal

def test_journal_keeps_final_answer_but_not_approval_arguments(tmp_path):
    path=tmp_path/'events.json'
    j=EventJournal(path)
    j.append('s',{'type':'event','session_id':'s','seq':1,'event_epoch':'e','turn_id':'t','event':{'type':'approval_required','approval_id':'a','arguments':{'password':'secret'}}})
    j.append('s',{'type':'event','session_id':'s','seq':2,'event_epoch':'e','turn_id':'t','event':{'type':'text','text':'finished'}})
    j.append('s',{'type':'event','session_id':'s','seq':3,'event_epoch':'e','turn_id':'t','event':{'type':'done'}})
    assert 'secret' not in path.read_text()
    assert [x['event']['type'] for x in EventJournal(path).data['s']]==['approval_interrupted','text','done']
    assert path.stat().st_mode & 0o077 == 0
