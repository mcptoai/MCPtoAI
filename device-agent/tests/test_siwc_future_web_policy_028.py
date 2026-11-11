from unittest.mock import patch
import pytest
from mcptoai_agent import siwc_policy

def test_web_denied_by_default():
    with patch.object(siwc_policy,'local_permission',return_value=False):
        with pytest.raises(PermissionError):
            siwc_policy.authorize_web_turn(None,interactive=True,fresh_message_id=True)

def test_missing_identity_denied_even_when_switches_on():
    with patch.object(siwc_policy,'local_permission',return_value=True),patch.object(siwc_policy,'remote_web_enabled',return_value=True):
        with pytest.raises(PermissionError):
            siwc_policy.authorize_web_turn(None,interactive=True,fresh_message_id=True)
