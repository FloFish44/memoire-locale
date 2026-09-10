"""Local image understanding: objects, colours and OCR. No network calls."""
from pathlib import Path
import asyncio
import json
import os
import sqlite3
import sys

GROUPS = {
    'chat chats chaton félin': list(range(281,286)),
    'chien chiens chiot': list(range(151,269)),
    'oiseau oiseaux': list(range(7,25))+list(range(80,101))+list(range(127,147)),
    'poisson poissons': list(range(0,7))+[389,390,391,392,393,394,395,396,397],
    'serpent': list(range(52,69)), 'papillon': list(range(321,327)),
    'lapin': [330,331], 'cheval': [339], 'éléphant': [385,386],
    'voiture automobile': [407,436,468,511,609,627,656,661,751,817],
    'vélo bicyclette': [444,671], 'bateau navire': [472,510,554,625,814,914],
    'avion': [404,895], 'plage mer': [978], 'montagne': [970,975,980],
    'fleur fleurs': [985,986,987], 'pizza': [963],
    'adhésif adhesive ruban tape scotch rouleau bobine coil enroulé': [507],
}

GROUP_THRESHOLDS = {'adhésif adhesive ruban tape scotch rouleau bobine coil enroulé': .03}

COLOR_TAGS = {
    'rouge red': lambda r,g,b: (r > 90) & (r > g * 1.35) & (r > b * 1.25),
    'orange': lambda r,g,b: (r > 120) & (g > 55) & (g < r * .8) & (b < g * .75),
    'jaune yellow': lambda r,g,b: (r > 115) & (g > 105) & (b < r * .65) & (b < g * .65),
    'vert verte green': lambda r,g,b: (g > 70) & (g > r * 1.18) & (g > b * 1.12),
    'bleu bleue blue': lambda r,g,b: (b > 75) & (b > r * 1.18) & (b > g * 1.08),
    'violet mauve purple': lambda r,g,b: (r > 65) & (b > 75) & (b > g * 1.18) & (r > g * 1.08),
    'rose pink': lambda r,g,b: (r > 125) & (b > 85) & (r > g * 1.18) & (b > g * 1.05),
}

def visual_tags(image):
    """Return conservative colour and format facts for local search."""
    import numpy as np
    sample=image.copy(); sample.thumbnail((320,320))
    pixels=np.asarray(sample.convert('RGB'),dtype=np.float32).reshape(-1,3)
    r,g,b=pixels[:,0],pixels[:,1],pixels[:,2]
    tags=[]
    for label,rule in COLOR_TAGS.items():
        if float(rule(r,g,b).mean()) >= .04: tags.append(label)
    brightness=(r+g+b)/3
    spread=np.maximum.reduce([r,g,b])-np.minimum.reduce([r,g,b])
    if float((brightness<45).mean())>=.35: tags.append('noir noire black fond sombre')
    if float(((brightness>215)&(spread<28)).mean())>=.35: tags.append('blanc blanche white fond clair')
    width,height=sample.size
    if .82 <= width/max(height,1) <= 1.22: tags.append('format carré square')
    elif width>height*1.35: tags.append('format horizontal paysage landscape')
    elif height>width*1.35: tags.append('format vertical portrait')
    return tags

class ImageReader:
    def __init__(self, cache_dir=None):
        import onnxruntime as ort
        model=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'models'/'mobilenetv2.onnx'
        options=ort.SessionOptions(); options.intra_op_num_threads=2
        self.session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
        base=Path(cache_dir) if cache_dir else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Retrio'
        base.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(base/'index-images-v2.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS images (path TEXT PRIMARY KEY,size INTEGER,mtime INTEGER,tags TEXT)')

    def read(self,path):
        import numpy as np
        from PIL import Image, ImageOps
        info=os.stat(path); key=os.path.normcase(os.path.abspath(path))
        hit=self.db.execute('SELECT tags FROM images WHERE path=? AND size=? AND mtime=?',(key,info.st_size,info.st_mtime_ns)).fetchone()
        if hit:return json.loads(hit[0])
        with Image.open(path) as raw:
            if raw.width*raw.height>40_000_000: raise ValueError('Image trop grande')
            original=ImageOps.exif_transpose(raw).convert('RGB')
            tags=visual_tags(original)
            try:
                from pdf_content import _ocr
                words=asyncio.run(_ocr(original)).replace('\x00',' ').strip()
                if words: tags.append(words[:2000])
            except Exception:
                pass
            frame=ImageOps.fit(original,(224,224),method=Image.Resampling.LANCZOS)
            array=np.asarray(frame,dtype=np.float32)/255
        array=(array-np.array([.485,.456,.406],dtype=np.float32))/np.array([.229,.224,.225],dtype=np.float32)
        logits=self.session.run(None,{self.session.get_inputs()[0].name:array.transpose(2,0,1)[None]})[0].reshape(-1)
        probs=np.exp(logits-logits.max());probs/=probs.sum()
        tags.extend(label for label,indices in GROUPS.items()
                    if float(probs[indices].sum())>=GROUP_THRESHOLDS.get(label,.25))
        tags=list(dict.fromkeys(tags))
        self.db.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?)',(key,info.st_size,info.st_mtime_ns,json.dumps(tags,ensure_ascii=False)))
        self.db.commit()
        return tags

    def close(self):self.db.close()
