from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_policy as p

IDENTITY={'source':'authenticated_relay','user_id':'42','device_id':'device-1','subjects':['auth0|owner']}

def authorized(identity=IDENTITY, **kwargs):
    return p.authorize_web_turn(identity,interactive=True,fresh_message_id=True,**kwargs)

def test_local_permission_off_denies_before_remote_call():
    with patch.object(p,'local_permission',side_effect=lambda k:k=='siwc_enabled'),patch.object(p,'remote_web_enabled') as remote:
        with pytest.raises(PermissionError):authorized()
        remote.assert_not_called()

def test_remote_off_or_unreadable_denies():
    with patch.object(p,'local_permission',return_value=True),patch.object(p,'remote_web_enabled',return_value=False):
        with pytest.raises(PermissionError):authorized()
    with patch.object(p.httpx,'get',side_effect=p.httpx.ConnectError('offline')):
        assert not p.remote_web_enabled()

def test_owner_device_and_linked_account_checks_before_model_call():
    with patch.object(p,'local_permission',return_value=True),patch.object(p,'remote_web_enabled',return_value=True),patch('mcptoai_agent.auth._auth_bundle',return_value={'device_id':'device-1'}),patch('mcptoai_agent.siwc_auth.paired_owner',return_value='auth0|owner'),patch('mcptoai_agent.siwc_auth.assert_owner',return_value='auth0|owner'):
        authorized()
        for invalid in (dict(IDENTITY,subjects=['auth0|attacker']),dict(IDENTITY,device_id='wrong'),dict(IDENTITY,source='client'),dict(IDENTITY,subjects=[]),dict(IDENTITY,subjects=['auth0|owner','auth0|attacker']),dict(IDENTITY,subjects=['auth0|owner','auth0|owner']),None):
            with pytest.raises(PermissionError):authorized(invalid)
        for flags in ({'replay':True},{'job_or_sampling':True},{'interactive':False}):
            with pytest.raises((PermissionError,TypeError)):
                p.authorize_web_turn(IDENTITY,interactive=flags.get('interactive',True),fresh_message_id=True,replay=flags.get('replay',False),job_or_sampling=flags.get('job_or_sampling',False))


def test_exactly_one_identity_matches_both_owners():
    with patch.object(p,'local_permission',return_value=True),patch.object(p,'remote_web_enabled',return_value=True),patch('mcptoai_agent.auth._auth_bundle',return_value={'device_id':'device-1'}),patch('mcptoai_agent.siwc_auth.paired_owner',return_value='auth0|owner'),patch('mcptoai_agent.siwc_auth.assert_owner',return_value='auth0|owner'):
        authorized(IDENTITY)
        for subjects in ([],['auth0|owner','auth0|other'],['auth0|owner','auth0|owner'],['auth0|other']):
            with pytest.raises(PermissionError):
                authorized(dict(IDENTITY,subjects=subjects))
    with patch.object(p,'local_permission',return_value=True),patch.object(p,'remote_web_enabled',return_value=True),patch('mcptoai_agent.auth._auth_bundle',return_value={'device_id':'device-1'}),patch('mcptoai_agent.siwc_auth.paired_owner',return_value='auth0|owner'),patch('mcptoai_agent.siwc_auth.assert_owner',return_value='auth0|other'):
        with pytest.raises(PermissionError):authorized(IDENTITY)
