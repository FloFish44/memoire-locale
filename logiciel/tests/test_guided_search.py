import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from retrio_web import Api, FileEntry, scan_folders, get_known_folders

class GuidedSearchTests(unittest.TestCase):
    def test_technical_folders_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['Codex','Claude','ChatGPT','OpenAI','Anthropic','Documents']:
                (root/name).mkdir();(root/name/'facture.txt').write_text('facture EDF')
            (root/'Documents'/'codex-clipboard-private.png').write_bytes(b'technical')
            (root/'Documents'/'desktop.ini').write_text('[ShellClassInfo]')
            (root/'Documents'/'application.ini').write_text('[settings]')
            result=scan_folders([tmp])
            self.assertEqual(result.total_files,1)
            self.assertIn('Documents',result.entries[0].path)

    def test_same_page_match_ranks_first(self):
        from retrieval import search
        far=FileEntry(path='far.pdf',name='far.pdf',stem='far',ext='.pdf',size=1,
                      category='pdf',content='facture\nEDF',badly_named=True,
                      pages=[{'page':1,'text':'facture','method':'texte'},
                             {'page':2,'text':'EDF','method':'texte'}])
        exact=FileEntry(path='928381.pdf',name='928381.pdf',stem='928381',ext='.pdf',size=1,
                        category='pdf',content='Facture EDF',badly_named=True,
                        pages=[{'page':1,'text':'Facture EDF','method':'OCR'}])
        self.assertEqual(search([far,exact],'facture EDF')[0].name,'928381.pdf')

    def test_pdf_word_is_a_filter_not_a_required_content_word(self):
        api=Api()
        entry=FileEntry(path='928381.pdf',name='928381.pdf',stem='928381',ext='.pdf',size=1,
                        category='pdf',content='Facture EDF',badly_named=True,
                        pages=[{'page':1,'text':'Facture EDF','method':'OCR'}])
        api.scan_result.entries=[entry]
        payload=json.loads(api.search('PDF facture EDF','pdf'))
        self.assertEqual([item['name'] for item in payload['matches']],['928381.pdf'])

    def test_image_intent_and_folder_filter(self):
        api=Api()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for folder,ext,category,content in [('Photos','.jpg','images','chat chats'),('PhotosBis','.jpg','images','chat chats'),('Documents','.txt','documents','chat chats')]:
                path=root/folder/('928381'+ext)
                api.scan_result.entries.append(FileEntry(path=str(path),name=path.name,stem=path.stem,ext=ext,size=10,category=category,content=content,badly_named=True))
            payload=json.loads(api.search('image de chat','image',str(root/'Photos')))
            self.assertEqual(len(payload['matches']),1)
            self.assertIn('Photos',payload['matches'][0]['path'])

    @unittest.skipUnless(sys.platform=='win32','Windows only')
    def test_desktop_offered(self):
        self.assertIn('Bureau',get_known_folders())
