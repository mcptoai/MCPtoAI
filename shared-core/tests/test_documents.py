import base64
import io
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest
from mcptoai_core import documents as d


def envelope(data=b'hello', name='notes.txt', media_type='text/plain'):
    return {'version': 1, 'files': [{'name': name, 'size': len(data), 'media_type': media_type,
                                   'data_base64': base64.b64encode(data).decode()}]}


def test_version_and_limits():
    caps = d.capabilities()
    assert caps['version'] == 1 and caps['max_file_bytes'] == 10 * 1024**2
    assert caps['max_turn_bytes'] == 20 * 1024**2
    assert set(caps['conversion_required']) == {'doc', 'xls', 'ppt'}
    assert d.decode_attachments(None) == []


@pytest.mark.parametrize('ext', sorted(d.TEXT_EXTENSIONS))
def test_source_and_structured_text_are_inert(ext, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('Uploaded code executed')
    monkeypatch.setattr(os, 'system', forbidden)
    text = '#!/bin/sh\necho not-executed\n<xml>&not-expanded;</xml>'
    out = d.process_documents(envelope(text.encode(), 'sample.' + ext))
    assert text in out.text
    assert set(out.metadata[0]) == {'name', 'size', 'type'}
    assert text not in json.dumps(out.metadata)


@pytest.mark.parametrize('name', ['../secret.txt', '/tmp/secret.txt', 'C:\\secret.txt', 'a\n.txt', 'x\u202etxt', '..', 'a/b.txt'])
def test_reject_paths_and_control_names(name):
    with pytest.raises(d.DocumentError, match='name'):
        d.process_documents(envelope(name=name))


@pytest.mark.parametrize('magic', d.EXECUTABLE_MAGIC)
def test_reject_executables_even_disguised_as_text(magic):
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope(magic + b'payload'))
    assert err.value.code == 'executable_rejected'


@pytest.mark.parametrize('ext', ['doc', 'xls', 'ppt'])
def test_legacy_has_explicit_conversion_error(ext):
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope(b'\xd0\xcf\x11\xe0', 'old.' + ext))
    assert err.value.code == 'conversion_required'
    assert 'conversion' in str(err.value)


@pytest.mark.parametrize('change,code', [
    ({'size': d.MAX_FILE_BYTES + 1}, 'attachment_size'),
    ({'size': True}, 'attachment_size'),
    ({'size': 1}, 'attachment_size'),
    ({'data_base64': '!!!!'}, 'invalid_attachment'),
    ({'name': 'bad.exe'}, 'unsupported_type'),
])
def test_bad_envelope(change, code):
    e = envelope(); e['files'][0].update(change)
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(e)
    assert err.value.code == code


@pytest.mark.parametrize('e', [{}, {'version': True}, {'version': 2}, [], {'version': 1, 'files': []}])
def test_invalid_versions_and_shapes(e):
    with pytest.raises(d.DocumentError):
        d.process_documents(e)


def test_quotas_before_decode_or_temp(monkeypatch):
    e = envelope()
    e['files'] *= 9
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(e)
    assert err.value.code == 'attachment_quota'
    e['files'] = [{'size': d.MAX_FILE_BYTES, 'data_base64': ''}] * 3
    monkeypatch.setattr(base64, 'b64decode', lambda *a, **kw: pytest.fail('decoded over quota'))
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(e)
    assert err.value.code == 'attachment_quota'


def test_file_boundary_and_aggregate_context():
    e = envelope(b'a' * d.MAX_FILE_BYTES)
    result = d.process_documents(e, context_window=9000, used_context_tokens=100, reserve_tokens=8192)
    assert d.NOTICE in result.notices and d.NOTICE not in result.text
    assert len(result.text.encode()) <= 808 + len(d.NOTICE) + 2
    assert len(d.decode_attachments(e)[0].data) == d.MAX_FILE_BYTES
    e['files'] *= 2
    result = d.process_documents(e, context_window=9000, used_context_tokens=100, reserve_tokens=8192)
    assert len(result.text.encode()) <= 808 + len(d.NOTICE) + 2


def test_utf16_and_multibyte_budget():
    out = d.process_documents(envelope('Hello 🌍'.encode('utf-16')))
    assert 'Hello 🌍' in out.text
    out = d.process_documents(envelope(('🌍' * 200).encode()), context_window=100, reserve_tokens=0)
    assert d.NOTICE in out.notices
    assert '\ufffd' not in out.text


def test_private_paths_cleanup_success_and_failure(tmp_path, monkeypatch):
    tmp_path = tmp_path / 'document-temp'
    tmp_path.mkdir()
    monkeypatch.setattr(d.tempfile, 'tempdir', str(tmp_path))
    original = d._extract
    def inspect(path, ext):
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.name == '0.txt'
        yield from original(path, ext)
    monkeypatch.setattr(d, '_extract', inspect)
    d.process_documents(envelope())
    assert not list(tmp_path.iterdir())
    def broken(path, ext):
        raise RuntimeError('CANARY_PRIVATE_CONTENT')
        yield
    monkeypatch.setattr(d, '_extract', broken)
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope())
    assert 'CANARY' not in str(err.value)
    assert not list(tmp_path.iterdir())


def image_bytes(fmt):
    from PIL import Image
    if fmt == 'HEIF':
        from pillow_heif import register_heif_opener
        register_heif_opener()
    out = io.BytesIO(); Image.new('RGB', (10, 10), 'red').save(out, format=fmt)
    return out.getvalue()


@pytest.mark.parametrize('ext,fmt', [('png','PNG'),('jpg','JPEG'),('webp','WEBP'),('gif','GIF'),('heic','HEIF')])
def test_images_are_decoded_and_normalized(ext, fmt):
    out = d.process_documents(envelope(image_bytes(fmt), 'image.' + ext, d.IMAGE_TYPES[ext]), provider='anthropic', model='claude-sonnet-5')
    assert out.images[0]['data_url'].startswith('data:image/jpeg;base64,')
    assert not out.files
    if ext == 'gif': assert 'first frame' in out.notices[0]


@pytest.mark.parametrize('data,name,mime', [(b'not an image','fake.png','image/png'), (b'hello','fake.pdf','application/pdf'), (b'a\x00b','bad.txt','text/plain'), (b'PK\x03\x04foo','bad.docx',d.OFFICE_TYPES['docx'])])
def test_magic_mismatches(data, name, mime):
    with pytest.raises(d.DocumentError):
        d.process_documents(envelope(data, name, mime))


def test_image_requires_supported_model():
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope(image_bytes('PNG'), 'x.png', 'image/png'))
    assert err.value.code == 'image_unsupported'


def pdf_bytes():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
    w = PdfWriter(); page = w.add_blank_page(width=100, height=100)
    stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 10 10 Td (Hello PDF) Tj ET')
    page[NameObject('/Contents')] = w._add_object(stream)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
    out = io.BytesIO(); w.write(out); return out.getvalue()


@pytest.mark.parametrize('provider,model', [('anthropic','claude-sonnet-5'),('openai','gpt-5')])
def test_native_pdf_and_provider_blocks(provider, model):
    out = d.process_documents(envelope(pdf_bytes(), 'report.pdf', 'application/pdf'), provider=provider, model=model)
    assert len(out.files) == 1 and out.text == ''
    block = d.provider_file_blocks(out.files, provider)[0]
    assert block['type'] == ('document' if provider == 'anthropic' else 'file')
    assert 'data_base64' not in json.dumps(out.metadata)


def test_pdf_fallback_for_unknown_and_custom_provider():
    for kwargs in ({}, {'provider':'openai','model':'gpt-5','base_url':'https://custom.invalid/v1'}):
        out = d.process_documents(envelope(pdf_bytes(), 'report.pdf', 'application/pdf'), **kwargs)
        assert 'Hello PDF' in out.text and not out.files


@pytest.mark.parametrize('ext', ['docx','xlsx','pptx','odt','ods','odp'])
def test_office_real_parser_fixtures(ext):
    out = io.BytesIO()
    if ext == 'docx':
        from docx import Document
        doc = Document(); doc.add_paragraph('Hello Office'); doc.add_table(rows=1, cols=1).cell(0,0).text = 'Table text'; doc.save(out)
    elif ext == 'xlsx':
        from openpyxl import Workbook
        doc = Workbook(); doc.active['A1'] = 'Hello Office'; doc.active['A2'] = '=1+1'; doc.save(out)
    elif ext == 'pptx':
        from pptx import Presentation
        doc = Presentation(); slide = doc.slides.add_slide(doc.slide_layouts[1]); slide.shapes.title.text = 'Hello Office'; doc.save(out)
    else:
        from odf.opendocument import OpenDocumentText, OpenDocumentSpreadsheet, OpenDocumentPresentation
        from odf.text import P
        doc = {'odt':OpenDocumentText,'ods':OpenDocumentSpreadsheet,'odp':OpenDocumentPresentation}[ext]()
        body = getattr(doc, {'odt':'text','ods':'spreadsheet','odp':'presentation'}[ext])
        body.addElement(P(text='Hello Office'), check_grammar=False); doc.save(out)
    result = d.process_documents(envelope(out.getvalue(), 'test.' + ext, d.OFFICE_TYPES[ext]))
    assert 'Hello Office' in result.text
    if ext == 'xlsx': assert '=1+1' not in result.text


def test_rtf():
    out = d.process_documents(envelope(b'{\\rtf1\\ansi Hello \\b World\\b0}', 'x.rtf', 'application/rtf'))
    assert 'Hello World' in out.text
    with pytest.raises(d.DocumentError):
        d.process_documents(envelope(b'{\\rtf1{\\object data}}', 'x.rtf', 'application/rtf'))


@pytest.mark.parametrize('name,data', [('word/document.xml',b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x/>'), ('word/vbaProject.bin',b'program'), ('../escape',b'x'), ('word/document.xml', b'x' * (11*1024*1024))])
def test_malicious_archives(name,data):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(name,data); z.writestr('[Content_Types].xml', '<x/>')
    with pytest.raises(d.DocumentError):
        d.process_documents(envelope(out.getvalue(),'bad.docx',d.OFFICE_TYPES['docx']))


def test_no_network_or_converter_code():
    import ast
    tree = ast.parse(Path(d.__file__).read_text())
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imports |= {alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names}
    assert not imports & {'requests','httpx','urllib.request','subprocess'}


def test_dependency_pins_match_every_distribution():
    import tomllib
    root = Path(__file__).resolve().parents[2]
    pins = {line.lower() for line in (root/'shared-core/requirements-documents.in').read_text().splitlines() if line and not line.startswith('#')}
    for folder in ('shared-core','device-agent','linux-agent'):
        project = tomllib.loads((root/folder/'pyproject.toml').read_text())['project']
        assert pins <= {line.lower() for line in project['dependencies']}
    lock = (root/'device-agent/requirements-build.lock').read_text().lower()
    assert all(pin in lock for pin in pins)


def test_legacy_images_share_quota_and_validation():
    data = image_bytes('PNG')
    image = {'data_url':'data:image/png;base64,' + base64.b64encode(data).decode()}
    result = d.process_documents(None, legacy_images=[image])
    assert result.images[0]['data_url'].startswith('data:image/jpeg;base64,')
    with pytest.raises(d.DocumentError):
        d.process_documents(None, legacy_images=[{'data_url':'data:image/png;base64,YWJj'}])
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope(), legacy_images=[image] * 8)
    assert err.value.code == 'attachment_quota'
    e = envelope(b'x' * d.MAX_FILE_BYTES); e['files'] *= 2
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(e, legacy_images=[image])
    assert err.value.code == 'attachment_quota'


def test_budget_exhaustion_is_visible_without_parsing(monkeypatch):
    monkeypatch.setattr(d, '_extract', lambda *args: pytest.fail('No context remaining'))
    result = d.process_documents(envelope(), used_context_tokens=32768)
    assert result.notices == [d.NOTICE]


def test_xlsx_wide_sheet_fails_explicitly():
    from openpyxl import Workbook
    book = Workbook(); book.active.cell(1,257,'Would otherwise silently disappear')
    data = io.BytesIO(); book.save(data)
    with pytest.raises(d.DocumentError) as err:
        d.process_documents(envelope(data.getvalue(),'wide.xlsx',d.OFFICE_TYPES['xlsx']))
    assert err.value.code == 'document_limit'


def test_small_csv_61_rows_no_truncation_with_real_provider_context():
    raw = ('item,value\n' + ''.join(f'{i},{i*2}\n' for i in range(61))).encode()
    result = d.process_documents(envelope(raw, name='table.csv'), provider='openai', model='gpt-5', used_context_tokens=2000)
    assert len(result.text.splitlines()) >= 62
    assert d.NOTICE not in result.notices
    assert d.trusted_context_window('openai', 'gpt-5') >= 128_000


def test_document_notice_never_enters_model_context():
    result = d.process_documents(envelope(b'x' * 5000), context_window=150, reserve_tokens=0)
    assert d.NOTICE in result.notices
    assert d.NOTICE not in result.text
    assert result.truncation and result.truncation[0]['included_bytes'] >= 0


def test_document_progress_metadata_only():
    events = []
    result = d.process_documents(envelope(b'hello'), progress=events.append)
    assert result.text.endswith('hello\n')
    assert events[0]['stage'] == 'received'
    assert events[-1]['stage'] == 'ready'
    assert 'hello' not in str(events)
