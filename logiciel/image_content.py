"""Local MobileNet classification. No downloads or network calls at runtime."""
from pathlib import Path
import os
import sys
import json
import sqlite3

# ImageNet class indices. French labels are intentionally broad, not invented captions.
GROUPS = {
    'chat chats chaton félin': list(range(281,286)),
    'chien chiens chiot': list(range(151,269)),
    'oiseau oiseaux': list(range(7,25))+list(range(80,101))+list(range(127,147)),
    'poisson poissons': list(range(0,7))+[389,390,391,392,393,394,395,396,397],
    'serpent': list(range(52,69)),
    'papillon': list(range(321,327)),
    'lapin': [330,331], 'cheval': [339], 'éléphant': [385,386],
    'voiture automobile': [407,436,468,511,609,627,656,661,751,817],
    'vélo bicyclette': [444,671], 'bateau navire': [472,510,554,625,814,914],
    'avion': [404,895], 'plage mer': [978], 'montagne': [970,975,980],
    'fleur fleurs': [985,986,987], 'pizza': [963],
}

class ImageReader:
    def __init__(self, cache_dir=None):
        import onnxruntime as ort
        model=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'models'/'mobilenetv2.onnx'
        options=ort.SessionOptions(); options.intra_op_num_threads=2
        self.session=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
        base=Path(cache_dir) if cache_dir else Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Retrio'
        base.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(base/'index-images.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS images (path TEXT PRIMARY KEY,size INTEGER,mtime INTEGER,tags TEXT)')

    def read(self,path):
        import numpy as np
        from PIL import Image, ImageOps
        info=os.stat(path); key=os.path.normcase(os.path.abspath(path))
        hit=self.db.execute('SELECT tags FROM images WHERE path=? AND size=? AND mtime=?',(key,info.st_size,info.st_mtime_ns)).fetchone()
        if hit:return json.loads(hit[0])
        with Image.open(path) as raw:
            if raw.width*raw.height>40_000_000: raise ValueError('Image trop grande')
            frame=ImageOps.exif_transpose(raw).convert('RGB')
            frame=ImageOps.fit(frame,(224,224),method=Image.Resampling.LANCZOS)
            array=np.asarray(frame,dtype=np.float32)/255
        array=(array-np.array([.485,.456,.406],dtype=np.float32))/np.array([.229,.224,.225],dtype=np.float32)
        logits=self.session.run(None,{self.session.get_inputs()[0].name:array.transpose(2,0,1)[None]})[0].reshape(-1)
        probs=np.exp(logits-logits.max());probs/=probs.sum()
        # Group related breeds; require meaningful confidence to avoid noisy labels.
        tags=[label for label,indices in GROUPS.items() if float(probs[indices].sum())>=.25]
        self.db.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?)',(key,info.st_size,info.st_mtime_ns,json.dumps(tags)))
        self.db.commit()
        return tags

    def close(self):self.db.close()
