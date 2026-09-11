#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrio — application Windows de recherche documentaire (interface web).

100% local : aucune analyse, aucun fichier et aucune requête n'est envoyé
sur Internet. Tout le traitement (parcours des dossiers, index, recherche)
se fait sur la machine de l'utilisateur — seule l'INTERFACE est rendue par
un moteur web (WebView2, déjà présent sur Windows 10/11) qui charge la page
locale app.html : rendu identique au design d'origine (anti-aliasing natif,
polices exactes), sans jamais rien envoyer sur le réseau.

Lecture PDF : PDFium. OCR : moteur Windows et langues installées localement.
Interface : pywebview / WebView2. Aucun service de reconnaissance distant.

Lancer :   python retrio_web.py
Compiler : voir build_web.bat (utilise PyInstaller)
"""

import multiprocessing
import base64
import csv
import ctypes
import difflib
import mimetypes
import io
import json
import os
import re
import sys
import subprocess
import threading
import tempfile
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from pdf_content import PdfService, read_pdf
from image_content import ImageReader
from retrieval import search as search_by_content, evidence

APP_NAME = "Retrio"
APP_VERSION = "0.5.1 (bêta)"

# ---------------------------------------------------------------------------
# Icône de l'application (PNG encodé en base64, intégré directement au
# script pour ne dépendre d'aucun fichier externe au runtime)
# ---------------------------------------------------------------------------
ICON_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAADeUlEQVR4nJ2XTW/cNhCGn6G0Wie2dxsHMFIgXvvUa3oK2l8R5B+kQH9sfWoK9FCgHyhQpAGKOKk/urJWIqcHSlotV5Tk8LDSjobvvJwZcoayWJ0qzZD6qZ336JBaMZwY0+ngdkRmR18DjBBvRxYqDipHRabve6sTemGSZ/p5aOCs5u8egen4n8Nkf/Yegfajsu/ZHZu68xizJsH/RmB2hL2GxsEn64W6AmmblX0J3As0ZlGneaUeaaPfwgb4qiCmxq2c1+3bdbLVN2lvZCMEmrnB/mxYiXjDkhjmJ0deMOQEq2xuc9Q6JDWd9I8RiMW+ZqXWMTt+xMnXF2SLx56jgHQYC1LzFVSV8nbN1ds/KW/WSJIwFBMzHC9FjPDkxTkHT49R58ApOA3eFbUOZyuctcyfHPH0xQUYM2jcE4gOv/r06IBseYjbVCCCGMGIkCQJxiSIGFQVVecBRXCbitnxI2bHB6h1DMVsuwv2dLTh4R3cyRFrLUWee5HCPMswxnRnIapIk61hfu0QaBR6PBByMSJUVcXyiyWr1YrKVjir/PHb75RlSZKmSJ10U3fitP1Sr0DrVZVFyavXr3j27EvOL8558/13GGNQ51BVnAvMawjWJRCj2nWAblGMGPL7nJubG/I85+rDBw4PDzFJgnVuG82oC3Y/pPvu76nzWsNq/a7g1PH87DlnZ2dc/nDJ9ad/WSyXfncAWp9wYwW0JwSRGl4bttayWCxI0xnv/37PTz++5eU3L1mdryiLTScJp1VvWZyfRpwlqLXMFo85/far+uAB5xzz+ZzZLEUVyrIkyzIqa8nXa78absv/XP5Kef0fkibREzEdIdguwamvWCJQFAX5fd6efPk6xxiDSUybrHsejIxhAuIPI3XecIMrIqQm9Seg+NNSUVwdf9Tr4Nxo9RzYhh64uisorm4x2YymOqn6UDiaPb+tCSgk8xnFxzvKu3vEDJxCUzyAKJ9+/gutHNnJUS3veKP92dpZv/vI9S/vBqFbE/Ek3A5VX3SSgyxoHHq6GFXs/aatG2NjPAmp45kItii7woZeh6nnMJT1IeFJBFr1ZkWN8bB/l6ZRnd6TjfQDkdHtIXv7s+lApvfy8SAG4ehrfyMQ9HngQfeNnivPVKD2XvDZF5zuSvs80q0EcSMjOTDRnVE9DZ59BHrBxgxEby087JYD/wNID45gGI7YLQAAAABJRU5ErkJggg=="

# ---------------------------------------------------------------------------
# Palette et typographie : définies plus bas, dans la section interface
# graphique (identiques au site Retrio et à l'installateur — cf. design
# tokens COL_* / FONT_SERIF / FONT_SANS / FONT_MONO).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Dossiers connus (compatibles avec un Windows localisé en français)
# ---------------------------------------------------------------------------

# GUID des dossiers connus Windows (Known Folder API), indépendants de la langue
KNOWN_FOLDER_GUIDS = {
    "Bureau": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Images": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Vidéos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "Musique": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Téléchargements": "374DE290-123F-4565-9164-39C4925E467B",
}


def _get_known_folder_win(guid: str) -> str | None:
    """Retourne le chemin réel d'un dossier connu Windows, quelle que soit la langue."""
    try:
        buf = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32
        guid_struct = ctypes.create_unicode_buffer(guid)
        # SHGetKnownFolderPath attend un GUID binaire (ctypes.wintypes) ; on
        # utilise une méthode compatible en construisant un GUID via ole32.
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_byte * 8),
            ]

        rfid = GUID()
        ole32 = ctypes.windll.ole32
        ole32.CLSIDFromString(ctypes.create_unicode_buffer("{" + guid + "}"), ctypes.byref(rfid))
        ret = shell32.SHGetKnownFolderPath(ctypes.byref(rfid), 0, 0, ctypes.byref(buf))
        if ret == 0 and buf.value:
            path = buf.value
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except Exception:
        return None
    return None


def get_known_folders() -> dict[str, str]:
    """Construit la liste des dossiers proposés à l'utilisateur (nom -> chemin)."""
    folders: dict[str, str] = {}
    home = str(Path.home())

    if sys.platform == "win32":
        for label, guid in KNOWN_FOLDER_GUIDS.items():
            path = _get_known_folder_win(guid)
            if path and os.path.isdir(path):
                folders[label] = path
        # Repli si l'API Windows échoue : noms de dossiers usuels
        fallback_names = {
            "Bureau": "Desktop",
            "Documents": "Documents",
            "Images": "Pictures",
            "Vidéos": "Videos",
            "Musique": "Music",
            "Téléchargements": "Downloads",
        }
        for label, folder_name in fallback_names.items():
            if label not in folders:
                guess = os.path.join(home, folder_name)
                if os.path.isdir(guess):
                    folders[label] = guess
    else:
        # Environnement non-Windows (développement / test sur Linux ou macOS)
        fallback_names = {
            "Bureau": "Desktop",
            "Documents": "Documents",
            "Images": "Pictures",
            "Vidéos": "Videos",
            "Musique": "Music",
            "Téléchargements": "Downloads",
        }
        for label, folder_name in fallback_names.items():
            guess = os.path.join(home, folder_name)
            if os.path.isdir(guess):
                folders[label] = guess

    # Disques / partitions
    if sys.platform == "win32":
        import string

        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    # On ne propose pas le lecteur système "A:" ou lecteurs
                    # amovibles vides par défaut, mais on liste C: et D: en priorité.
                    if letter in ("C", "D") and os.path.isdir(drive):
                        folders[f"Disque {letter}:"] = drive
                except Exception:
                    pass
    else:
        if os.path.isdir("/"):
            folders["Disque (racine)"] = "/"

    return folders


# ---------------------------------------------------------------------------
# Catégorisation des fichiers
# ---------------------------------------------------------------------------
EXT_PDF = {".pdf"}
EXT_IMAGES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".heif", ".svg", ".raw"}
EXT_VIDEOS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".flv", ".webm"}
EXT_AUDIO = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".wma", ".ogg"}
EXT_DOCS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".odt", ".ods", ".odp", ".rtf", ".csv"}
EXT_ARCHIVES = {".zip", ".rar", ".7z", ".tar", ".gz"}

# Extensions pour lesquelles on tente une extraction du contenu texte
# (utilisées pour indexer et retrouver un fichier par ce qu'il contient,
# pas seulement par son nom). Tout est fait avec la bibliothèque standard.
EXT_TEXT_READABLE = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm", ".rtf"}
EXT_DOCX = {".docx"}
EXT_XLSX = {".xlsx"}
EXT_PPTX = {".pptx"}

# Fichiers techniques sans intérêt pour la recherche personnelle.
# Ils ne sont ni comptés ni ajoutés à l'index.
IGNORED_EXTENSIONS = {".ini"}

# Taille max lue par fichier pour l'extraction de contenu (évite de passer
# un temps disproportionné sur d'énormes fichiers texte/logs).
MAX_CONTENT_READ_BYTES = 2_000_000
# Longueur max du contenu conservé en mémoire par fichier (index + aperçu).
MAX_CONTENT_KEEP_CHARS = 20_000

# Dossiers à ignorer pendant le parcours (dossiers système / techniques)
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "programdata",
    "program files", "program files (x86)", "node_modules", ".git", ".cache",
    "appdata", "codex", "claude", "chatgpt", "openai", "anthropic",
    ".codex", ".claude", ".openai", "__pycache__", ".venv",
}

SKIP_FILE_PREFIXES = (
    "codex-clipboard-", "codex-session-", "claude-session-",
    "chatgpt-session-", "chatgpt-export-",
)

# Motifs de noms de fichiers "peu parlants" (scan, capture, sans titre...)
BADLY_NAMED_PATTERNS = [
    re.compile(r"^img_?\d+$", re.I),
    re.compile(r"^scan_?\d+$", re.I),
    re.compile(r"^scan\d{4,}.*$", re.I),
    re.compile(r"^document\d*$", re.I),
    re.compile(r"^document \(\d+\)$", re.I),
    re.compile(r"^nouveau document.*$", re.I),
    re.compile(r"^sans titre.*$", re.I),
    re.compile(r"^untitled.*$", re.I),
    re.compile(r"^copie de .*$", re.I),
    re.compile(r"^\d{8,}$"),
    re.compile(r"^capture d.?écran.*$", re.I),
    re.compile(r"^dsc_?\d+$", re.I),
    re.compile(r"^photo_?\d+$", re.I),
    re.compile(r"^fichier\d*$", re.I),
    re.compile(r"^new document.*$", re.I),
]


def categorize(ext: str) -> str:
    ext = ext.lower()
    if ext in EXT_PDF:
        return "pdf"
    if ext in EXT_IMAGES:
        return "images"
    if ext in EXT_VIDEOS:
        return "videos"
    if ext in EXT_AUDIO:
        return "audio"
    if ext in EXT_DOCS:
        return "documents"
    if ext in EXT_ARCHIVES:
        return "archives"
    return "autres"


def is_badly_named(stem: str) -> bool:
    stem = stem.strip()
    for pattern in BADLY_NAMED_PATTERNS:
        if pattern.match(stem):
            return True
    return False


CATEGORY_LABELS = {
    "pdf": "PDF",
    "images": "Photos & images",
    "videos": "Vidéos",
    "audio": "Musique & audio",
    "documents": "Autres documents",
    "archives": "Archives",
    "autres": "Autres fichiers",
}


# ---------------------------------------------------------------------------
# Extraction de contenu (100% bibliothèque standard)
#
# But : permettre de retrouver un fichier par ce qu'il CONTIENT (le texte
# d'une facture, les cellules d'un tableau, le texte d'une présentation...)
# et pas seulement par son nom de fichier. Chaque fonction est "best effort"
# et ne lève jamais d'exception vers l'appelant : un fichier illisible ou
# corrompu est simplement ignoré pour l'indexation de contenu (son nom
# reste malgré tout cherchable).
# ---------------------------------------------------------------------------

def _read_plain_text(path: str) -> str:
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_CONTENT_READ_BYTES)
        for encoding in ("utf-8", "cp1252", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _read_csv_text(path: str) -> str:
    text = _read_plain_text(path)
    if not text:
        return ""
    try:
        reader = csv.reader(io.StringIO(text[:MAX_CONTENT_READ_BYTES]))
        rows = []
        for i, row in enumerate(reader):
            if i > 2000:
                break
            rows.append(" ".join(row))
        return "\n".join(rows)
    except Exception:
        return text


def _xml_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
        return " ".join(t.strip() for t in root.itertext() if t and t.strip())
    except Exception:
        return ""


def _read_docx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("word/document.xml")
        return _xml_text(data)
    except Exception:
        return ""


def _read_xlsx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.startswith("xl/worksheets/") and n.endswith(".xml")]
            shared = ""
            if "xl/sharedStrings.xml" in z.namelist():
                shared = _xml_text(z.read("xl/sharedStrings.xml"))
            parts = [shared]
            for n in names[:20]:  # limite raisonnable de feuilles parcourues
                parts.append(_xml_text(z.read(n)))
        return " ".join(p for p in parts if p)
    except Exception:
        return ""


def _read_pptx_text(path: str) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
            parts = []
            for n in names[:200]:
                parts.append(_xml_text(z.read(n)))
        return " ".join(p for p in parts if p)
    except Exception:
        return ""


def extract_text_content(path: str, ext: str) -> str:
    """Retourne un extrait texte du fichier pour l'indexation de contenu,
    ou une chaîne vide si le format n'est pas pris en charge / illisible."""
    ext = ext.lower()
    try:
        if ext == ".pdf":
            return "\n\n".join(page["text"] for page in read_pdf(path)["pages"])
        elif ext == ".csv":
            text = _read_csv_text(path)
        elif ext in EXT_TEXT_READABLE:
            text = _read_plain_text(path)
            if ext in (".html", ".htm", ".xml"):
                text = re.sub(r"<[^>]+>", " ", text)
        elif ext in EXT_DOCX:
            text = _read_docx_text(path)
        elif ext in EXT_XLSX:
            text = _read_xlsx_text(path)
        elif ext in EXT_PPTX:
            text = _read_pptx_text(path)
        else:
            text = ""
    except Exception:
        text = ""

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_CONTENT_KEEP_CHARS:
        text = text[:MAX_CONTENT_KEEP_CHARS]
    return text


@dataclass
class FileEntry:
    path: str
    name: str
    stem: str
    ext: str
    category: str
    size: int
    badly_named: bool
    content: str = ""          # extrait de contenu indexé (peut être vide)
    content_lower: str = ""    # version en minuscule, prête pour la recherche
    pages: list = field(default_factory=list)
    read_status: str = "Nom et emplacement"


@dataclass
class ScanResult:
    entries: list = field(default_factory=list)
    counts_by_category: dict = field(default_factory=lambda: defaultdict(int))
    total_files: int = 0
    total_size: int = 0
    duplicates_count: int = 0
    badly_named_count: int = 0
    content_indexed_count: int = 0
    errors: int = 0
    pdf_read: int = 0
    pdf_ocr: int = 0
    pdf_unread: int = 0
    pdf_partial: int = 0
    cancelled: bool = False
    pdf_issues: list = field(default_factory=list)


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["o", "Ko", "Mo", "Go", "To"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Po"


def scan_folders(roots: list, progress_cb=None, stop_flag=None, cache_dir=None) -> ScanResult:
    """Read selected local files once. PDF parsing is isolated and cached."""
    result = ScanResult()
    stop_flag = stop_flag or threading.Event()
    size_index = defaultdict(list)
    normalized = sorted(set(os.path.normcase(os.path.abspath(r)) for r in roots), key=len)
    roots = []
    for root in normalized:
        def within(parent):
            try: return os.path.commonpath([root, parent]) == parent
            except ValueError: return False
        if not any(within(parent) for parent in roots): roots.append(root)
    seen = set()
    service = None
    image_reader = None
    def scan_error(_error): result.errors += 1
    try:
        for root in roots:
            if not os.path.isdir(root):
                result.errors += 1
                continue
            for dirpath, dirnames, filenames in os.walk(root, onerror=scan_error, followlinks=False):
                if stop_flag.is_set(): break
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIR_NAMES and not d.startswith('.') and not os.path.islink(os.path.join(dirpath,d)) and not getattr(os.path,"isjunction",lambda _:False)(os.path.join(dirpath,d))]
                for filename in filenames:
                    if stop_flag.is_set(): break
                    if filename.lower().startswith(SKIP_FILE_PREFIXES):
                        continue
                    if os.path.splitext(filename)[1].lower() in IGNORED_EXTENSIONS:
                        continue
                    full_path = os.path.abspath(os.path.join(dirpath,filename))
                    key = os.path.normcase(full_path)
                    if key in seen: continue
                    seen.add(key)
                    try:
                        info = os.stat(full_path, follow_symlinks=False)
                        attrs = getattr(info,'st_file_attributes',0)
                        if os.path.islink(full_path) or attrs & (0x1000 | 0x40000 | 0x400000):
                            result.errors += 1
                            continue  # Do not hydrate cloud-only files.
                    except OSError:
                        result.errors += 1
                        continue
                    stem, ext = os.path.splitext(filename)
                    ext = ext.lower()
                    content = ''
                    pages = []
                    status = 'Nom et emplacement'
                    if ext == '.pdf':
                        if progress_cb: progress_cb(result.total_files, 'Lecture PDF : '+filename)
                        try:
                            if service is None: service = PdfService(cache_dir)
                            details = service.read(full_path,stop_flag,lambda page,total: progress_cb(result.total_files, f'{filename} — page {page}/{total}') if progress_cb else None)
                        except Exception as exc:
                            details = dict(pages=[],status='PDF inaccessible : '+type(exc).__name__,issues=[],ocr_pages=0)
                        pages = details['pages']
                        content = '\n\n'.join(page['text'] for page in pages)
                        status = details['status']
                        if content: result.pdf_read += 1
                        else: result.pdf_unread += 1
                        if details.get('ocr_pages'): result.pdf_ocr += 1
                        if details.get('issues') and content: result.pdf_partial += 1
                        if not content or details.get('issues'):
                            result.pdf_issues.append(dict(name=filename,path=full_path,status=status,details=details.get('issues',[])))
                    elif ext in EXT_IMAGES:
                        if progress_cb: progress_cb(result.total_files, 'Analyse visuelle : '+filename)
                        try:
                            if image_reader is None: image_reader = ImageReader(cache_dir)
                            tags = image_reader.read(full_path)
                            content = ' '.join(tags)
                            status = 'Analyse visuelle locale : '+(', '.join(t.split()[0] for t in tags) if tags else 'sujet non identifié')
                        except Exception:
                            status = 'Analyse visuelle indisponible pour cette image'
                    elif info.st_size <= MAX_CONTENT_READ_BYTES * 3:
                        content = extract_text_content(full_path,ext)
                        if content: status = 'Texte indexé'
                    entry = FileEntry(path=full_path,name=filename,stem=stem,ext=ext,
                        category=categorize(ext),size=info.st_size,badly_named=is_badly_named(stem),
                        content=content,content_lower=content.lower(),pages=pages,read_status=status)
                    result.entries.append(entry)
                    result.counts_by_category[entry.category] += 1
                    result.total_files += 1
                    result.total_size += entry.size
                    result.badly_named_count += int(entry.badly_named)
                    result.content_indexed_count += bool(content)
                    if info.st_size: size_index[(info.st_size,filename.lower())].append(full_path)
                    if progress_cb and (ext=='.pdf' or result.total_files%25==0): progress_cb(result.total_files,full_path)
        result.duplicates_count = sum(len(paths)-1 for paths in size_index.values() if len(paths)>1)
        result.cancelled = stop_flag.is_set()
        if progress_cb: progress_cb(result.total_files,'')
        return result
    finally:
        if service: service.close()
        if image_reader: image_reader.close()


# ---------------------------------------------------------------------------
# Recherche en langage courant
#
# La recherche combine plusieurs signaux pour se rapprocher d'une requête
# "comme on parle" plutôt que d'une simple correspondance exacte :
#   1. Mots du nom de fichier (poids fort, y compris correspondance floue
#      pour tolérer les fautes de frappe grâce à difflib)
#   2. Mots du CONTENU du fichier, quand celui-ci a pu être indexé
#      (documents Word/Excel/PowerPoint, texte, CSV, HTML...)
#   3. Mots du chemin / des dossiers parents
#   4. Synonymes usuels (facture ~ reçu, photo ~ image...)
#   5. Bonus si la requête entière apparaît telle quelle (nom ou contenu)
#
# Limite honnête : Retrio ne "regarde" pas l'intérieur d'une image ou d'une
# vidéo (reconnaître un objet, un logo, un visage sur une photo demande un
# modèle de vision par ordinateur, ce qui sort du cadre d'un petit outil
# 100% local et sans dépendance). Une image ne peut donc être retrouvée que
# par son nom de fichier, son dossier, ou — si Retrio en a l'occasion plus
# tard — un texte que l'utilisateur y aura associé lui-même (légende, nom
# de dossier explicite...).
# ---------------------------------------------------------------------------
SYNONYMS = {
    "facture": ["facture", "invoice", "reçu", "recu", "note"],
    "assurance": ["assurance", "contrat", "attestation", "police"],
    "photo": ["photo", "image", "img", "dsc", "photos"],
    "logo": ["logo", "marque", "icone", "icône", "brand"],
    "video": ["video", "vidéo", "film", "mov", "clip"],
    "musique": ["musique", "son", "audio", "mp3", "chanson"],
    "devis": ["devis", "estimation", "proposition", "offre"],
    "cv": ["cv", "curriculum", "resume", "candidature"],
    "impot": ["impot", "impôt", "taxe", "fiscal", "declaration"],
    "banque": ["banque", "releve", "relevé", "compte", "virement"],
    "contrat": ["contrat", "bail", "convention", "accord"],
    "carte": ["carte", "id", "identite", "identité", "passeport"],
}

STOPWORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "avec", "et", "ou",
    "sur", "dans", "pour", "mon", "ma", "mes", "au", "aux", "ce", "cette",
    "the", "a", "an", "with", "and", "or", "for", "of", "my",
}


def _tokenize(text: str) -> list:
    return re.findall(r"[a-zà-ÿ0-9]+", text.lower())


def expand_query(query: str) -> list:
    tokens = [t for t in _tokenize(query) if t not in STOPWORDS] or _tokenize(query)
    expanded = set(tokens)
    for token in tokens:
        for key, syns in SYNONYMS.items():
            if token == key or token in syns:
                expanded.update(syns)
                expanded.add(key)
    return list(expanded)


def _fuzzy_token_score(token: str, haystack_tokens: set) -> float:
    """Tolère les fautes de frappe / accords approximatifs : renvoie le
    meilleur score de similarité (0 à 1) entre `token` et les mots du texte
    comparé, via difflib (bibliothèque standard, pas d'IA)."""
    if not haystack_tokens:
        return 0.0
    best = 0.0
    for h in haystack_tokens:
        if abs(len(h) - len(token)) > 3:
            continue
        ratio = difflib.SequenceMatcher(None, token, h).ratio()
        if ratio > best:
            best = ratio
    return best


def search_entries(entries: list, query: str, limit: int = 60) -> list:
    return search_by_content(entries, query, limit)


def content_snippet(entry, query: str, radius: int = 60) -> str:
    return evidence(entry,query)['text']


# ---------------------------------------------------------------------------
# Couleurs utilisées pour les badges de type de fichier dans les résultats
# (identiques aux tokens CSS de app.css — voir --primary, --terracotta, etc.)
# ---------------------------------------------------------------------------
COL_BG = "#F5F1E6"
COL_PRIMARY = "#1B4332"
COL_GOLD = "#D9C185"
COL_TERRACOTTA = "#C9A187"
COL_TEXT_TERTIARY = "#5B7364"


def file_badge(entry) -> tuple:
    ext = entry.ext.lower()
    if ext == ".pdf":
        return "PDF", COL_PRIMARY
    if ext in (".doc", ".docx", ".odt", ".rtf"):
        return "DOCX", COL_TERRACOTTA
    if ext in (".xls", ".xlsx", ".csv", ".ods"):
        return "XLSX", COL_TERRACOTTA
    if ext in (".ppt", ".pptx", ".odp"):
        return "PPT", COL_TERRACOTTA
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff", ".svg"):
        return "JPG", COL_GOLD
    if ext in (".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".flv", ".webm"):
        return "VID", COL_TEXT_TERTIARY
    if ext in (".mp3", ".wav", ".flac", ".aac", ".m4a", ".wma", ".ogg"):
        return "AUD", COL_TEXT_TERTIARY
    label = ext.lstrip(".").upper()[:4] or "FILE"
    return label, COL_TEXT_TERTIARY


# ---------------------------------------------------------------------------
# Pont pywebview : expose la logique métier ci-dessus au JavaScript de
# app.html / app.js. AUCUNE logique métier n'est dupliquée ici — cette
# classe ne fait que sérialiser des dataclasses Python en JSON et router les
# appels ; le scan, la recherche, l'extraction de contenu restent exactement
# le code ci-dessus (identique à la version précédente de Retrio).
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self.window = None
        self.scan_result = ScanResult()
        self.type_filter = "tous"
        self._stop = threading.Event()
        self._scan_lock = threading.Lock()
        self._scanning = False

    def _run_js(self, code):
        try:
            if self.window is not None:
                self.window.evaluate_js(code)
        except Exception:
            pass

    # -- dossiers ----------------------------------------------------------
    def get_known_folders(self):
        return get_known_folders()

    def pick_folder(self):
        import webview
        try:
            result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            return None
        if result:
            return result[0]
        return None

    def pick_bug_attachments(self):
        import webview
        try:
            result = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.gif)", "Tous les fichiers (*.*)"),
            )
            return list(result or [])
        except Exception:
            return []

    def prepare_bug_report(self, area, message, attachments=None):
        """Create a local email draft with optional attachments; never upload data."""
        area = str(area or "Autre problème").strip()[:120]
        message = str(message or "").strip()[:12000]
        if not message:
            return {"ok": False, "error": "Décrivez le problème avant de préparer l’e-mail."}
        mail = EmailMessage()
        mail["To"] = "retrio.pro@gmail.com"
        mail["Subject"] = f"[Retrio bêta] Problème — {area}"
        mail.set_content(
            f"Bonjour,\n\nJe rencontre un problème avec Retrio.\n\n"
            f"Partie concernée : {area}\nVersion : {APP_VERSION}\n\n"
            f"Description :\n{message}\n\nMerci.\n"
        )
        added = 0
        for raw_path in list(attachments or [])[:5]:
            try:
                path = Path(str(raw_path))
                if not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
                    continue
                mime, _ = mimetypes.guess_type(path.name)
                maintype, subtype = (mime or "application/octet-stream").split("/", 1)
                mail.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
                added += 1
            except Exception:
                continue
        try:
            draft_dir = Path(tempfile.gettempdir()) / "Retrio" / "assistance"
            draft_dir.mkdir(parents=True, exist_ok=True)
            draft = draft_dir / "signalement-retrio.eml"
            draft.write_bytes(mail.as_bytes())
            os.startfile(str(draft))  # type: ignore[attr-defined]
            return {"ok": True, "attachments": added}
        except Exception:
            subject = urllib.parse.quote(str(mail["Subject"]))
            body = urllib.parse.quote(mail.get_body(preferencelist=("plain",)).get_content())
            webbrowser.open(f"mailto:retrio.pro@gmail.com?subject={subject}&body={body}")
            return {"ok": True, "attachments": 0}

    # -- analyse -------------------------------------------------------------
    def start_scan(self, roots):
        if not isinstance(roots,list) or not roots or not all(isinstance(r,str) and os.path.isabs(r) for r in roots):
            return False
        with self._scan_lock:
            if self._scanning: return False
            self._scanning = True
            self._stop.clear()
        threading.Thread(target=self._scan_worker,args=(roots,),daemon=True).start()
        return True

    def stop_scan(self):
        self._stop.set()
        return True

    def _scan_worker(self, roots):
        try:
            def progress_cb(n_files,current_path):
                self._run_js(f"window.onScanProgress({n_files}, {json.dumps(current_path)})")
            result = scan_folders(roots,progress_cb=progress_cb,stop_flag=self._stop)
            self.scan_result = result
            payload = dict(roots=roots,total_files=result.total_files,total_size_human=human_size(result.total_size),
                content_indexed_count=result.content_indexed_count,counts=dict(result.counts_by_category),
                pdf_read=result.pdf_read,pdf_ocr=result.pdf_ocr,pdf_unread=result.pdf_unread,
                pdf_partial=result.pdf_partial,errors=result.errors,cancelled=result.cancelled,
                pdf_issues=result.pdf_issues)
            self._run_js(f"window.onScanDone({json.dumps(json.dumps(payload))})")
        except Exception as exc:
            self._run_js(f"window.onScanError({json.dumps('Analyse interrompue : '+type(exc).__name__)})")
        finally:
            with self._scan_lock: self._scanning = False

    # -- recherche -----------------------------------------------------------
    def _filtered(self, entries, type_filter):
        if type_filter == "tous":
            return entries
        mapping = {"pdf": "pdf", "image": "images", "doc": "documents"}
        cat = mapping.get(type_filter)
        return [e for e in entries if e.category == cat]

    def minimize(self): self.window.minimize()
    def toggle_maximize(self):
        if getattr(self, '_maximized', False): self.window.restore()
        else: self.window.maximize()
        self._maximized = not getattr(self, '_maximized', False)
    def close_window(self):
        self._stop.set()
        self.window.destroy()

    def search(self, query, type_filter, folder=""):
        self.type_filter = type_filter or "tous"
        pool = self._filtered(self.scan_result.entries, self.type_filter)
        if folder:
            parent = os.path.normcase(os.path.abspath(folder))
            pool = [e for e in pool if os.path.normcase(os.path.abspath(e.path)).startswith(parent.rstrip(os.sep)+os.sep)]
        query = query or ""
        if self.type_filter == 'image':
            query = re.sub(r'\b(photos?|images?)\b', '', query, flags=re.I).strip()
        elif self.type_filter == 'pdf':
            query = re.sub(r'\bpdfs?\b', '', query, flags=re.I).strip()
        if query.strip():
            all_matches = search_entries(pool, query, limit=None)
            matches = all_matches[:60]
        else:
            all_matches = pool
            matches = pool[:60]

        if query.strip():
            count_label = f"{len(all_matches)} résultat(s) pour « {query} »"
        else:
            count_label = f"{len(all_matches)} fichier(s)" if matches else ""

        if len(all_matches)>60: count_label += " — 60 premiers affichés"
        match_dicts = []
        for entry in matches:
            badge_label, badge_color = file_badge(entry)
            proof = evidence(entry,query)
            match_dicts.append({
                "path": entry.path,
                "name": entry.name,
                "dir": os.path.dirname(entry.path),
                "size_human": human_size(entry.size),
                "badly_named": entry.badly_named,
                "badge_label": badge_label,
                "badge_color": badge_color,
                "snippet": proof["text"] if query else "",
                "page": proof["page"],
                "method": proof["method"],
                "read_status": entry.read_status,
            })
        return json.dumps({"matches": match_dicts, "count_label": count_label})

    # -- actions sur un fichier ------------------------------------------------
    def open_path(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass
        return True

    def open_folder(self, path):
        self.open_path(os.path.dirname(path))
        return True

    def copy_path(self, path):
        try:
            if sys.platform == "win32":
                subprocess.run(["clip"], input=path.encode("utf-16-le"), check=True)
            elif sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=path.encode("utf-8"), check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=path.encode("utf-8"), check=False)
        except Exception:
            pass
        return True


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def main():
    import webview

    if sys.platform == 'win32':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Retrio.Desktop')
    api = Api()
    html_path = resource_path("app.html")

    # Icône de la fenêtre : webview.start(icon=...) exige un vrai fichier
    # .ico (System.Drawing.Icon côté WebView2/.NET refuse un PNG). On
    # utilise le .ico déjà bundlé avec l'app (voir build_web.bat), avec un
    # repli silencieux si absent plutôt que de faire planter l'appli.
    icon_path = resource_path("icon.ico")
    if not os.path.isfile(icon_path):
        icon_path = None

    window = webview.create_window(
        APP_NAME,
        url=html_path,
        js_api=api,
        frameless=True,
        easy_drag=False,
        width=1220,
        height=800,
        min_size=(1000, 660),
        background_color="#F5F1E6",
    )
    api.window = window
    if icon_path:
        webview.start(gui="edgechromium", icon=icon_path)
    else:
        webview.start(gui="edgechromium")


def warmup():
    """Charge silencieusement les composants du démarrage pendant l'installation."""
    get_known_folders()
    import webview  # noqa: F401
    if sys.platform == "win32":
        try:
            import webview.platforms.edgechromium  # noqa: F401
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 2 and sys.argv[1] == "--warmup":
        sys.exit(warmup())
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from smoke_check import run
        sys.exit(run(sys.argv[2]))
    main()
