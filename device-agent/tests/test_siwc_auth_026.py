import time
from unittest.mock import patch
from mcptoai_agent import siwc_auth
import pytest

@pytest.fixture(autouse=True)
def owner_fixture():
    with patch.object(siwc_auth, "paired_owner", return_value="auth0|owner"):
        yield


def test_host_identity_reused():
    memory={}
    with patch.object(siwc_auth,'vault_get',side_effect=memory.get),patch.object(siwc_auth,'vault_put',side_effect=memory.__setitem__):
        first=siwc_auth.host_id()
        assert first.startswith('urn:uuid:')
        assert siwc_auth.host_id()==first


def test_status_never_returns_credentials():
    account={'mcptoai_owner_sub':'auth0|owner','access_token':'secret','refresh_token':'private','scopes':['chatgpt.tokens.use.direct'],'expires_at':time.time()+3600}
    with patch.object(siwc_auth,'vault_get',return_value=account):
        assert siwc_auth.status()=={'connected':True,'linked':True,'sharing':True,'reason':None,'expires_at':int(account['expires_at'])}


def test_refresh_rotates_both_tokens_under_lock():
    from contextlib import nullcontext
    account={'mcptoai_owner_sub':'auth0|owner','client_id':'issued','refresh_token':'old','access_token':'old-access','subject':'same-account','scopes':['chatgpt.tokens.use.direct'],'expires_at':0}
    store={'account':account}
    with patch.object(siwc_auth,'vault_get',side_effect=store.get),patch.object(siwc_auth,'vault_put',side_effect=store.__setitem__),patch.object(siwc_auth,'credential_lock',return_value=nullcontext()),patch.object(siwc_auth,'request_json',return_value={'access_token':'new-access','refresh_token':'new','id_token':'new-id','expires_in':3600}),patch.object(siwc_auth,'verify_identity',return_value={'sub':'same-account'}):
        assert siwc_auth.access_token()=='new-access'
        assert store['account']['refresh_token']=='new'


def test_logout_reports_unconfirmed_revocation():
    account={'mcptoai_owner_sub':'auth0|owner','client_id':'issued','refresh_token':'private'}
    deleted=[]
    with patch.object(siwc_auth,'vault_get',return_value=account),patch.object(siwc_auth,'request_json',side_effect=RuntimeError('offline')),patch.object(siwc_auth,'delete_secret',side_effect=deleted.append):
        assert siwc_auth.sign_out()=={'disconnected':True,'revoked':False}
        assert deleted==['siwc:account']


def test_callback_rejects_invalid_state_and_accepts_valid_state():
    import urllib.request
    import urllib.error
    port, result, finished, worker = siwc_auth.callback_listener('expected', timeout=3)
    worker.start()
    with __import__('pytest').raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f'http://127.0.0.1:{port}/auth/callback?state=wrong&code=secret', timeout=2)
    assert exc.value.code == 400
    assert not result
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/auth/callback?state=expected&code=sample&client_id=issued', timeout=2) as response:
        assert response.status == 200
    worker.join(timeout=3)
    assert finished.is_set() and result['code']=='sample' and result['client_id']=='issued'


def test_sign_in_validates_oidc_and_saves_only_after_verification():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    memory={}
    callback={'code':'sample-code','client_id':'issued-client'}
    worker=MagicMock()
    worker.is_alive.return_value=False
    tokens={'access_token':'access','refresh_token':'refresh','id_token':'id',
            'scope':'openid chatgpt.tokens.use.direct','expires_in':3600}
    def endpoint(url, **kwargs):
        if url.endswith('/oauth/token'):
            assert kwargs['data']['client_id']=='issued-client'
            assert kwargs['data']['code_verifier']
            return tokens
        return {'jwks_uri':siwc_auth.AUTH+'/jwks'}
    class FakeJWK:
        def __init__(self,uri):
            assert uri==siwc_auth.AUTH+'/jwks'
        def get_signing_key_from_jwt(self,token):
            return SimpleNamespace(key='public-key')
    def verify(*args,**kwargs):
        assert kwargs['audience']=='issued-client'
        assert kwargs['issuer']==siwc_auth.AUTH
        return {'sub':'account','nonce':memory['nonce']}
    def browser(url):
        from urllib.parse import parse_qs,urlsplit
        query=parse_qs(urlsplit(url).query)
        memory['nonce']=query['nonce'][0]
        assert query['code_challenge_method']==['S256']
        assert query['client_id']==['dynamic_agent_client']
    with patch.object(siwc_auth,'vault_get',return_value=None), \
         patch.object(siwc_auth,'vault_put',side_effect=lambda k,v:memory.__setitem__(k,v)), \
         patch.object(siwc_auth,'callback_listener',return_value=(54321,callback,MagicMock(),worker)), \
         patch.object(siwc_auth.webbrowser,'open',side_effect=browser), \
         patch.object(siwc_auth,'request_json',side_effect=endpoint), \
         patch.object(siwc_auth.jwt,'PyJWKClient',FakeJWK), \
         patch.object(siwc_auth.jwt,'decode',side_effect=verify):
        assert siwc_auth.sign_in()=={'connected':True}
    assert memory['account']['subject']=='account'
    assert memory['account']['refresh_token']=='refresh'


def test_sign_in_rejects_wrong_nonce_without_saving():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    worker=MagicMock()
    worker.is_alive.return_value=False
    callback={'code':'code','client_id':'issued-client'}
    tokens={'access_token':'access','refresh_token':'refresh','id_token':'id',
            'scope':'openid chatgpt.tokens.use.direct'}
    saved=[]
    class FakeJWK:
        def __init__(self,uri): pass
        def get_signing_key_from_jwt(self,token): return SimpleNamespace(key='public')
    with patch.object(siwc_auth,'vault_get',return_value=None), \
         patch.object(siwc_auth,'vault_put',side_effect=lambda k,v:saved.append(k)), \
         patch.object(siwc_auth,'callback_listener',return_value=(54321,callback,MagicMock(),worker)), \
         patch.object(siwc_auth.webbrowser,'open',return_value=True), \
         patch.object(siwc_auth,'request_json',side_effect=lambda url,**kw: tokens if url.endswith('/oauth/token') else {'jwks_uri':siwc_auth.AUTH+'/jwks'}), \
         patch.object(siwc_auth.jwt,'PyJWKClient',FakeJWK), \
         patch.object(siwc_auth.jwt,'decode',return_value={'sub':'account','nonce':'incorrect'}):
        import pytest
        with pytest.raises(RuntimeError,match='nonce mismatch'):
            siwc_auth.sign_in()
    assert 'account' not in saved


def test_model_list_accepts_chatgpt_models_envelope():
    models={'models':[{'slug':'gpt-test','display_name':'GPT Test','visibility':'list'},
                      {'slug':'hidden','visibility':'hidden'}]}
    with patch.object(siwc_auth,'access_token',return_value='test-token'), \
         patch.object(siwc_auth,'request_json',return_value=models):
        assert siwc_auth.list_models()==[{'id':'gpt-test','name':'GPT Test'}]


def test_model_list_accepts_legacy_data_envelope():
    models={'data':[{'slug':'gpt-test','visibility':'list'}]}
    with patch.object(siwc_auth,'access_token',return_value='test-token'), \
         patch.object(siwc_auth,'request_json',return_value=models):
        assert siwc_auth.list_models()==[{'id':'gpt-test','name':'gpt-test'}]
