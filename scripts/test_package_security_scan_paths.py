import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('package_security_scan', Path(__file__).with_name('package-security-scan.py'))
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)


def test_windows_paths_with_single_or_doubled_separators(tmp_path):
    for path in [r'C:\Users\Alice\Documents\Projects\MCPtoAI\device-agent',
                 r'C:\\Users\\Alice\\Documents\\Projects\\MCPtoAI\\device-agent']:
        artifact = tmp_path / 'binary.exe'
        artifact.write_bytes(('prefix ' + path + ' suffix').encode())
        failures, warnings = [], []
        scan.scan_bytes('agent', artifact, failures, warnings)
        assert any('developer Windows project path' in w for w in warnings)


def test_unrelated_windows_path_not_flagged(tmp_path):
    artifact = tmp_path / 'binary.exe'
    artifact.write_bytes(rb'C:\Users\Alice\Desktop\Unrelated')
    failures, warnings = [], []
    scan.scan_bytes('agent', artifact, failures, warnings)
    assert not warnings
