"""Versioned, device-local attachment boundary. Uploaded bytes are never executed.

Only this module accepts the untrusted relay envelope. Parsers receive a generated
private path, never a caller path/URL. No archive is extracted to disk, no converter
or shell is invoked, and errors never contain parser output or document contents.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import time
import os
from pathlib import Path
import re
import tempfile
import warnings
import zipfile
from dataclasses import dataclass, field

CAPABILITY = "document_processing_v1"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TURN_BYTES = 20 * 1024 * 1024
MAX_FILES = 8
MAX_RELAY_BYTES = 29 * 1024 * 1024  # base64 quota + bounded chat envelope
MAX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_TEXT_CHARS = 120_000
NOTICE = "[Attachment text truncated to fit the available context.]"
LOG = logging.getLogger("mcptoai.documents")
PDF_MAX_SECONDS = 90
PDF_MAX_PAGES = 500
# Trusted provider/model family defaults; unknown/local models remain conservative.
def trusted_context_window(provider, model):
    p, m = str(provider).lower(), str(model).lower()
    if p in ("anthropic", "claude") or m.startswith("claude-"):
        return 200_000
    if p in ("openai", "chatgpt") or m.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "gpt-6", "o3", "o4")):
        return 128_000
    if p in ("google", "gemini") or m.startswith("gemini-"):
        return 128_000
    return 32_768

TEXT_EXTENSIONS = frozenset("txt md markdown csv tsv json xml html htm yaml yml log m mm py pyw js jsx ts tsx mjs cjs c h cc cpp cxx hpp cs java kt kts swift go rs rb php sh bash zsh fish ps1 sql r scala lua pl pm rkt clj ex exs erl hs dart vue svelte css scss sass less toml ini cfg conf env dockerfile makefile cmake tex rst ipynb graphql proto diff patch bat cmd psm1 psd1 asm s gradle properties gitignore svg".split())
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "heic": "image/heic", "heif": "image/heif"}
OFFICE_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\x00asm")


class DocumentError(ValueError):
    """Public, content-free error safe to show in chat."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code, message):
    raise DocumentError(code, message) from None


def capabilities() -> dict:
    return {"version": 1, "capability": CAPABILITY, "max_file_bytes": MAX_FILE_BYTES,
            "max_turn_bytes": MAX_TURN_BYTES, "max_files": MAX_FILES,
            "extensions": sorted(TEXT_EXTENSIONS | IMAGE_TYPES.keys() | OFFICE_TYPES.keys() | {"pdf", "rtf"}),
            "conversion_required": ["doc", "xls", "ppt"]}


@dataclass(frozen=True)
class Attachment:
    name: str
    media_type: str
    extension: str
    data: bytes = field(repr=False)

    def metadata(self):
        return {"name": self.name, "size": len(self.data), "type": self.media_type}


@dataclass
class ProcessedDocuments:
    text: str = ""
    images: list[dict] = field(default_factory=list, repr=False)
    files: list[dict] = field(default_factory=list, repr=False)
    metadata: list[dict] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    truncation: list[dict] = field(default_factory=list)


def _name(value):
    if not isinstance(value, str) or not value or len(value) > 255:
        _fail("invalid_attachment", "Attachment name is invalid.")
    # Reject paths rather than attempting platform-specific path normalization.
    if value in {".", ".."} or any(c in value for c in '/\\:') or any(ord(c) < 32 or ord(c) == 127 or c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in value):
        _fail("invalid_attachment", "Attachment name must be a plain file name.")
    return value


def _decode_text(data):
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeError:
        _fail("invalid_type", "Text attachments must use UTF-8 or BOM-marked UTF-16.")
    if any(ord(c) < 32 and c not in '\t\n\r\f' for c in text):
        _fail("invalid_type", "Binary data cannot be attached as text.")
    return text


def _check_archive(data, ext):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 2048 or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                _fail("archive_limit", "Document archive exceeds extraction limits.")
            names = set()
            for item in infos:
                if (item.filename in names or item.flag_bits & 1 or item.compress_type not in (0, 8)
                        or item.file_size > 10 * 1024 * 1024
                        or item.file_size > max(1024 * 1024, item.compress_size * 200)
                        or item.filename.startswith('/') or '\\' in item.filename or '..' in item.filename.split('/')
                        or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    _fail("unsafe_archive", "Document archive contains unsafe entries.")
                names.add(item.filename)
                content = archive.read(item)
                if content.startswith(EXECUTABLE_MAGIC) or item.filename.lower().endswith(('.exe', '.dll', '.class', '.wasm', '.com', '.scr', '.vbs')):
                    _fail('unsafe_archive', 'Document contains an embedded program.')
                # Parse-only policy: reject macros, embedded objects and external entities.
                if any(part in item.filename.lower() for part in ('vbaproject', '/embeddings/', '/scripts/')):
                    _fail("unsafe_archive", "Documents containing embedded programs are not supported.")
                if item.filename.endswith(('.xml', '.rels')):
                    xml = archive.read(item)
                    probe = xml.replace(b'\x00', b'').upper()
                    if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
                        _fail("unsafe_archive", "Document XML declarations are not supported.")
            expected = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
            if ext in expected:
                if expected[ext] not in names or '[Content_Types].xml' not in names:
                    _fail("invalid_type", "Office document signature does not match its extension.")
            elif archive.read('mimetype').decode('ascii') != OFFICE_TYPES[ext] or 'content.xml' not in names:
                _fail("invalid_type", "OpenDocument signature does not match its extension.")
    except DocumentError:
        raise
    except Exception:
        _fail("invalid_type", "Document archive is invalid.")


def _validate(data, ext):
    if data.startswith(EXECUTABLE_MAGIC):
        _fail("executable_rejected", "Executable files cannot be attached.")
    if ext in {"doc", "xls", "ppt"}:
        _fail("conversion_required", "Legacy doc/xls/ppt files require conversion to docx/xlsx/pptx or PDF before attaching.")
    if ext in IMAGE_TYPES:
        match = {"png": data.startswith(b'\x89PNG\r\n\x1a\n'),
                 "jpg": data.startswith(b'\xff\xd8\xff'), "jpeg": data.startswith(b'\xff\xd8\xff'),
                 "gif": data.startswith((b'GIF87a', b'GIF89a')),
                 "webp": data[:4] == b'RIFF' and data[8:12] == b'WEBP',
                 "heic": data[4:8] == b'ftyp' and any(b in data[8:40] for b in (b'heic', b'heix', b'hevc', b'hevx')),
                 "heif": data[4:8] == b'ftyp' and any(b in data[8:40] for b in (b'heic', b'heix', b'mif1'))}[ext]
        if not match:
            _fail("invalid_type", "Image signature does not match its extension.")
        return IMAGE_TYPES[ext]
    if ext == 'pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
            _fail("invalid_type", "PDF signature is invalid.")
        return 'application/pdf'
    if ext in OFFICE_TYPES:
        if not data.startswith(b'PK\x03\x04'):
            _fail("invalid_type", "Office document signature is invalid.")
        _check_archive(data, ext)
        return OFFICE_TYPES[ext]
    if ext == 'rtf':
        if not data.startswith(b'{\\rtf'):
            _fail("invalid_type", "RTF signature is invalid.")
        if re.search(rb'\\(?:object|objdata|bin)\b', data, re.I):
            _fail("invalid_type", "RTF embedded objects are not supported.")
        return 'application/rtf'
    if ext in TEXT_EXTENSIONS:
        _decode_text(data)
        return 'text/plain'
    _fail("unsupported_type", "This attachment type is not supported.")


def decode_attachments(envelope) -> list[Attachment]:
    """Validate the complete turn before creating any temporary files.

    The wire shape is {version: 1, files: [{name, size, media_type, data_base64}]}.
    MIME claims are checked for binary formats; text formats normalize to text/plain.
    """
    if envelope is None:
        return []
    if not isinstance(envelope, dict) or type(envelope.get('version')) is not int or envelope['version'] != 1:
        _fail("unsupported_version", "Unsupported attachment envelope version.")
    files = envelope.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        _fail("attachment_quota", "Attach between one and eight files per turn.")
    total = 0
    for item in files:
        if not isinstance(item, dict) or type(item.get('size')) is not int or not 0 <= item['size'] <= MAX_FILE_BYTES:
            _fail("attachment_size", "Each attachment must be at most 10 MiB.")
        total += item['size']
        encoded = item.get('data_base64')
        if not isinstance(encoded, str) or len(encoded) > ((item['size'] + 2) // 3) * 4:
            _fail("attachment_size", "Attachment encoded size is invalid.")
    if total > MAX_TURN_BYTES:
        _fail("attachment_quota", "Attachments must total at most 20 MiB per turn.")
    result = []
    for item in files:
        name = _name(item.get('name'))
        ext = name.rsplit('.', 1)[-1].lower()
        try:
            data = base64.b64decode(item['data_base64'], validate=True)
        except (ValueError, binascii.Error):
            _fail("invalid_attachment", "Attachment base64 encoding is invalid.")
        if len(data) != item['size']:
            _fail("attachment_size", "Attachment size does not match its payload.")
        media = _validate(data, ext)
        claim = item.get('media_type')
        if not isinstance(claim, str) or len(claim) > 128 or (media != 'text/plain' and claim not in (media, 'application/octet-stream')):
            _fail("invalid_type", "Attachment media type does not match its contents.")
        result.append(Attachment(name, media, ext, data))
    return result


def native_support(provider: str, model: str, base_url: str = '') -> bool:
    """Conservative model gate; custom OpenAI-compatible endpoints use extraction."""
    if base_url and base_url.rstrip('/') != 'https://api.openai.com/v1':
        return False
    if provider == 'anthropic':
        return bool(re.search(r'claude[-_](?:[3-9]|(?:sonnet|opus|haiku)[-_][3-9])', model.lower()))
    return provider == 'openai' and bool(re.match(r'(?:gpt-4o(?:-|$)|gpt-4\.[1-9]|gpt-[5-9]|o[3-9](?:-|$))', model.lower()))


def _image(data, ext):
    from PIL import Image, ImageOps
    if ext in {'heic', 'heif'}:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 20_000_000 or im.width <= 0 or im.height <= 0:
                _fail('image_limit', 'Image exceeds the 20 megapixel limit.')
            im.seek(0)
            im.load()
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((2048, 2048))
            output = io.BytesIO()
            im.save(output, format='JPEG', quality=85)
    return {'data_url': 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')}


def _extract(path, ext, *, progress=None, cancelled=None):
    """Yield bounded text pieces. Libraries never evaluate formulas/macros or URLs."""
    if ext in TEXT_EXTENSIONS:
        yield _decode_text(path.read_bytes())
    elif ext == 'rtf':
        from striprtf.striprtf import rtf_to_text
        yield rtf_to_text(path.read_bytes().decode('latin-1'), errors='replace')
    elif ext == 'pdf':
        from pypdf import PdfReader, apply_configuration
        # Context-local limits apply before decompression, not merely after a
        # potentially oversized stream has already been allocated.
        with apply_configuration(
            maximum_declared_stream_length=5 * 1024 * 1024,
            array_based_stream_maximum_output_length=5 * 1024 * 1024,
            zlib_maximum_output_length=5 * 1024 * 1024,
            lzw_maximum_output_length=5 * 1024 * 1024,
            run_length_maximum_output_length=5 * 1024 * 1024,
            stream_decoding_work_maximum_length=MAX_EXPANDED_BYTES,
        ):
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                _fail('encrypted_document', 'Encrypted PDFs must be decrypted before attaching.')
            if len(reader.pages) > PDF_MAX_PAGES:
                _fail('document_limit', 'PDF exceeds the 500 page extraction limit.')
            expanded = 0
            started = time.monotonic()
            total = len(reader.pages)
            for index, page in enumerate(reader.pages):
                if cancelled and cancelled():
                    _fail('document_cancelled', 'Document processing was stopped.')
                if time.monotonic() - started > PDF_MAX_SECONDS:
                    _fail('document_timeout', 'PDF text extraction exceeded 90 seconds. Try a smaller document.')
                if progress and (index == 0 or index % 10 == 0):
                    progress({'stage': 'processing', 'pages_done': index, 'pages_total': total})
                contents = page.get_contents()
                if contents is not None:
                    expanded += len(contents.get_data())
                    if expanded > MAX_EXPANDED_BYTES:
                        _fail('document_limit', 'PDF exceeds extraction limits.')
                yield page.extract_text() or ''
            if progress: progress({'stage': 'processing', 'pages_done': total, 'pages_total': total})
    elif ext == 'docx':
        from docx import Document
        doc = Document(path)
        for p in doc.paragraphs:
            yield p.text
        for table in doc.tables:
            for row in table.rows:
                yield '\t'.join(c.text for c in row.cells)
    elif ext == 'xlsx':
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        try:
            for sheet in book:
                yield '[' + sheet.title + ']'
                # Ignore malicious dimension claims; bound actual iteration too.
                if sheet.max_column and sheet.max_column > 256:
                    _fail('document_limit', 'Spreadsheet exceeds the 256 column extraction limit.')
                sheet.reset_dimensions()
                for index, row in enumerate(sheet.iter_rows(max_col=256, values_only=True)):
                    if index >= 100_000:
                        _fail('document_limit', 'Spreadsheet exceeds extraction limits.')
                    yield '\t'.join('' if v is None else str(v) for v in row)
        finally:
            book.close()
    elif ext == 'pptx':
        from pptx import Presentation
        for slide in Presentation(path).slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    yield shape.text
                if shape.has_table:
                    for row in shape.table.rows:
                        yield '\t'.join(c.text for c in row.cells)
    else:
        from odf.opendocument import load
        from odf import teletype
        from odf.text import P, H
        doc = load(str(path))
        for element in doc.getElementsByType(P) + doc.getElementsByType(H):
            yield teletype.extractText(element)


def process_documents(envelope, *, provider='', model='', base_url='', context_window=32768,
                      used_context_tokens=0, reserve_tokens=8192, legacy_images=None, progress=None, cancelled=None) -> ProcessedDocuments:
    """Atomic processing with aggregate context budget and automatic private cleanup.

    Token accounting uses UTF-8 bytes as a conservative upper bound. Callers may
    supply a trusted smaller model window, never a value from the upload envelope.
    Native images/PDFs have provider-specific token costs and provider-side limits.
    """
    started = time.monotonic()
    attachments = decode_attachments(envelope)
    if progress: progress({'stage': 'received', 'files': len(attachments), 'bytes': sum(len(a.data) for a in attachments)})
    LOG.info('attachments_received files=%d bytes=%d', len(attachments), sum(len(a.data) for a in attachments))
    legacy = []
    if legacy_images:
        if not isinstance(legacy_images, list) or len(legacy_images) > MAX_FILES:
            _fail('attachment_quota', 'Attach at most eight files per turn.')
        for index, image in enumerate(legacy_images):
            url = image.get('data_url') if isinstance(image, dict) else None
            if not isinstance(url, str) or len(url) > ((MAX_FILE_BYTES + 2) // 3) * 4 + 64:
                _fail('attachment_size', 'Image exceeds attachment limits.')
            match = re.fullmatch(r'data:(image/(png|jpeg|gif|webp|heic|heif));base64,([A-Za-z0-9+/]*={0,2})', url)
            if not match:
                _fail('invalid_type', 'Image data URL is invalid.')
            try:
                data = base64.b64decode(match[3], validate=True)
            except ValueError:
                _fail('invalid_attachment', 'Image encoding is invalid.')
            if len(data) > MAX_FILE_BYTES:
                _fail('attachment_size', 'Image exceeds attachment limits.')
            media = _validate(data, match[2])
            legacy.append(Attachment(f'image-{index + 1}.{match[2]}', media, match[2], data))
    attachments = legacy + attachments
    if len(attachments) > MAX_FILES or sum(len(a.data) for a in attachments) > MAX_TURN_BYTES:
        _fail('attachment_quota', 'Attachments and images together exceed the per-turn quota.')
    result = ProcessedDocuments(metadata=[a.metadata() for a in attachments])
    if context_window == 32768:
        context_window = trusted_context_window(provider, model)
    budget = max(0, min(MAX_TEXT_CHARS, context_window - used_context_tokens - reserve_tokens))
    LOG.info('attachment_budget provider=%s context=%d used_bytes=%d budget_bytes=%d', provider, context_window, used_context_tokens, budget)
    native = native_support(provider, model, base_url)
    with tempfile.TemporaryDirectory(prefix='mcptoai-documents-') as folder:
        os.chmod(folder, 0o700)
        for index, attachment in enumerate(attachments):
            if cancelled and cancelled(): _fail('document_cancelled', 'Document processing was stopped.')
            file_started = time.monotonic()
            ext = attachment.extension
            mode = 'native' if ext == 'pdf' and native else 'extract' if ext not in IMAGE_TYPES else 'image'
            LOG.info('attachment_start index=%d type=%s bytes=%d mode=%s', index, ext, len(attachment.data), mode)
            if progress: progress({'stage': 'processing', 'mode': mode, 'file_index': index + 1, 'file_total': len(attachments)})
            try:
                if ext in IMAGE_TYPES:
                    if not native and index >= len(legacy):
                        _fail('image_unsupported', 'This model cannot accept images. Select a vision-capable Anthropic or OpenAI model.')
                    result.images.append(_image(attachment.data, ext))
                    if ext == 'gif':
                        result.notices.append('Animated images use the first frame only.')
                    continue
                if ext == 'pdf' and native:
                    validate_complete(attachment.data, ext)
                    result.files.append({'name': attachment.name, 'media_type': attachment.media_type,
                                         'data_base64': base64.b64encode(attachment.data).decode('ascii')})
                    continue
                path = Path(folder) / f'{index}.{ext}'
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(attachment.data)
                header = f'\n[Untrusted attachment: {attachment.name}]\n'
                header_size = len(header.encode('utf-8'))
                if header_size > budget:
                    result.notices.append(NOTICE)
                    continue
                result.text += header
                budget -= header_size
                chunks = _extract(path, ext, progress=progress, cancelled=cancelled) if ext == "pdf" else _extract(path, ext)
                found = False
                included_lines = 0
                try:
                    for chunk in chunks:
                        if not chunk:
                            continue
                        found = True
                        raw = (chunk + '\n').encode('utf-8')
                        if len(raw) > budget:
                            fragment = raw[:budget].decode('utf-8', errors='ignore')
                            if ext in ('csv', 'tsv') and '\n' in fragment:
                                fragment = fragment[:fragment.rfind('\n') + 1]
                            result.text += fragment
                            included_lines += fragment.count('\n')
                            budget = 0
                            result.notices.append(NOTICE)
                            result.truncation.append({'file_index': index, 'included_lines': included_lines, 'included_bytes': len(fragment.encode('utf-8'))})
                            break
                        result.text += chunk + '\n'
                        included_lines += chunk.count('\n') + 1
                        budget -= len(raw)
                finally:
                    chunks.close()
                LOG.info('attachment_extracted index=%d type=%s elapsed_ms=%d included_lines=%d', index, ext, round((time.monotonic()-file_started)*1000), included_lines)
                if not found:
                    result.notices.append('No extractable text was found in an attachment; scanned documents may need OCR.')
            except DocumentError as exc:
                LOG.info('attachment_failed index=%d code=%s elapsed_ms=%d', index, exc.code, round((time.monotonic()-file_started)*1000))
                raise
            except Exception:
                LOG.info('attachment_failed index=%d code=extraction_failed elapsed_ms=%d', index, round((time.monotonic()-file_started)*1000))
                _fail('extraction_failed', 'Attachment could not be safely decoded or extracted. Convert it to PDF or UTF-8 text and try again.')
    result.notices = list(dict.fromkeys(result.notices))
    LOG.info('attachments_complete files=%d elapsed_ms=%d', len(attachments), round((time.monotonic()-started)*1000))
    if progress: progress({'stage': 'ready'})
    return result


def provider_file_blocks(files, provider):
    """Convert trusted processor output to provider request parts, never upload IDs/URLs."""
    if provider == 'anthropic':
        return [{'type': 'document', 'source': {'type': 'base64', 'media_type': f['media_type'], 'data': f['data_base64']}} for f in files]
    return [{'type': 'file', 'file': {'filename': f['name'], 'file_data': 'data:' + f['media_type'] + ';base64,' + f['data_base64']}} for f in files]


def validate_complete(data, ext):
    """Full staging validation, including native PDFs before provider dispatch."""
    try:
        media = _validate(data, ext)
        if ext in TEXT_EXTENSIONS:
            text = data.decode('utf-8-sig')
            if any((ord(c) < 32 and c not in '\t\r\n') or 127 <= ord(c) <= 159 for c in text):
                _fail('invalid_type', 'Text contains invalid control bytes.')
        elif ext in IMAGE_TYPES:
            _image(data, ext)
        else:
            with tempfile.TemporaryDirectory(prefix='mcptoai-validate-') as folder:
                path = Path(folder) / ('document.' + ext)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream: stream.write(data)
                for _ in _extract(path, ext): pass
        return media
    except DocumentError:
        raise
    except Exception:
        _fail('invalid_type', 'Attachment could not be safely validated.')
