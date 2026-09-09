import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.pdfencrypt import StandardEncryption
from PIL import Image, ImageDraw, ImageFont
from pdf_content import PdfService, read_pdf
from retrio_web import scan_folders, FileEntry, search_entries, content_snippet
from retrieval import evidence


def pdf(path,texts,encrypt=None):
    c=canvas.Canvas(str(path),encrypt=encrypt)
    for text in texts:
        c.setFont('Helvetica',12)
        for i,line in enumerate(text.splitlines()): c.drawString(40,800-20*i,line)
        c.showPage()
    c.save()


class PdfSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.documents=self.root/'documents'; self.documents.mkdir()
        self.cache=self.root/'cache'
    def tearDown(self): self.tmp.cleanup()
    def scan(self,roots=None): return scan_folders(roots or [str(self.documents)],cache_dir=self.cache)

    def test_renamed_invoice_found_by_content_and_page(self):
        p=self.documents/'41684346vc.pdf'
        pdf(p,['Facture EDF\nElectricite fevrier 2026\nTotal TTC : 196,67 EUR','Informations contractuelles'])
        result=self.scan()
        matches=search_entries(result.entries,'retrouve moi la facture EDF')
        self.assertEqual([e.name for e in matches],[p.name])
        self.assertEqual(result.pdf_read,1)
        self.assertEqual(evidence(matches[0],'facture EDF')['page'],1)
        self.assertIn('EDF',content_snippet(matches[0],'facture EDF'))

    def test_late_page_is_indexed(self):
        p=self.documents/'928381.pdf'
        pdf(p,['Conditions generales '+('texte '*4000),'Facture EDF\nTotal TTC 196,67 EUR'])
        matches=search_entries(self.scan().entries,'facture EDF')
        self.assertEqual(len(matches),1)
        self.assertEqual(evidence(matches[0],'facture EDF')['page'],2)

    def test_unrelated_invoices_and_hashes_are_excluded(self):
        entries=[FileEntry('/temp/00bf951edf65a.txt','00bf951edf65a.txt','00bf951edf65a','.txt','documents',10,False),
                 FileEntry('/temp/facture.txt','facture.txt','facture','.txt','documents',20,False,content='Facture Orange telephone',content_lower='facture orange telephone')]
        self.assertEqual(search_entries(entries,'facture edf'),[])
        self.assertEqual(search_entries(entries,'edf'),[])

    def test_fuzzy_invoice_but_exact_provider(self):
        entry=FileEntry('/temp/098.pdf','098.pdf','098','.pdf','pdf',50,True,content='Facture EDF Electricité',content_lower='facture edf electricité')
        self.assertEqual(search_entries([entry],'facturre edf'),[entry])
        self.assertEqual(search_entries([entry],'facture engie'),[])
        self.assertEqual(search_entries([entry],'electricite edf'),[entry])

    def test_overlapping_folders_are_counted_once(self):
        sub=self.documents/'nested';sub.mkdir();pdf(sub/'123.pdf',['Facture EDF montant total 196,67 EUR'])
        result=self.scan([str(self.documents),str(sub),str(self.documents)])
        self.assertEqual(result.total_files,1)

    def test_cache_reused_then_invalidated(self):
        p=self.documents/'123.pdf';pdf(p,['Facture EDF montant 196,67 EUR'])
        service=PdfService(self.cache)
        try:
            first=service.read(str(p));second=service.read(str(p))
            self.assertTrue(second.get('cached'));self.assertTrue(first['pages'])
            pdf(p,['Facture ENGIE montant 210,99 EUR pour electricite'])
            third=service.read(str(p))
            self.assertFalse(third.get('cached',False))
            self.assertIn('ENGIE',third['pages'][0]['text'])
        finally:service.close()

    def test_corrupt_and_encrypted_pdf_reported(self):
        (self.documents/'broken.pdf').write_bytes(b'not a pdf')
        pdf(self.documents/'protected.pdf',['Facture EDF'],StandardEncryption('secret'))
        result=self.scan()
        self.assertEqual(result.total_files,2);self.assertEqual(result.pdf_unread,2)
        self.assertEqual(len(result.pdf_issues),2)

    def test_cancellation_and_missing_root(self):
        event=threading.Event();event.set()
        result=scan_folders([str(self.documents)],stop_flag=event,cache_dir=self.cache)
        self.assertTrue(result.cancelled)
        self.assertEqual(self.scan([str(self.root/'missing')]).errors,1)

    @unittest.skipUnless(sys.platform=='win32','Windows OCR')
    def test_scanned_pdf_ocr(self):
        image=Image.new('RGB',(1400,900),'white')
        draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',50)
        draw.text((70,80),'FACTURE EDF',font=font,fill='black')
        draw.text((70,180),'Electricite - Fevrier 2026',font=font,fill='black')
        draw.text((70,280),'Total TTC : 196,67 EUR',font=font,fill='black')
        p=self.documents/'scan_003.pdf'
        c=canvas.Canvas(str(p),pagesize=(700,450));c.drawImage(ImageReader(image),0,0,width=700,height=450);c.save()
        result=self.scan()
        self.assertEqual(result.pdf_ocr,1,str(result.pdf_issues))
        self.assertEqual(len(search_entries(result.entries,'facture edf')),1)
        self.assertEqual(evidence(result.entries[0],'facture edf')['method'],'OCR')


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    unittest.main()
