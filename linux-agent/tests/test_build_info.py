from mcptoai_linux import build_info


def test_packaged_build_info(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, '__file__', str(tmp_path/'build_info.py'))
    (tmp_path/'build-info.json').write_text('{"commit":"abc123","dirty":false}')
    assert build_info.version_string('0.2.7') == 'mcptoai 0.2.7 (commit=abc123, dirty=false)'


def test_unknown_build_info(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info, '__file__', str(tmp_path/'build_info.py'))
    assert build_info.build_info() == {'commit':'unknown','dirty':None}
