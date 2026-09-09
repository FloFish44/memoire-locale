"""PDF text + Windows OCR. All processing and cache stay on this PC."""
from __future__ import annotations
import asyncio
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time

READER_VERSION = '1'
MAX_PAGES = 300
MAX_CHARS = 2_000_000
MAX_BYTES = 100 * 1024 * 1024


async def _ocr(image):
    # Windows language packs are used as installed. Never download a model.
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.storage.streams import DataWriter
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
    engine = OcrEngine.try_create_from_language(Language('fr-FR'))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError('Aucune langue OCR Windows installée')
    image = image.convert('RGBA')
    image.thumbnail((min(2400, OcrEngine.max_image_dimension),)*2)
    writer = DataWriter()
    bitmap = None
    try:
        writer.write_bytes(image.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.RGBA8,
            image.width, image.height)
        result = await engine.recognize_async(bitmap)
        return '\n'.join(line.text for line in result.lines)
    finally:
        if bitmap is not None: bitmap.close()
        writer.close()


def read_pdf(path, progress=None):
    result = dict(pages=[], status='PDF lu', total_pages=0, ocr_pages=0, issues=[])
    document = None
    try:
        import pypdfium2 as pdfium
        if os.path.getsize(path) > MAX_BYTES:
            result['status'] = 'PDF > 100 Mo : contenu non analysé'
            return result
        document = pdfium.PdfDocument(path)
        result['total_pages'] = len(document)
        count = 0
        for index in range(min(len(document), MAX_PAGES)):
            page = document[index]
            text_page = None
            try:
                text_page = page.get_textpage()
                text = text_page.get_text_range()
                method = 'texte'
                # OCR a scan, including a page with only a small text footer.
                needs_ocr = len(''.join(text.split())) < 40
                if not needs_ocr and len(text) < 250:
                    area = page.get_width() * page.get_height()
                    for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]):
                        left, bottom, right, top = obj.get_bounds()
                        if (right-left)*(top-bottom) > .4*area:
                            needs_ocr = True
                            break
                if needs_ocr:
                    try:
                        scale = min(2.5, 2400/max(page.get_width(),page.get_height()))
                        bitmap = page.render(scale=scale)
                        try:
                            image = bitmap.to_pil().copy()
                        finally:
                            bitmap.close()
                        try: recognized = asyncio.run(_ocr(image))
                        finally: image.close()
                        if recognized.strip():
                            text = text+'\n'+recognized if text.strip() else recognized
                            method = 'OCR'; result['ocr_pages'] += 1
                    except Exception as exc:
                        result['issues'].append(f'Page {index+1} : OCR indisponible ({type(exc).__name__})')
                text = text.replace('\x00','').strip()
                available = MAX_CHARS-count
                if text:
                    result['pages'].append(dict(page=index+1,text=text[:available],method=method))
                    count += len(text[:available])
                if progress: progress(index+1,len(document))
                if count >= MAX_CHARS:
                    result['issues'].append('Limite de 2 millions de caractères atteinte')
                    break
            except Exception as exc:
                result['issues'].append(f'Page {index+1} illisible ({type(exc).__name__})')
            finally:
                if text_page is not None: text_page.close()
                page.close()
        if len(document) > MAX_PAGES: result['issues'].append('Lecture limitée aux 300 premières pages')
        if not result['pages']:
            result['status'] = 'Aucun texte lisible — PDF scanné, vide ou OCR indisponible'
        elif result['issues']:
            result['status'] = 'PDF partiellement lu'
        elif result['ocr_pages']:
            result['status'] = 'PDF lu avec OCR local'
    except Exception as exc:
        result['status'] = 'PDF protégé, endommagé ou inaccessible'
        result['issues'].append(type(exc).__name__)
    finally:
        if document is not None: document.close()
    return result


def _worker(inbox,outbox):
    while True:
        path = inbox.get()
        if path is None: return
        result = read_pdf(path,lambda page,total: outbox.put(('progress',page,total)))
        outbox.put(('result',result))


class PdfService:
    """One disposable reader process isolates native PDF crashes/timeouts."""
    def __init__(self, cache_dir=None):
        directory = Path(cache_dir) if cache_dir else Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'Retrio'
        directory.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(directory/'index-pdf.sqlite3',timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS pdf_cache(path TEXT PRIMARY KEY,signature TEXT,payload TEXT)')
        self.ctx = mp.get_context('spawn')
        self.process = None

    def _close_worker(self):
        if self.process is not None:
            if self.process.is_alive(): self.process.terminate()
            self.process.join(timeout=2)
            self.inbox.cancel_join_thread(); self.inbox.close()
            self.outbox.cancel_join_thread(); self.outbox.close()
            self.process = None

    def read(self,path,stop=None,progress=None,timeout=180):
        stop = stop or threading.Event()
        path = os.path.normcase(os.path.abspath(path))
        info = os.stat(path)
        signature = f'{READER_VERSION}:{info.st_size}:{info.st_mtime_ns}'
        cached = self.db.execute('SELECT payload FROM pdf_cache WHERE path=? AND signature=?',(path,signature)).fetchone()
        if cached:
            result=json.loads(cached[0]); result['cached']=True
            return result
        if self.process is None or not self.process.is_alive():
            self._close_worker()
            self.inbox=self.ctx.Queue(); self.outbox=self.ctx.Queue()
            self.process=self.ctx.Process(target=_worker,args=(self.inbox,self.outbox),daemon=True)
            self.process.start()
        self.inbox.put(path)
        deadline=time.monotonic()+timeout
        while not stop.is_set() and time.monotonic()<deadline:
            try:
                message=self.outbox.get(timeout=.1)
                if message[0]=='progress':
                    if progress: progress(message[1],message[2])
                    continue
                result=message[1]
                fresh=os.stat(path)
                if signature != f'{READER_VERSION}:{fresh.st_size}:{fresh.st_mtime_ns}':
                    return dict(pages=[],status='PDF modifié pendant la lecture : relancer',issues=[],total_pages=0,ocr_pages=0)
                # Don't cache missing OCR/dependency/error states; retry next scan.
                if result['pages'] and not result['issues']:
                    self.db.execute('INSERT OR REPLACE INTO pdf_cache VALUES(?,?,?)',(path,signature,json.dumps(result,ensure_ascii=False)))
                    self.db.commit()
                return result
            except queue.Empty:
                if not self.process.is_alive(): break
        self._close_worker()
        return dict(pages=[],status='Lecture interrompue' if stop.is_set() else 'Délai de lecture dépassé ou lecteur interrompu',issues=[],total_pages=0,ocr_pages=0)

    def close(self):
        self._close_worker(); self.db.close()
