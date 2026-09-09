"""Opt-in packaged-runtime verification, using only synthetic temporary files."""
import json
from pathlib import Path
import tempfile


def run(destination):
    from PIL import Image, ImageDraw, ImageFont
    from retrio_web import scan_folders, search_entries
    with tempfile.TemporaryDirectory(prefix='retrio-verification-') as temp:
        root=Path(temp); documents=root/'documents';documents.mkdir()
        image=Image.new('RGB',(1400,900),'white')
        draw=ImageDraw.Draw(image)
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',50)
        draw.text((70,80),'FACTURE EDF - EXEMPLE FICTIF',font=font,fill='black')
        draw.text((70,180),'Electricite - Fevrier 2026',font=font,fill='black')
        draw.text((70,280),'Total TTC : 196,67 EUR',font=font,fill='black')
        image.save(documents/'928381.pdf','PDF',resolution=150)
        image.save(root/'visual.png')
        image.close()
        from image_content import ImageReader
        reader=ImageReader(root/'cache')
        visual=reader.read(root/'visual.png')
        reader.close()
        (documents/'00f9edf771.txt').write_text('Contenu sans rapport',encoding='utf-8')
        result=scan_folders([str(documents)],cache_dir=root/'cache')
        matches=search_entries(result.entries,'facture edf')
        ok=len(matches)==1 and matches[0].name=='928381.pdf' and result.pdf_ocr==1
        payload=dict(ok=ok,visual_engine=isinstance(visual,list),files=result.total_files,pdf_read=result.pdf_read,ocr=result.pdf_ocr,
            matches=[e.name for e in matches],issues=result.pdf_issues)
        Path(destination).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if ok else 1
