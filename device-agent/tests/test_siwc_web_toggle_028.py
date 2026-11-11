"""Web permission is separate from Desktop Preview and defaults off."""
from unittest.mock import patch
from mcptoai_agent import config

def test_web_permission_defaults_off_and_is_independent():
    with patch.object(config,'config_dir') as path:
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as temp:
            path.return_value=Path(temp)
            assert not config.local_permission('siwc_enabled')
            assert not config.local_permission('siwc_web_enabled')
            config.save_local_permission('siwc_enabled',True)
            assert not config.local_permission('siwc_web_enabled')
            config.save_local_permission('siwc_web_enabled',True)
            assert config.local_permission('siwc_web_enabled')
