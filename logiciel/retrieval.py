"""Deterministic local relevance: all concepts required, no hash substrings."""
import re
import unicodedata
from difflib import SequenceMatcher

STOP = set('le la les un une des de du d l avec et ou sur dans pour mon ma mes au aux ce cette ces the a an with and or for of my je moi tu me retrouve retrouver trouve trouver cherche chercher montre montrer fichier fichiers document documents stp sil te plait concernant'.split())
CONCEPTS = [
    {'facture','factures','invoice','recu','recus','receipt'},
    {'assurance','assurances','assureur'},
    {'contrat','contrats','convention','bail'},
    {'devis','devis','estimation'},
    {'electricite','electrique','electric','electricity'},
    {'lavelinge','machinealaver','laveuse'},
    {'photo','photos','image','images'},
    {'impot','impots','fiscal','fiscale','taxe'},
    {'habitation','logement','domicile'},
]

def normalize(s):
    s=''.join(c for c in unicodedata.normalize('NFD',s.lower()) if unicodedata.category(c)!='Mn')
    s=re.sub(r'lave[\s-]*linge|machine\s+a\s+laver','lavelinge',s)
    return s

def tokenize(s):
    return re.findall(r'[a-z0-9]+',normalize(s))

def query_groups(query):
    words=list(dict.fromkeys(w for w in tokenize(query) if w not in STOP))[:20]
    groups=[]
    for word in words:
        group=next((set(g) for g in CONCEPTS if word in g),{word})
        if len(group)==1 and word.isalpha() and len(word)>4 and word.endswith('s'): group.add(word[:-1])
        if group not in groups: groups.append(group)
    return groups

def relevance(entry,groups):
    if not groups: return 0
    # Cached token sets avoid retokenizing multi-page documents on every search.
    fields=getattr(entry,'_search_tokens',None)
    if fields is None:
        import os
        fields=(set(tokenize(entry.stem)),set(tokenize(entry.content)),set(tokenize(os.path.dirname(entry.path))))
        entry._search_tokens=fields
    name,content,folder=fields
    score=0
    for group in groups:
        direct_content=bool(group & content); direct_name=bool(group & name)
        if direct_content or direct_name:
            score += (12 if direct_content else 0)+(9 if direct_name else 0)
            continue
        if group & folder:
            score += 2
            continue
        # Never fuzz short terms like EDF into arbitrary hash/filename fragments.
        fuzzy=any(len(word)>=5 and word.isalpha() and any(
            candidate.isalpha() and abs(len(word)-len(candidate))<=1 and
            SequenceMatcher(None,word,candidate).ratio()>=.86
            for candidate in name|content) for word in group)
        if fuzzy: score+=4
        else: return 0
    # Favor documents where every requested concept appears together on the
    # same page. This makes the actual invoice outrank loose coincidences.
    pages=getattr(entry,'pages',[]) or []
    if pages:
        for page in pages:
            words=set(tokenize(page.get('text','')))
            if all(group & words for group in groups):
                score += 10
                break
    return score

def search(entries,query,limit=60):
    groups=query_groups(query)
    ranked=[(relevance(e,groups),e) for e in entries]
    ranked=[pair for pair in ranked if pair[0]>0]
    ranked.sort(key=lambda pair:(-pair[0],pair[1].name.lower()))
    return [e for _,e in ranked[:limit]] if limit is not None else [e for _,e in ranked]

def evidence(entry,query):
    groups=query_groups(query)
    pages=getattr(entry,'pages',[]) or [{'page':None,'text':entry.content,'method':'texte'}]
    if not entry.content: return dict(text='',page=None,method='')
    def page_score(page):
        words=set(tokenize(page['text']))
        return sum(bool(group & words) for group in groups)
    page=max(pages,key=page_score)
    text=page['text']
    # Pick the narrowest region covering the most query concepts. Keep original text.
    occurrences=[]
    for match in re.finditer(r'\w+',text):
        word=normalize(match.group())
        for i,group in enumerate(groups):
            if word in group: occurrences.append((match.start(),match.end(),i))
    position=0; best=(-1,float('-inf'))
    for start,end,_ in occurrences:
        hits=[p for p in occurrences if start<=p[0]<=start+260]
        key=(len({p[2] for p in hits}),-(max(p[1] for p in hits)-start))
        if key>best: best=key; position=start
    start=max(0,position-55); end=min(len(text),start+350)
    return dict(text=('… ' if start else '')+text[start:end].strip()+(' …' if end<len(text) else ''),page=page['page'],method=page['method'])
