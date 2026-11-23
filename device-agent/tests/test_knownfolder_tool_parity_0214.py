"""All filesystem tools consume the same explicitly authorized roots.

Windows: exercise actual OneDrive Known Folder Move roots, not USERPROFILE\\Desktop.
Never permit a sibling folder when only one redirected root is approved.
"""
import asyncio
import dataclasses
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from mcptoai_agent.workspace_policy import within_allowed_roots


class RootPolicyTests(unittest.TestCase):
    def test_containment_never_expands_to_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            allowed=Path(d)/'Desktop'; allowed.mkdir()
            sibling=Path(d)/'Documents'; sibling.mkdir()
            self.assertTrue(within_allowed_roots(allowed/'new.txt', [allowed]))
            self.assertFalse(within_allowed_roots(sibling/'private.txt', [allowed]))
            self.assertFalse(within_allowed_roots(allowed/'..'/'Documents'/'private.txt', [allowed]))

    @unittest.skipUnless(os.name == 'nt', 'real redirected Windows Known Folder API')
    def test_desktop_documents_tools_and_inbound(self):
        from fastmcp import Client
        from PIL import Image
        from mcptoai_agent.config import Settings
        from mcptoai_agent.preflight import validate
        from mcptoai_agent.tools.host_tools import build_server
        from mcptoai_agent.image_processing import preview,save
        from mcptoai_agent.inbound_transfer import validate_destination
        from mcptoai_agent.windows_known_folders import get_known_folder
        from mcptoai_core.safe_subfolders import plan_inbound_subfolder

        for kind in ('Desktop','Documents'):
            root=get_known_folder(kind)
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=root,prefix='mcptoai-tools-') as tmp:
                work=Path(tmp)
                cfg=Settings(allowed_roots=[root],enable_shell=False)
                self.assertTrue(within_allowed_roots(work, cfg.allowed_roots))
                path=work/'ğşıöçü.txt'
                image=work/'source.png'
                Image.new('RGB',(2,2)).save(image)
                async def exercise():
                    async with Client(build_server(cfg)) as client:
                        calls=(('write_file',{'path':str(path),'content':'ğşıöçü'}),
                               ('list_dir',{'path':str(work)}),
                               ('read_file',{'path':str(path)}),
                               ('find_files',{'root':str(work),'pattern':'*.txt'}),
                               ('image_preview',{'source':str(image),'operation':'resize','width':2,'height':2}),
                               ('image_save',{'source':str(image),'destination':str(work/'out.png'), 'operation':'resize','width':2,'height':2}))
                        for tool,args in calls:
                            reason,_=validate(tool,args,cfg)
                            self.assertIsNone(reason,(kind,tool,reason))
                            reply=await client.call_tool(tool,args,raise_on_error=False)
                            body=''.join(part.text for part in reply.content if hasattr(part,'text'))
                            self.assertNotIn('[ERROR]',body,(kind,tool,body[:250]))
                        self.assertEqual(path.read_text(encoding='utf-8'),'ğşıöçü')
                asyncio.run(exercise())
                uploaded=validate_destination('upload.txt',str(work),cfg.allowed_roots)
                self.assertEqual(uploaded,work/'upload.txt')
                planned,needed=plan_inbound_subfolder(str(root),work.name+'/incoming',cfg.allowed_roots,check_path=lambda *_a,**_k: None)
                self.assertEqual(planned,work/'incoming')
                self.assertTrue(needed)

if __name__=='__main__': unittest.main()
