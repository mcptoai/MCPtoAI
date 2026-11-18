import asyncio
import io
import json
from dataclasses import replace

import pytest
from fastmcp import Client
from PIL import Image, PngImagePlugin

from mcptoai_agent.config import settings
from mcptoai_agent.image_processing import preview, save
from mcptoai_agent.policy import ToolPolicy, Decision, FORCE_CONFIRM_TOOLS
from mcptoai_agent.tools import build_server


def _source(tmp_path):
    p = tmp_path / 'source.png'
    image = Image.new('RGBA', (120, 80), (255, 0, 0, 128))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Comment', 'sensitive data')
    image.save(p, pnginfo=metadata)
    return p


def test_resize_crop_convert_and_metadata(tmp_path):
    src = _source(tmp_path)
    roots = [tmp_path]
    info = preview(str(src), roots, 'resize', width=60, height=60, output_format='JPEG')
    assert info['dimensions'] == [60, 40] and info['preview_data_url'].startswith('data:image/jpeg;base64,')
    dest = tmp_path / 'out.jpg'
    result = save(str(src), str(dest), roots, 'resize', width=60, height=60, output_format='JPEG')
    assert result['bytes'] == dest.stat().st_size
    with Image.open(dest) as image:
        assert image.size == (60, 40) and not image.getexif() and not image.info.get('Comment')
    cropped = save(str(src), str(tmp_path / 'crop.webp'), roots, 'crop', left=10, top=20, right=30, bottom=50, output_format='WEBP')
    assert cropped['dimensions'] == [20, 30]
    with pytest.raises(ValueError):
        preview(str(src), roots, 'crop', right=200, bottom=20)
    with pytest.raises(ValueError):
        preview(str(src), roots, 'resize', width=20000, height=2)
    with pytest.raises(FileExistsError):
        save(str(src), str(dest), roots, 'convert', output_format='JPEG')
    assert save(str(src), str(dest), roots, 'convert', output_format='JPEG', overwrite=True)['saved_to'] == str(dest)


def test_roots_symlinks_and_invalid_format(tmp_path):
    src = _source(tmp_path)
    outside = tmp_path.parent / 'outside-test-image.png'
    with pytest.raises(PermissionError):
        preview(str(outside), [tmp_path], 'convert')
    link = tmp_path / 'alias.png'
    link.symlink_to(src)
    with pytest.raises(ValueError):
        preview(str(link), [tmp_path], 'convert')
    with pytest.raises(ValueError):
        save(str(src), str(tmp_path / 'wrong.txt'), [tmp_path], 'convert')
    with pytest.raises(ValueError):
        preview(str(src), [tmp_path], 'convert', output_format='GIF')


def test_approval_cannot_be_bypassed():
    assert 'image_save' in FORCE_CONFIRM_TOOLS
    policy = ToolPolicy(rules={'image_save': Decision.AUTO})
    approvals = []
    async def deny(tool, args):
        approvals.append((tool, args))
        return False
    assert asyncio.run(policy.authorize('image_save', {'overwrite': True}, deny))[0] is False
    assert approvals == [('image_save', {'overwrite': True})]


def test_image_tools_mcp(tmp_path):
    src = _source(tmp_path)
    cfg = replace(settings, allowed_roots=[tmp_path])
    async def run():
        async with Client(build_server(cfg)) as client:
            names = {t.name for t in await client.list_tools()}
            assert {'image_preview', 'image_save'} <= names
            result = await client.call_tool('image_preview', {'source': str(src), 'operation': 'convert'})
            data = json.loads(''.join(getattr(x, 'text', '') for x in result.content))
            assert data['dimensions'] == [120, 80]
    asyncio.run(run())
