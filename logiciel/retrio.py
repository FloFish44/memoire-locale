#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrio — application Windows de recherche documentaire.

100% local : aucune analyse, aucun fichier et aucune requête n'est envoyé
sur Internet. Tout le traitement (parcours des dossiers, index, recherche)
se fait sur la machine de l'utilisateur.

Ne nécessite aucune dépendance externe : uniquement la bibliothèque
standard de Python (tkinter inclus). L'indexation de contenu (texte dans
les documents) et la recherche floue sont également 100% stdlib.

Lancer :   python retrio.py
Compiler : voir build_exe.bat (utilise PyInstaller)
"""

import base64
import csv
import ctypes
import difflib
import io
import json
import os
import queue
import re
import sys
import subprocess
import threading
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import Tk, Canvas, Frame, Label, StringVar, IntVar, BooleanVar, PhotoImage
from tkinter import ttk, filedialog

APP_NAME = "Retrio"
APP_VERSION = "0.3.0 (bêta)"

# ---------------------------------------------------------------------------
# Icône de l'application (PNG encodé en base64, intégré directement au
# script pour ne dépendre d'aucun fichier externe au runtime)
# ---------------------------------------------------------------------------
ICON_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAADeUlEQVR4nJ2XTW/cNhCGn6G0Wie2dxsHMFIgXvvUa3oK2l8R5B+kQH9sfWoK9FCgHyhQpAGKOKk/urJWIqcHSlotV5Tk8LDSjobvvJwZcoayWJ0qzZD6qZ336JBaMZwY0+ngdkRmR18DjBBvRxYqDipHRabve6sTemGSZ/p5aOCs5u8egen4n8Nkf/Yegfajsu/ZHZu68xizJsH/RmB2hL2GxsEn64W6AmmblX0J3As0ZlGneaUeaaPfwgb4qiCmxq2c1+3bdbLVN2lvZCMEmrnB/mxYiXjDkhjmJ0deMOQEq2xuc9Q6JDWd9I8RiMW+ZqXWMTt+xMnXF2SLx56jgHQYC1LzFVSV8nbN1ds/KW/WSJIwFBMzHC9FjPDkxTkHT49R58ApOA3eFbUOZyuctcyfHPH0xQUYM2jcE4gOv/r06IBseYjbVCCCGMGIkCQJxiSIGFQVVecBRXCbitnxI2bHB6h1DMVsuwv2dLTh4R3cyRFrLUWee5HCPMswxnRnIapIk61hfu0QaBR6PBByMSJUVcXyiyWr1YrKVjir/PHb75RlSZKmSJ10U3fitP1Sr0DrVZVFyavXr3j27EvOL8558/13GGNQ51BVnAvMawjWJRCj2nWAblGMGPL7nJubG/I85+rDBw4PDzFJgnVuG82oC3Y/pPvu76nzWsNq/a7g1PH87DlnZ2dc/nDJ9ad/WSyXfncAWp9wYwW0JwSRGl4bttayWCxI0xnv/37PTz++5eU3L1mdryiLTScJp1VvWZyfRpwlqLXMFo85/far+uAB5xzz+ZzZLEUVyrIkyzIqa8nXa78basv/XP5Kef0fkibREzEdIdguwamvWCJQFAX5fd6efPk6xxiDSUybrHsejIxhAuIPI3XecIMrIqQm9Seg+NNSUVwdf9Tr4Nxo9RzYhh64uisorm4x2YymOqn6UDiaPb+tCSgk8xnFxzvKu3vEDJxCUzyAKJ9+/gutHNnJUS3veKP92dpZv/vI9S/vBqFbE/Ek3A5VX3SSgyxoHHq6GFXs/aatG2NjPAmp45kItii7woZeh6nnMJT1IeFJBFr1ZkWN8bB/l6ZRnd6TjfQDkdHtIXv7s+lApvfy8SAG4ehrfyMQ9HngQfeNnivPVKD2XvDZF5zuSvs80q0EcSMjOTDRnVE9DZ59BHrBxgxEby087JYD/wNID45gGI7YLQAAAABJRU5ErkJggg=="

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
EXT_TEXT_READABLE = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm", ".ini", ".rtf"}
EXT_DOCX = {".docx"}
EXT_XLSX = {".xlsx"}
EXT_PPTX = {".pptx"}

# Taille max lue par fichier pour l'extraction de contenu (évite de passer
# un temps disproportionné sur d'énormes fichiers texte/logs).
MAX_CONTENT_READ_BYTES = 2_000_000
# Longueur max du contenu conservé en mémoire par fichier (index + aperçu).
MAX_CONTENT_KEEP_CHARS = 20_000

# Dossiers à ignorer pendant le parcours (dossiers système / techniques)
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "programdata",
    "program files", "program files (x86)", "node_modules", ".git", ".cache",
    "appdata",
}

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
        if ext == ".csv":
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


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["o", "Ko", "Mo", "Go", "To"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Po"


def scan_folders(roots: list, progress_cb=None, stop_flag: threading.Event = None) -> ScanResult:
    """Parcourt récursivement les dossiers sélectionnés, construit les stats
    et indexe le contenu texte des documents reconnus (voir extract_text_content).

    progress_cb(n_files, current_path) est appelé régulièrement pour permettre
    une mise à jour de l'interface pendant le scan (qui tourne dans un thread
    séparé pour ne jamais geler la fenêtre).
    """
    result = ScanResult()
    size_index: dict = defaultdict(list)  # taille -> liste de chemins (détection de doublons)

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if stop_flag is not None and stop_flag.is_set():
                return result

            # Élague les dossiers système / techniques pour rester rapide et pertinent
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIR_NAMES and not d.startswith(".")]

            for filename in filenames:
                if stop_flag is not None and stop_flag.is_set():
                    return result
                full_path = os.path.join(dirpath, filename)
                try:
                    stat = os.stat(full_path)
                except OSError:
                    result.errors += 1
                    continue

                stem, ext = os.path.splitext(filename)
                ext = ext.lower()
                category = categorize(ext)
                badly_named = is_badly_named(stem)

                content = ""
                # On ne tente l'extraction que sur des fichiers de taille
                # raisonnable, pour ne jamais bloquer l'analyse sur un très
                # gros fichier.
                if stat.st_size <= MAX_CONTENT_READ_BYTES * 3:
                    content = extract_text_content(full_path, ext)

                entry = FileEntry(
                    path=full_path,
                    name=filename,
                    stem=stem,
                    ext=ext,
                    category=category,
                    size=stat.st_size,
                    badly_named=badly_named,
                    content=content,
                    content_lower=content.lower(),
                )
                result.entries.append(entry)
                result.counts_by_category[category] += 1
                result.total_files += 1
                result.total_size += stat.st_size
                if badly_named:
                    result.badly_named_count += 1
                if content:
                    result.content_indexed_count += 1
                if stat.st_size > 0:
                    size_index[(stat.st_size, filename.lower())].append(full_path)

                if progress_cb and result.total_files % 25 == 0:
                    progress_cb(result.total_files, full_path)

    # Doublons potentiels : même taille + même nom de fichier dans des dossiers différents
    for key, paths in size_index.items():
        if len(paths) > 1:
            result.duplicates_count += len(paths) - 1

    if progress_cb:
        progress_cb(result.total_files, "")

    return result


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
    query = query.strip()
    if not query:
        return []
    tokens = expand_query(query)
    query_lower = query.lower()

    scored = []
    for entry in entries:
        name_lower = entry.name.lower()
        stem_tokens = set(_tokenize(entry.stem))
        path_lower = entry.path.lower()
        content_lower = entry.content_lower

        score = 0.0
        matched_any = False

        for t in tokens:
            if t in name_lower:
                score += 5
                matched_any = True
            elif _fuzzy_token_score(t, stem_tokens) >= 0.82:
                score += 3
                matched_any = True

            if content_lower and t in content_lower:
                score += 2
                matched_any = True

            if t in path_lower and t not in name_lower:
                score += 1
                matched_any = True

        # Bonus : la requête complète apparaît telle quelle
        if query_lower in name_lower:
            score += 8
            matched_any = True
        if content_lower and query_lower in content_lower:
            score += 6
            matched_any = True

        # Petit malus pour les fichiers dont le nom ne dit rien (on les
        # laisse remonter uniquement si le CONTENU correspond vraiment).
        if entry.badly_named and not (content_lower and any(t in content_lower for t in tokens)):
            score *= 0.85

        if matched_any and score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))
    return [e for _, e in scored[:limit]]


def content_snippet(entry, query: str, radius: int = 60) -> str:
    """Construit un court extrait du contenu autour du premier mot-clé
    trouvé, pour montrer à l'utilisateur POURQUOI ce fichier est remonté."""
    if not entry.content:
        return ""
    tokens = expand_query(query)
    lower = entry.content_lower
    best_pos = -1
    for t in tokens:
        pos = lower.find(t)
        if pos != -1 and (best_pos == -1 or pos < best_pos):
            best_pos = pos
    if best_pos == -1:
        return ""
    start = max(0, best_pos - radius)
    end = min(len(entry.content), best_pos + radius)
    snippet = entry.content[start:end].strip()
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(entry.content) else ""
    return f"{prefix}{snippet}{suffix}"

# ---------------------------------------------------------------------------
# Interface graphique — recréation du design de référence "Retrio App"
# (sidebar + contenu), identique à la charte du site web et de l'installateur.
# ---------------------------------------------------------------------------
import tkinter.font as tkfont

# -- Palette (identique au site Retrio et à l'installateur) -----------------
COL_BG = "#F5F1E6"
COL_CARD_CREAM = "#FBF8F0"
COL_WHITE = "#FFFFFF"
COL_PRIMARY = "#1B4332"
COL_PRIMARY_HOVER = "#2F6B4A"
COL_MINT = "#95D5B2"
COL_TEXT = "#14251C"
COL_TEXT_SECOND = "#4C5A50"
COL_TEXT_TERTIARY = "#5B7364"
COL_TEXT_DISABLED = "#9AA79E"
COL_BORDER = "#DED4BC"
COL_BORDER_BTN = "#C9BE9F"
COL_GOLD = "#D9C185"
COL_GOLD_TEXT = "#B8863F"
COL_TERRACOTTA = "#C9A187"
COL_NAV_ACTIVE_BG = "#E3E9E1"
COL_NAV_ICON_BG = "#F2EEE1"
COL_NAV_ICON_FG = "#7A8A80"
COL_BADGE_BG = "#EEE4CB"
COL_PRIVACY_BG = "#E9E8DC"
COL_BLUR_BAR = "#EEE8D8"

FONT_SERIF = "Fraunces"
FONT_SANS = "Inter"
FONT_MONO = "IBM Plex Mono"

SIDEBAR_WIDTH = 250


# ---------------------------------------------------------------------------
# Petits utilitaires de dessin (coins arrondis, icônes en CSS-like pur canvas)
# ---------------------------------------------------------------------------
def draw_round_rect(canvas, x1, y1, x2, y2, radius=10, **kwargs):
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def draw_icon(canvas, kind, color, cx, cy, size=15):
    """Dessine un petit pictogramme (aucune image bitmap, uniquement des
    primitives canvas), centré sur (cx, cy)."""
    s = size
    if kind == "search":
        r = s * 0.32
        canvas.create_oval(cx - r - 2, cy - r - 3, cx + r - 2, cy + r - 3, outline=color, width=1.6)
        canvas.create_line(cx + r * 0.4, cy + r * 0.4, cx + r + 3, cy + r + 4, fill=color, width=1.8, capstyle="round")
    elif kind == "duplicates":
        w = s * 0.62
        canvas.create_rectangle(cx - w / 2 + 3, cy - w / 2 - 2, cx + w / 2 + 3, cy + w / 2 - 2,
                                 outline=color, width=1.5)
        canvas.create_rectangle(cx - w / 2 - 3, cy - w / 2 + 2, cx + w / 2 - 3, cy + w / 2 + 2,
                                 outline=color, width=1.5, fill=COL_WHITE if kind else "")
    elif kind == "folder":
        w, h = s * 0.85, s * 0.62
        x0, y0 = cx - w / 2, cy - h / 2 + 2
        canvas.create_rectangle(x0, y0 - 3, x0 + w * 0.45, y0, outline=color, width=1.5)
        canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline=color, width=1.5)
    elif kind == "clean":
        w = s * 0.66
        canvas.create_rectangle(cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2, outline=color, width=1.5)
        canvas.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=color, outline="")
    elif kind == "lock":
        w, h = s * 0.55, s * 0.42
        x0, y0 = cx - w / 2, cy - h / 2 + 3
        canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline=color, width=1.3, fill=color)
        canvas.create_arc(cx - w / 2 + 1.5, y0 - h * 0.9, cx + w / 2 - 1.5, y0 + h * 0.3,
                           start=0, extent=180, style="arc", outline=color, width=1.3)
    elif kind == "shield":
        canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color, outline="")


def measure_text(text, family, size, weight="normal"):
    try:
        f = tkfont.Font(family=family, size=size, weight=weight)
        return f.measure(text)
    except Exception:
        return len(text) * (size - 1)


class CanvasButton:
    """Bouton pilule / rectangle arrondi dessiné en canvas (pas de bordure
    carrée ttk) — utilisé partout où le design impose un radius marqué."""

    def __init__(self, parent, text, command=None, width=None, height=44,
                 bg=COL_PRIMARY, fg=COL_WHITE, hover_bg=None, font=None,
                 radius=12, outline=None, surface_bg=COL_BG, padx=18, pill=False,
                 disabled_bg=None, disabled_fg=None):
        self.command = command
        self.bg = bg
        self.fg = fg
        self.hover_bg = hover_bg or bg
        self.outline = outline
        self.font = font or (FONT_SANS, 10, "bold")
        self.height = height
        self.disabled = False
        self.disabled_bg = disabled_bg or bg
        self.disabled_fg = disabled_fg or fg
        self.radius = (height / 2) if pill else radius
        self._text = text
        if width is None:
            width = measure_text(text, self.font[0], self.font[1],
                                  "bold" if len(self.font) > 2 and "bold" in self.font[2] else "normal") + padx * 2
        self.width = width
        self.canvas = Canvas(parent, width=self.width, height=self.height, bg=surface_bg,
                              highlightthickness=0, cursor="hand2")
        self._hover = False
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self._render()

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def grid(self, **kw):
        self.canvas.grid(**kw)
        return self

    def _render(self):
        c = self.canvas
        c.delete("all")
        if self.disabled:
            fill, fg = self.disabled_bg, self.disabled_fg
        else:
            fill = self.hover_bg if self._hover else self.bg
            fg = self.fg
        if self.outline:
            draw_round_rect(c, 1, 1, self.width - 1, self.height - 1, self.radius,
                             fill=fill, outline=self.outline, width=1.3)
        else:
            draw_round_rect(c, 0, 0, self.width, self.height, self.radius, fill=fill, outline="")
        c.create_text(self.width / 2, self.height / 2, text=self._text, fill=fg, font=self.font)

    def _on_enter(self, _e):
        self._hover = True
        self._render()

    def _on_leave(self, _e):
        self._hover = False
        self._render()

    def _on_click(self, _e):
        if not self.disabled and self.command:
            self.command()

    def set_text(self, text):
        self._text = text
        self._render()

    def set_disabled(self, disabled):
        self.disabled = disabled
        self.canvas.config(cursor="arrow" if disabled else "hand2")
        self._render()


class Chip(CanvasButton):
    """Chip pilule à deux états (actif / inactif) — filtres et suggestions."""

    def __init__(self, parent, text, command=None, active=False,
                 active_bg=COL_PRIMARY, active_fg=COL_WHITE,
                 inactive_bg=COL_WHITE, inactive_fg=COL_TEXT_SECOND,
                 outline=COL_BORDER, surface_bg=COL_BG, height=32, font=None):
        self.active = active
        self.active_bg = active_bg
        self.active_fg = active_fg
        self.inactive_bg = inactive_bg
        self.inactive_fg = inactive_fg
        font = font or (FONT_SANS, 9)
        super().__init__(parent, text, command=command, height=height,
                          bg=active_bg if active else inactive_bg,
                          fg=active_fg if active else inactive_fg,
                          font=font, pill=True, outline=None if active else outline,
                          surface_bg=surface_bg, padx=14)

    def _render(self):
        self.bg = self.active_bg if self.active else self.inactive_bg
        self.fg = self.active_fg if self.active else self.inactive_fg
        self.hover_bg = self.bg
        self.outline = None if self.active else COL_BORDER
        super()._render()

    def set_active(self, active):
        self.active = active
        self._render()

    def set_label(self, text, padx=14):
        self._text = text
        new_w = measure_text(text, self.font[0], self.font[1]) + padx * 2
        self.width = new_w
        self.canvas.config(width=new_w)
        self._render()


# ---------------------------------------------------------------------------
# Badges de type de fichier pour les résultats
# ---------------------------------------------------------------------------
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


LOCKED_TABS = {
    "doublons": {
        "label": "Doublons",
        "icon": "duplicates",
        "badge": "3 751",
        "title": "Libérez de l'espace en un clic.",
        "bullets": [
            "3 751 doublons potentiels détectés",
            "Comparaison par contenu (pas seulement le nom)",
            "Suppression groupée avec validation",
        ],
    },
    "ranger": {
        "label": "Ranger vos documents",
        "icon": "folder",
        "badge": "1 858",
        "title": "Un classement automatique, sans effort.",
        "bullets": [
            "1 858 fichiers mal nommés ou mal classés",
            "Suggestions de rangement par dossier",
            "Renommage intelligent en un clic",
        ],
    },
    "nettoyage": {
        "label": "Nettoyage",
        "icon": "clean",
        "badge": "3,7 Go",
        "title": "Libérez 3,7 Go d'espace disque.",
        "bullets": [
            "Fichiers temporaires et caches oubliés",
            "Doublons volumineux repérés",
            "Rien n'est supprimé sans accord",
        ],
    },
}


class RetrioApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1220x800")
        self.root.minsize(1000, 660)
        self.root.configure(bg=COL_BG)
        self._set_app_icon()

        self.known_folders = get_known_folders()
        self.folder_vars: dict = {}
        self.custom_folders: list = []

        self.scan_result: ScanResult = ScanResult()
        self.scan_thread = None
        self.stop_flag = threading.Event()
        self.ui_queue = queue.Queue()

        self.active_tab = "recherche"
        self.nav_items: dict = {}
        self.type_filter = "tous"
        self.filter_chips: dict = {}

        self._build_style()
        self._build_layout()
        self.root.after(100, self._poll_queue)

    # -- icône -----------------------------------------------------------
    def _set_app_icon(self):
        try:
            icon_img = PhotoImage(data=ICON_PNG_B64)
            self.root.iconphoto(True, icon_img)
            self._icon_img_ref = icon_img
        except Exception:
            pass

    # -- style (widgets ttk restants : entrée, scrollbar, progressbar) ---
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=COL_BG)
        style.configure("Sidebar.TFrame", background=COL_WHITE)
        style.configure("Card.TFrame", background=COL_WHITE)
        style.configure("CreamCard.TFrame", background=COL_CARD_CREAM)
        style.configure("TLabel", background=COL_BG, foreground=COL_TEXT, font=(FONT_SANS, 10))
        style.configure("Sidebar.TLabel", background=COL_WHITE, foreground=COL_TEXT, font=(FONT_SANS, 10))
        style.configure("Card.TLabel", background=COL_WHITE, foreground=COL_TEXT, font=(FONT_SANS, 10))
        style.configure("Muted.TLabel", background=COL_BG, foreground=COL_TEXT_TERTIARY, font=(FONT_SANS, 9))
        style.configure("SidebarMuted.TLabel", background=COL_WHITE, foreground=COL_TEXT_TERTIARY,
                         font=(FONT_SANS, 9))

        style.configure("Search.TEntry", fieldbackground=COL_WHITE, foreground=COL_TEXT,
                         bordercolor=COL_BORDER, lightcolor=COL_BORDER, darkcolor=COL_BORDER,
                         borderwidth=1.5, padding=10)
        style.map("Search.TEntry", bordercolor=[("focus", COL_PRIMARY_HOVER)])

        style.configure("TCheckbutton", background=COL_BG, foreground=COL_TEXT, font=(FONT_SANS, 9))
        style.configure("Horizontal.TProgressbar", troughcolor=COL_BORDER, background=COL_PRIMARY_HOVER,
                         bordercolor=COL_BG, lightcolor=COL_PRIMARY_HOVER, darkcolor=COL_PRIMARY_HOVER)

    # -- layout général : sidebar + contenu -------------------------------
    def _build_layout(self):
        outer = Frame(self.root, bg=COL_BG)
        outer.pack(fill="both", expand=True)

        self.sidebar = Frame(outer, bg=COL_WHITE, width=SIDEBAR_WIDTH,
                              highlightthickness=1, highlightbackground=COL_BORDER, highlightcolor=COL_BORDER)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar(self.sidebar)

        self.main_area = Frame(outer, bg=COL_BG)
        self.main_area.pack(side="left", fill="both", expand=True)
        self._build_main_area(self.main_area)

    # -- sidebar -----------------------------------------------------------
    def _build_sidebar(self, parent):
        pad = Frame(parent, bg=COL_WHITE)
        pad.pack(fill="both", expand=True, padx=16, pady=22)

        # Logo
        logo_row = Frame(pad, bg=COL_WHITE)
        logo_row.pack(fill="x")
        logo_c = Canvas(logo_row, width=34, height=34, bg=COL_WHITE, highlightthickness=0)
        logo_c.pack(side="left")
        draw_round_rect(logo_c, 0, 0, 34, 34, 9, fill=COL_PRIMARY, outline="")
        logo_c.create_text(17, 18, text="R", fill=COL_BG, font=(FONT_SERIF, 16, "bold"))
        logo_text = Frame(logo_row, bg=COL_WHITE)
        logo_text.pack(side="left", padx=(10, 0))
        Label(logo_text, text="Retrio", bg=COL_WHITE, fg=COL_TEXT, font=(FONT_SERIF, 12, "bold")).pack(anchor="w")
        Label(logo_text, text="Vos fichiers, en un instant", bg=COL_WHITE, fg=COL_TEXT_TERTIARY,
              font=(FONT_SANS, 8)).pack(anchor="w")

        # Navigation
        nav_frame = Frame(pad, bg=COL_WHITE)
        nav_frame.pack(fill="x", pady=(26, 0))
        self._add_nav_item(nav_frame, "recherche", "Recherche", "search", locked=False)
        for key in ("doublons", "ranger", "nettoyage"):
            info = LOCKED_TABS[key]
            self._add_nav_item(nav_frame, key, info["label"], info["icon"], locked=True, badge=info["badge"])

        # Spacer
        Frame(pad, bg=COL_WHITE).pack(fill="both", expand=True)

        # Bloc confidentialité
        priv = Frame(pad, bg=COL_PRIVACY_BG, highlightthickness=1, highlightbackground=COL_BORDER)
        priv.pack(fill="x", pady=(0, 10))
        priv_in = Frame(priv, bg=COL_PRIVACY_BG)
        priv_in.pack(fill="x", padx=14, pady=13)
        top_row = Frame(priv_in, bg=COL_PRIVACY_BG)
        top_row.pack(fill="x")
        dot = Canvas(top_row, width=9, height=9, bg=COL_PRIVACY_BG, highlightthickness=0)
        dot.pack(side="left")
        dot.create_oval(0, 0, 9, 9, fill="#2F6B4A", outline="")
        Label(top_row, text="Vos données restent ici.", bg=COL_PRIVACY_BG, fg=COL_TEXT,
              font=(FONT_SANS, 9, "bold")).pack(side="left", padx=(6, 0))
        Label(priv_in, text="Rien n'est envoyé sur Internet.", bg=COL_PRIVACY_BG, fg=COL_TEXT_TERTIARY,
              font=(FONT_SANS, 8)).pack(anchor="w", pady=(2, 0))

        # Carte upgrade Pro (dégradé approximé)
        pro_w = SIDEBAR_WIDTH - 32
        pro_c = Canvas(pad, width=pro_w, height=112, bg=COL_WHITE, highlightthickness=0)
        pro_c.pack(fill="x")
        self._draw_gradient_card(pro_c, pro_w, 112, COL_PRIMARY, COL_PRIMARY_HOVER, radius=12)
        pro_c.create_text(15, 24, text="Passer à Retrio Pro", anchor="w", fill=COL_BG,
                           font=(FONT_SERIF, 11, "bold"))
        pro_c.create_text(15, 46, text="Doublons, rangement automatique", anchor="w", fill=COL_MINT,
                           font=(FONT_SANS, 8))
        pro_c.create_text(15, 60, text="et plus encore.", anchor="w", fill=COL_MINT, font=(FONT_SANS, 8))
        btn_w, btn_h = pro_w - 24, 30
        draw_round_rect(pro_c, 12, 74, 12 + btn_w, 74 + btn_h, btn_h / 2, fill=COL_BG, outline="")
        pro_c.create_text(12 + btn_w / 2, 74 + btn_h / 2, text="Découvrir", fill=COL_TEXT,
                           font=(FONT_SANS, 9, "bold"))
        pro_c.tag_bind("all", "<Button-1>", lambda e: self.set_active_tab("doublons"))
        pro_c.config(cursor="hand2")

    def _draw_gradient_card(self, canvas, w, h, color_a, color_b, radius=12):
        ra, ga, ba = self._hex_to_rgb(color_a)
        rb, gb, bb = self._hex_to_rgb(color_b)
        steps = 40
        for i in range(steps):
            t = i / (steps - 1)
            r = int(ra + (rb - ra) * t)
            g = int(ga + (gb - ga) * t)
            b = int(ba + (bb - ba) * t)
            color = f"#{r:02x}{g:02x}{b:02x}"
            x0 = w * i / steps
            x1 = w * (i + 1) / steps + 1
            canvas.create_rectangle(x0, 0, x1, h, fill=color, outline=color)
        # masque les coins pour obtenir un rectangle arrondi malgré les bandes
        mask = COL_WHITE
        r = radius
        canvas.create_rectangle(0, 0, r, r, fill=mask, outline=mask)
        canvas.create_rectangle(w - r, 0, w, r, fill=mask, outline=mask)
        canvas.create_rectangle(0, h - r, r, h, fill=mask, outline=mask)
        canvas.create_rectangle(w - r, h - r, w, h, fill=mask, outline=mask)
        canvas.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90, fill=color_a, outline=color_a, style="pieslice")
        canvas.create_arc(w - 2 * r, 0, w, 2 * r, start=0, extent=90, fill=color_b, outline=color_b, style="pieslice")
        canvas.create_arc(0, h - 2 * r, 2 * r, h, start=180, extent=90, fill=color_a, outline=color_a, style="pieslice")
        canvas.create_arc(w - 2 * r, h - 2 * r, w, h, start=270, extent=90, fill=color_b, outline=color_b,
                           style="pieslice")

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    def _add_nav_item(self, parent, key, label, icon_kind, locked, badge=None):
        height = 52
        c = Canvas(parent, width=SIDEBAR_WIDTH - 32, height=height, bg=COL_WHITE,
                   highlightthickness=0, cursor="hand2")
        c.pack(fill="x", pady=3)
        self.nav_items[key] = {"canvas": c, "label": label, "icon": icon_kind, "locked": locked, "badge": badge}
        c.bind("<Button-1>", lambda e, k=key: self.set_active_tab(k))
        self._render_nav_item(key)

    def _render_nav_item(self, key):
        info = self.nav_items[key]
        c = info["canvas"]
        active = (self.active_tab == key)
        w = SIDEBAR_WIDTH - 32
        h = 52
        c.delete("all")
        if active:
            draw_round_rect(c, 0, 4, w, h - 4, 10, fill=COL_NAV_ACTIVE_BG, outline="")
        icon_bg = COL_PRIMARY if active else COL_NAV_ICON_BG
        icon_fg = COL_BG if active else COL_NAV_ICON_FG
        draw_round_rect(c, 10, h / 2 - 15, 10 + 30, h / 2 + 15, 8, fill=icon_bg, outline="")
        draw_icon(c, info["icon"], icon_fg, cx=25, cy=h / 2)

        text_y = h / 2 - (8 if info["locked"] and info["badge"] else 0)
        text_color = COL_PRIMARY if active else (COL_TEXT_TERTIARY if info["locked"] else "#3C4A40")
        c.create_text(50, text_y, text=info["label"], anchor="w", fill=text_color, font=(FONT_SANS, 9, "bold"))

        if info["locked"] and info["badge"]:
            by = h / 2 + 11
            badge_text = info["badge"]
            tw = measure_text(badge_text, FONT_MONO, 8)
            bw = tw + 26
            draw_round_rect(c, 50, by - 8, 50 + bw, by + 8, 8, fill=COL_BADGE_BG, outline="")
            c.create_text(56, by, text=badge_text, anchor="w", fill=COL_GOLD_TEXT, font=(FONT_MONO, 7))
            draw_icon(c, "lock", COL_TEXT_DISABLED, cx=50 + bw - 10, cy=by, size=9)

    def set_active_tab(self, key):
        self.active_tab = key
        for k in self.nav_items:
            self._render_nav_item(k)
        for k, frame in self.tab_frames.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

    # -- zone principale -----------------------------------------------------
    def _build_main_area(self, parent):
        content = Frame(parent, bg=COL_BG)
        content.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 0))

        header_pad = Frame(content, bg=COL_BG)
        header_pad.pack(fill="x", padx=36, pady=(30, 0))
        Label(header_pad, text="Bonjour !", bg=COL_BG, fg=COL_TEXT, font=(FONT_SERIF, 22, "bold")).pack(anchor="w")
        Label(header_pad, text="Retrouvez vos fichiers en un instant.", bg=COL_BG, fg=COL_TEXT_TERTIARY,
              font=(FONT_SANS, 10)).pack(anchor="w", pady=(2, 0))

        # -- panneau réglages / dossiers (repliable) --
        self.settings_visible = True
        toggle_row = Frame(content, bg=COL_BG)
        toggle_row.pack(fill="x", padx=36, pady=(14, 0))
        self.settings_toggle_btn = Label(toggle_row, text="▾ Dossiers à analyser / réglages", bg=COL_BG,
                                          fg=COL_TEXT_TERTIARY, font=(FONT_SANS, 9, "bold"), cursor="hand2")
        self.settings_toggle_btn.pack(anchor="w")
        self.settings_toggle_btn.bind("<Button-1>", lambda e: self._toggle_settings())

        self.settings_frame = Frame(content, bg=COL_CARD_CREAM, highlightthickness=1,
                                     highlightbackground=COL_BORDER)
        self.settings_frame.pack(fill="x", padx=36, pady=(8, 0))
        self._build_settings_panel(self.settings_frame)

        # -- cartes stats (toujours visibles, 4 cartes) --
        self.stats_row = Frame(content, bg=COL_BG)
        self.stats_row.pack(fill="x", padx=36, pady=(16, 0))
        self._build_stat_cards(self.stats_row)

        # -- zone à onglets --
        tabs_wrap = Frame(content, bg=COL_BG)
        tabs_wrap.pack(fill="both", expand=True, padx=36, pady=(18, 24))

        self.tab_frames = {}
        recherche_frame = Frame(tabs_wrap, bg=COL_BG)
        self.tab_frames["recherche"] = recherche_frame
        self._build_recherche_tab(recherche_frame)

        for key, info in LOCKED_TABS.items():
            f = Frame(tabs_wrap, bg=COL_BG)
            self.tab_frames[key] = f
            self._build_locked_tab(f, key, info)

        recherche_frame.pack(fill="both", expand=True)

    # -- panneau dossiers/réglages -------------------------------------------
    def _build_settings_panel(self, parent):
        inner = Frame(parent, bg=COL_CARD_CREAM)
        inner.pack(fill="x", padx=18, pady=16)

        Label(inner, text="Dossiers à analyser", bg=COL_CARD_CREAM, fg=COL_TEXT,
              font=(FONT_SANS, 9, "bold")).pack(anchor="w")

        chips_row = Frame(inner, bg=COL_CARD_CREAM)
        chips_row.pack(fill="x", pady=(8, 0))
        for label, path in self.known_folders.items():
            var = BooleanVar(value=label in ("Documents", "Téléchargements"))
            self.folder_vars[label] = (var, path)
            cb = ttk.Checkbutton(chips_row, text=label, variable=var)
            cb.pack(side="left", padx=(0, 16), pady=4)

        add_row = Frame(inner, bg=COL_CARD_CREAM)
        add_row.pack(fill="x", pady=(6, 0))
        CanvasButton(add_row, "+ Ajouter un autre dossier…", command=self._add_custom_folder,
                     height=32, bg=COL_WHITE, fg=COL_TEXT, hover_bg=COL_WHITE, outline=COL_BORDER_BTN,
                     surface_bg=COL_CARD_CREAM, radius=999, font=(FONT_SANS, 9)).pack(side="left")
        self.custom_folders_label = Label(add_row, text="", bg=COL_CARD_CREAM, fg=COL_TEXT_TERTIARY,
                                           font=(FONT_SANS, 8))
        self.custom_folders_label.pack(side="left", padx=10)

        action_row = Frame(inner, bg=COL_CARD_CREAM)
        action_row.pack(fill="x", pady=(12, 0))
        self.analyze_btn = CanvasButton(action_row, "▶  Analyse", command=self._on_analyze_click,
                                         height=38, bg=COL_PRIMARY, fg=COL_BG, hover_bg=COL_PRIMARY_HOVER,
                                         surface_bg=COL_CARD_CREAM, radius=10, font=(FONT_SANS, 10, "bold"))
        self.analyze_btn.pack(side="left")
        self.status_var = StringVar(value="Sélectionnez au moins un dossier, puis cliquez sur Analyse.")
        Label(action_row, textvariable=self.status_var, bg=COL_CARD_CREAM, fg=COL_TEXT_TERTIARY,
              font=(FONT_SANS, 9)).pack(side="left", padx=14)

        self.progress = ttk.Progressbar(inner, mode="indeterminate", style="Horizontal.TProgressbar")
        # empaqueté à la demande pendant le scan

    def _toggle_settings(self):
        self.settings_visible = not self.settings_visible
        if self.settings_visible:
            self.settings_frame.pack(fill="x", padx=36, pady=(8, 0), before=self.stats_row)
            self.settings_toggle_btn.config(text="▾ Dossiers à analyser / réglages")
        else:
            self.settings_frame.pack_forget()
            self.settings_toggle_btn.config(text="▸ Dossiers à analyser / réglages")

    # -- cartes statistiques (4, comme dans le design) -----------------------
    def _build_stat_cards(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        self.stat_widgets = {}
        cards = [
            ("total_files", "Fichiers analysés", "0", COL_PRIMARY),
            ("pdf", "PDF trouvés", "0", COL_GOLD),
            ("images", "Photos trouvées", "0", COL_TERRACOTTA),
            ("total_size", "Espace occupé", "0 o", COL_TEXT_TERTIARY),
        ]
        for i, (key, label, default, color) in enumerate(cards):
            card = Frame(parent, bg=COL_WHITE, highlightthickness=1, highlightbackground=COL_BORDER)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7, 0))
            parent.columnconfigure(i, weight=1)
            inner = Frame(card, bg=COL_WHITE)
            inner.pack(fill="both", expand=True, padx=16, pady=13)
            sq = Canvas(inner, width=26, height=26, bg=COL_WHITE, highlightthickness=0)
            sq.pack(anchor="w")
            draw_round_rect(sq, 0, 0, 26, 26, 7, fill=color, outline="")
            num_label = Label(inner, text=default, bg=COL_WHITE, fg=COL_TEXT, font=(FONT_SERIF, 17, "bold"))
            num_label.pack(anchor="w", pady=(6, 0))
            Label(inner, text=label, bg=COL_WHITE, fg=COL_TEXT_TERTIARY, font=(FONT_SANS, 8)).pack(anchor="w")
            self.stat_widgets[key] = num_label

    # -- onglet Recherche ------------------------------------------------------
    def _build_recherche_tab(self, parent):
        search_card = Frame(parent, bg=COL_BG)
        search_card.pack(fill="x")

        search_row = Frame(search_card, bg=COL_BG)
        search_row.pack(fill="x")
        self.search_var = StringVar()
        entry = ttk.Entry(search_row, textvariable=self.search_var, style="Search.TEntry",
                           font=(FONT_SANS, 12))
        entry.pack(side="left", fill="x", expand=True, ipady=10)
        entry.bind("<Return>", lambda e: self._run_search())
        CanvasButton(search_row, "Rechercher", command=self._run_search, height=48, bg=COL_PRIMARY,
                     fg=COL_BG, hover_bg=COL_PRIMARY_HOVER, radius=12, surface_bg=COL_BG,
                     font=(FONT_SANS, 10, "bold")).pack(side="left", padx=(10, 0))

        sugg_row = Frame(search_card, bg=COL_BG)
        sugg_row.pack(fill="x", pady=(10, 0))
        Label(sugg_row, text="Essayez :", bg=COL_BG, fg=COL_TEXT_TERTIARY, font=(FONT_SANS, 9)).pack(
            side="left", padx=(0, 8))
        for example in ["facture", "photo vacances", "devis", "assurance"]:
            Chip(sugg_row, example, command=lambda q=example: self._run_search(q), height=30,
                 inactive_bg=COL_WHITE, inactive_fg=COL_TEXT_SECOND, outline=COL_BORDER,
                 surface_bg=COL_BG).pack(side="left", padx=4)

        filter_row = Frame(search_card, bg=COL_BG)
        filter_row.pack(fill="x", pady=(10, 0))
        self.filter_row_parent = filter_row
        self.filter_chips = {}
        for key, label in (("tous", "Tous"), ("pdf", "PDF"), ("image", "Images"), ("doc", "Documents")):
            chip = Chip(filter_row, f"{label} (0)", command=lambda k=key: self._set_type_filter(k),
                        active=(key == "tous"), surface_bg=COL_BG)
            chip.pack(side="left", padx=(0, 6))
            self.filter_chips[key] = chip

        self.results_count_var = StringVar(value="")
        Label(parent, textvariable=self.results_count_var, bg=COL_BG, fg=COL_TEXT_TERTIARY,
              font=(FONT_SANS, 9)).pack(anchor="w", pady=(14, 0))

        canvas_frame = Frame(parent, bg=COL_BG)
        canvas_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.results_canvas = Canvas(canvas_frame, bg=COL_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.results_canvas.yview)
        self.results_list_frame = Frame(self.results_canvas, bg=COL_BG)
        self.results_list_frame.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all")),
        )
        self.results_canvas.create_window((0, 0), window=self.results_list_frame, anchor="nw")
        self.results_canvas.configure(yscrollcommand=scrollbar.set)
        self.results_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.results_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        try:
            self.results_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    # -- onglets verrouillés (Doublons / Ranger / Nettoyage) ------------------
    def _build_locked_tab(self, parent, key, info):
        bg_canvas = Canvas(parent, bg=COL_BG, highlightthickness=0)
        bg_canvas.pack(fill="both", expand=True)

        def redraw_blur(event=None):
            bg_canvas.delete("blur")
            w = bg_canvas.winfo_width() or 900
            h = bg_canvas.winfo_height() or 420
            y = 20
            while y < h - 20:
                draw_round_rect(bg_canvas, 20, y, w - 20, y + 46, 14, fill=COL_BLUR_BAR, outline="", tags="blur")
                y += 60
            self._draw_upsell_card(bg_canvas, w, h, key, info)

        bg_canvas.bind("<Configure>", redraw_blur)

    def _draw_upsell_card(self, canvas, w, h, key, info):
        canvas.delete("upsell")
        card_w = min(440, w - 60)
        card_h = 300
        x0 = (w - card_w) / 2
        y0 = max(20, (h - card_h) / 2)
        draw_round_rect(canvas, x0, y0, x0 + card_w, y0 + card_h, 18, fill=COL_WHITE, outline="", tags="upsell")

        icon_sq = 46
        icx = x0 + 30
        icy = y0 + 30
        draw_round_rect(canvas, icx, icy, icx + icon_sq, icy + icon_sq, 12, fill=COL_BADGE_BG, outline="",
                         tags="upsell")
        draw_icon(canvas, "lock", COL_GOLD_TEXT, cx=icx + icon_sq / 2, cy=icy + icon_sq / 2, size=18)

        canvas.create_text(x0 + 30, icy + icon_sq + 26, text=info["title"], anchor="nw", fill=COL_TEXT,
                            font=(FONT_SERIF, 14, "bold"), width=card_w - 60, tags="upsell")

        by = icy + icon_sq + 78
        for bullet in info["bullets"]:
            canvas.create_oval(x0 + 30, by + 4, x0 + 36, by + 10, fill="#2F6B4A", outline="", tags="upsell")
            canvas.create_text(x0 + 46, by, text=bullet, anchor="nw", fill=COL_TEXT_SECOND,
                                font=(FONT_SANS, 9), width=card_w - 76, tags="upsell")
            by += 34

        btn_w, btn_h = card_w - 60, 44
        bx, byy = x0 + 30, y0 + card_h - btn_h - 24
        self._draw_gradient_pill(canvas, bx, byy, btn_w, btn_h, COL_PRIMARY, COL_PRIMARY_HOVER, tags="upsell")
        canvas.create_text(bx + btn_w / 2, byy + btn_h / 2, text="Débloquer avec Retrio Pro", fill=COL_BG,
                            font=(FONT_SANS, 10, "bold"), tags="upsell")
        canvas.tag_bind("upsell", "<Enter>", lambda e: canvas.config(cursor="hand2"))
        canvas.tag_bind("upsell", "<Leave>", lambda e: canvas.config(cursor="arrow"))

    def _draw_gradient_pill(self, canvas, x, y, w, h, color_a, color_b, tags=""):
        ra, ga, ba = self._hex_to_rgb(color_a)
        rb, gb, bb = self._hex_to_rgb(color_b)
        steps = 30
        r = h / 2
        for i in range(steps):
            t = i / (steps - 1)
            cr = int(ra + (rb - ra) * t)
            cg = int(ga + (gb - ga) * t)
            cb = int(ba + (bb - ba) * t)
            color = f"#{cr:02x}{cg:02x}{cb:02x}"
            sx0 = x + w * i / steps
            sx1 = x + w * (i + 1) / steps + 1
            canvas.create_rectangle(sx0, y, sx1, y + h, fill=color, outline=color, tags=tags)
        canvas.create_oval(x, y, x + h, y + h, fill=color_a, outline=color_a, tags=tags)
        canvas.create_oval(x + w - h, y, x + w, y + h, fill=color_b, outline=color_b, tags=tags)
        canvas.create_rectangle(x, y, x + h / 2, y + h, fill=color_a, outline=color_a, tags=tags)
        canvas.create_rectangle(x + w - h / 2, y, x + w, y + h, fill=color_b, outline=color_b, tags=tags)

    # -- actions ---------------------------------------------------------------
    def _add_custom_folder(self):
        path = filedialog.askdirectory(title="Choisir un dossier à analyser")
        if path:
            self.custom_folders.append(path)
            self.custom_folders_label.config(
                text=f"{len(self.custom_folders)} dossier(s) personnalisé(s) ajouté(s)"
            )

    def _selected_roots(self) -> list:
        roots = [path for (var, path) in self.folder_vars.values() if var.get()]
        roots += self.custom_folders
        return list(dict.fromkeys(roots))

    def _on_analyze_click(self):
        if self.scan_thread and self.scan_thread.is_alive():
            return
        roots = self._selected_roots()
        if not roots:
            self.status_var.set("Sélectionnez au moins un dossier avant de lancer l'analyse.")
            return

        self.analyze_btn.set_disabled(True)
        self.analyze_btn.set_text("Analyse en cours…")
        self.progress.pack(fill="x", pady=(10, 0))
        self.progress.start(12)
        self.status_var.set("Analyse en cours (lecture du contenu des documents)…")
        self.stop_flag = threading.Event()

        def progress_cb(n_files, current_path):
            self.ui_queue.put(("progress", n_files, current_path))

        def worker():
            result = scan_folders(roots, progress_cb=progress_cb, stop_flag=self.stop_flag)
            self.ui_queue.put(("done", result))

        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def _poll_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                if msg[0] == "progress":
                    _, n_files, current_path = msg
                    shown = current_path if len(current_path) < 60 else "…" + current_path[-57:]
                    self.status_var.set(f"{n_files} fichiers analysés — {shown}")
                elif msg[0] == "done":
                    self._on_scan_done(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_scan_done(self, result: ScanResult):
        self.scan_result = result
        self.progress.stop()
        self.progress.pack_forget()
        self.analyze_btn.set_disabled(False)
        self.analyze_btn.set_text("▶  Relancer l'analyse")
        self.status_var.set(
            f"Analyse terminée : {result.total_files} fichiers, {human_size(result.total_size)} "
            f"— {result.content_indexed_count} fichiers indexés en contenu."
        )

        self.stat_widgets["total_files"].config(text=str(result.total_files))
        self.stat_widgets["pdf"].config(text=str(result.counts_by_category.get("pdf", 0)))
        self.stat_widgets["images"].config(text=str(result.counts_by_category.get("images", 0)))
        self.stat_widgets["total_size"].config(text=human_size(result.total_size))

        # Compteurs des chips de filtre (dérivés du jeu complet, pas du filtré)
        n_pdf = result.counts_by_category.get("pdf", 0)
        n_img = result.counts_by_category.get("images", 0)
        n_doc = result.counts_by_category.get("documents", 0)
        self.filter_chips["tous"].set_label(f"Tous ({result.total_files})")
        self.filter_chips["pdf"].set_label(f"PDF ({n_pdf})")
        self.filter_chips["image"].set_label(f"Images ({n_img})")
        self.filter_chips["doc"].set_label(f"Documents ({n_doc})")

        # Replie automatiquement le panneau de réglages une fois l'analyse
        # faite, pour laisser toute la place à la recherche — et relance la
        # recherche en cours s'il y en a une.
        if self.settings_visible:
            self._toggle_settings()
        if self.search_var.get().strip():
            self._run_search()

    def _set_type_filter(self, key):
        self.type_filter = key
        for k, chip in self.filter_chips.items():
            chip.set_active(k == key)
        self._run_search()

    def _filtered_category_entries(self, entries):
        if self.type_filter == "tous":
            return entries
        mapping = {"pdf": "pdf", "image": "images", "doc": "documents"}
        cat = mapping.get(self.type_filter)
        return [e for e in entries if e.category == cat]

    def _run_search(self, query: str = None):
        if query is None:
            query = self.search_var.get()
        else:
            self.search_var.set(query)

        if not self.scan_result.entries:
            self.results_count_var.set("Lancez d'abord une analyse pour pouvoir rechercher.")
            self._render_results([], query)
            return

        pool = self._filtered_category_entries(self.scan_result.entries)
        if query.strip():
            matches = search_entries(pool, query)
        else:
            matches = pool[:60]

        self.results_count_var.set(
            f"{len(matches)} résultat(s) pour « {query} »" if query.strip() else
            (f"{len(matches)} fichier(s)" if matches else "")
        )
        self._render_results(matches, query)

    def _render_results(self, matches: list, query: str = ""):
        for widget in self.results_list_frame.winfo_children():
            widget.destroy()

        if not matches:
            msg = f"Aucun résultat pour « {query} »." if query.strip() else "Lancez une recherche pour voir vos fichiers."
            Label(self.results_list_frame, text=msg, bg=COL_BG, fg=COL_TEXT_DISABLED,
                  font=(FONT_SANS, 10)).pack(anchor="w", pady=20)
            return

        for entry in matches:
            row = Frame(self.results_list_frame, bg=COL_WHITE, highlightthickness=1,
                        highlightbackground=COL_BORDER)
            row.pack(fill="x", pady=5)
            row_in = Frame(row, bg=COL_WHITE)
            row_in.pack(fill="x", padx=18, pady=14)

            badge_label, badge_color = file_badge(entry)
            badge_c = Canvas(row_in, width=42, height=42, bg=COL_WHITE, highlightthickness=0)
            badge_c.grid(row=0, column=0, rowspan=3, sticky="n")
            draw_round_rect(badge_c, 0, 0, 42, 42, 10, fill=badge_color, outline="")
            badge_c.create_text(21, 21, text=badge_label, fill=COL_BG, font=(FONT_MONO, 8, "bold"))

            text_col = Frame(row_in, bg=COL_WHITE)
            text_col.grid(row=0, column=1, sticky="w", padx=(14, 0))
            row_in.columnconfigure(1, weight=1)

            title_row = Frame(text_col, bg=COL_WHITE)
            title_row.pack(fill="x", anchor="w")
            Label(title_row, text=entry.name, bg=COL_WHITE, fg=COL_TEXT,
                  font=(FONT_SANS, 10, "bold")).pack(side="left")
            if entry.badly_named:
                Label(title_row, text="  nom peu explicite", bg=COL_WHITE, fg=COL_GOLD_TEXT,
                      font=(FONT_SANS, 7, "bold")).pack(side="left")

            snippet = content_snippet(entry, query) if query else ""
            if snippet:
                Label(text_col, text=f"« {snippet} »", bg=COL_WHITE, fg=COL_TEXT_SECOND,
                      font=(FONT_SANS, 9), wraplength=760, justify="left").pack(anchor="w", pady=(3, 0))

            meta = f"{os.path.dirname(entry.path)}  ·  {human_size(entry.size)}"
            Label(text_col, text=meta, bg=COL_WHITE, fg="#7A7161", font=(FONT_MONO, 8)).pack(anchor="w",
                                                                                               pady=(4, 0))

            btn_row = Frame(text_col, bg=COL_WHITE)
            btn_row.pack(anchor="w", pady=(8, 0))
            CanvasButton(btn_row, "Ouvrir", command=lambda p=entry.path: self._open_path(p), height=28,
                         bg=COL_WHITE, fg=COL_TEXT_SECOND, hover_bg=COL_WHITE, outline=COL_BORDER_BTN,
                         surface_bg=COL_WHITE, radius=999, font=(FONT_SANS, 8, "bold")).pack(side="left",
                                                                                              padx=(0, 6))
            CanvasButton(btn_row, "Dossier", command=lambda p=entry.path: self._open_folder(p), height=28,
                         bg=COL_WHITE, fg=COL_TEXT_SECOND, hover_bg=COL_WHITE, outline=COL_BORDER_BTN,
                         surface_bg=COL_WHITE, radius=999, font=(FONT_SANS, 8, "bold")).pack(side="left",
                                                                                              padx=(0, 6))
            CanvasButton(btn_row, "Copier le chemin", command=lambda p=entry.path: self._copy_path(p), height=28,
                         bg=COL_WHITE, fg=COL_TEXT_SECOND, hover_bg=COL_WHITE, outline=COL_BORDER_BTN,
                         surface_bg=COL_WHITE, radius=999, font=(FONT_SANS, 8, "bold")).pack(side="left")

    def _open_path(self, path: str):
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as exc:
            self.status_var.set(f"Impossible d'ouvrir le fichier ({exc}).")

    def _open_folder(self, path: str):
        folder = os.path.dirname(path)
        self._open_path(folder)

    def _copy_path(self, path: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.status_var.set("Chemin copié dans le presse-papiers.")


def main():
    root = Tk()
    RetrioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
