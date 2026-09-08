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
from tkinter import Tk, Canvas, StringVar, IntVar, BooleanVar, PhotoImage
from tkinter import ttk, filedialog

APP_NAME = "Retrio"
APP_VERSION = "0.2.0 (bêta)"

# ---------------------------------------------------------------------------
# Icône de l'application (PNG encodé en base64, intégré directement au
# script pour ne dépendre d'aucun fichier externe au runtime)
# ---------------------------------------------------------------------------
ICON_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAADeUlEQVR4nJ2XTW/cNhCGn6G0Wie2dxsHMFIgXvvUa3oK2l8R5B+kQH9sfWoK9FCgHyhQpAGKOKk/urJWIqcHSlotV5Tk8LDSjobvvJwZcoayWJ0qzZD6qZ336JBaMZwY0+ngdkRmR18DjBBvRxYqDipHRabve6sTemGSZ/p5aOCs5u8egen4n8Nkf/Yegfajsu/ZHZu68xizJsH/RmB2hL2GxsEn64W6AmmblX0J3As0ZlGneaUeaaPfwgb4qiCmxq2c1+3bdbLVN2lvZCMEmrnB/mxYiXjDkhjmJ0deMOQEq2xuc9Q6JDWd9I8RiMW+ZqXWMTt+xMnXF2SLx56jgHQYC1LzFVSV8nbN1ds/KW/WSJIwFBMzHC9FjPDkxTkHT49R58ApOA3eFbUOZyuctcyfHPH0xQUYM2jcE4gOv/r06IBseYjbVCCCGMGIkCQJxiSIGFQVVecBRXCbitnxI2bHB6h1DMVsuwv2dLTh4R3cyRFrLUWee5HCPMswxnRnIapIk61hfu0QaBR6PBByMSJUVcXyiyWr1YrKVjir/PHb75RlSZKmSJ10U3fitP1Sr0DrVZVFyavXr3j27EvOL8558/13GGNQ51BVnAvMawjWJRCj2nWAblGMGPL7nJubG/I85+rDBw4PDzFJgnVuG82oC3Y/pPvu76nzWsNq/a7g1PH87DlnZ2dc/nDJ9ad/WSyXfncAWp9wYwW0JwSRGl4bttayWCxI0xnv/37PTz++5eU3L1mdryiLTScJp1VvWZyfRpwlqLXMFo85/far+uAB5xzz+ZzZLEUVyrIkyzIqa8nXa78basv/XP5Kef0fkibREzEdIdguwamvWCJQFAX5fd6efPk6xxiDSUybrHsejIxhAuIPI3XecIMrIqQm9Seg+NNSUVwdf9Tr4Nxo9RzYhh64uisorm4x2YymOqn6UDiaPb+tCSgk8xnFxzvKu3vEDJxCUzyAKJ9+/gutHNnJUS3veKP92dpZv/vI9S/vBqFbE/Ek3A5VX3SSgyxoHHq6GFXs/aatG2NjPAmp45kItii7woZeh6nnMJT1IeFJBFr1ZkWN8bB/l6ZRnd6TjfQDkdHtIXv7s+lApvfy8SAG4ehrfyMQ9HngQfeNnivPVKD2XvDZF5zuSvs80q0EcSMjOTDRnVE9DZ59BHrBxgxEby087JYD/wNID45gGI7YLQAAAABJRU5ErkJggg=="

# ---------------------------------------------------------------------------
# Palette (reprend les couleurs du site)
# ---------------------------------------------------------------------------
COLOR_BG = "#F7F5F0"
COLOR_BG_CARD = "#FFFFFF"
COLOR_PRIMARY = "#1B4332"       # vert sapin (fond boutons principaux)
COLOR_PRIMARY_DARK = "#0E2A1D"
COLOR_ACCENT = "#40916C"        # vert moyen (highlights, liens)
COLOR_ACCENT_LIGHT = "#95D5B2"  # vert clair (badges)
COLOR_WARM = "#E07A5F"          # touche corail pour les alertes / doublons
COLOR_GOLD = "#D9A441"          # touche dorée pour les stats importantes
COLOR_TEXT = "#1B1B1B"
COLOR_TEXT_MUTED = "#6B7280"
COLOR_BORDER = "#E5E2D9"

FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else "Helvetica"

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
# Interface graphique
# ---------------------------------------------------------------------------
CATEGORY_ICONS = {
    "pdf": "📄",
    "images": "🖼",
    "videos": "🎬",
    "audio": "🎵",
    "documents": "📝",
    "archives": "🗜",
    "autres": "📁",
}


class RetrioApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x780")
        self.root.minsize(980, 640)
        self.root.configure(bg=COLOR_BG)
        self._set_app_icon()

        self.known_folders = get_known_folders()
        self.folder_vars: dict = {}
        self.custom_folders: list = []

        self.scan_result: ScanResult = ScanResult()
        self.scan_thread = None
        self.stop_flag = threading.Event()
        self.ui_queue = queue.Queue()

        self._build_style()
        self._build_layout()
        self.root.after(100, self._poll_queue)

    # -- icône ---------------------------------------------------------------
    def _set_app_icon(self):
        """Applique le logo Retrio comme icône de fenêtre (barre des tâches,
        barre de titre). L'icône est embarquée en base64 dans le script :
        aucun fichier externe n'est nécessaire au lancement."""
        try:
            icon_img = PhotoImage(data=ICON_PNG_B64)
            self.root.iconphoto(True, icon_img)
            self._icon_img_ref = icon_img  # évite le garbage-collection
        except Exception:
            pass

    # -- style -------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Card.TFrame", background=COLOR_BG_CARD)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10))
        style.configure("Card.TLabel", background=COLOR_BG_CARD, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10))
        style.configure("Title.TLabel", background=COLOR_BG, foreground=COLOR_PRIMARY_DARK,
                         font=(FONT_FAMILY, 20, "bold"))
        style.configure("Subtitle.TLabel", background=COLOR_BG, foreground=COLOR_TEXT_MUTED,
                         font=(FONT_FAMILY, 10))
        style.configure("StatNumber.TLabel", background=COLOR_BG_CARD, foreground=COLOR_PRIMARY_DARK,
                         font=(FONT_FAMILY, 24, "bold"))
        style.configure("StatLabel.TLabel", background=COLOR_BG_CARD, foreground=COLOR_TEXT_MUTED,
                         font=(FONT_FAMILY, 9))

        style.configure("Primary.TButton", background=COLOR_PRIMARY, foreground="white",
                         font=(FONT_FAMILY, 11, "bold"), padding=(18, 10), borderwidth=0)
        style.map("Primary.TButton", background=[("active", COLOR_PRIMARY_DARK), ("disabled", "#A9B8AE")])

        style.configure("Chip.TButton", background="#EFEDE6", foreground=COLOR_TEXT,
                         font=(FONT_FAMILY, 9), padding=(10, 5), borderwidth=0)
        style.map("Chip.TButton", background=[("active", COLOR_ACCENT_LIGHT)])

        style.configure("Ghost.TButton", background=COLOR_BG_CARD, foreground=COLOR_ACCENT,
                         font=(FONT_FAMILY, 9, "bold"), padding=(8, 4), borderwidth=1)

        style.configure("TCheckbutton", background=COLOR_BG, foreground=COLOR_TEXT, font=(FONT_FAMILY, 10))
        style.configure("Horizontal.TProgressbar", troughcolor="#E5E2D9", background=COLOR_ACCENT,
                         bordercolor=COLOR_BG, lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT)

    # -- layout --------------------------------------------------------------
    def _build_layout(self):
        header = ttk.Frame(self.root, padding=(28, 22, 28, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Retrio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Sélectionnez vos dossiers, lancez l'analyse, puis retrouvez vos fichiers en quelques mots. "
                 "Tout reste sur cet ordinateur.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        # --- Sélection des dossiers ---
        folders_frame = ttk.Frame(self.root, padding=(28, 4, 28, 4))
        folders_frame.pack(fill="x")
        ttk.Label(folders_frame, text="Dossiers à analyser", style="TLabel",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w", pady=(0, 6))

        chips_row = ttk.Frame(folders_frame)
        chips_row.pack(fill="x")
        for label, path in self.known_folders.items():
            var = BooleanVar(value=label in ("Documents", "Téléchargements"))
            self.folder_vars[label] = (var, path)
            cb = ttk.Checkbutton(chips_row, text=f"{label}", variable=var)
            cb.pack(side="left", padx=(0, 16), pady=4)

        add_row = ttk.Frame(folders_frame)
        add_row.pack(fill="x", pady=(4, 0))
        ttk.Button(add_row, text="+ Ajouter un autre dossier…", style="Ghost.TButton",
                   command=self._add_custom_folder).pack(side="left")
        self.custom_folders_label = ttk.Label(add_row, text="", style="Subtitle.TLabel")
        self.custom_folders_label.pack(side="left", padx=10)

        # --- Bouton Analyse + progression ---
        action_frame = ttk.Frame(self.root, padding=(28, 12, 28, 6))
        action_frame.pack(fill="x")
        self.analyze_btn = ttk.Button(action_frame, text="▶  Analyse", style="Primary.TButton",
                                       command=self._on_analyze_click)
        self.analyze_btn.pack(side="left")
        self.status_var = StringVar(value="Sélectionnez au moins un dossier, puis cliquez sur Analyse.")
        ttk.Label(action_frame, textvariable=self.status_var, style="TLabel").pack(side="left", padx=16)

        self.progress = ttk.Progressbar(self.root, mode="indeterminate", style="Horizontal.TProgressbar")
        # packed on demand during scan

        # --- Stats ---
        self.stats_frame = ttk.Frame(self.root, padding=(28, 10, 28, 6))
        self.stats_frame.pack(fill="x")
        self.stat_widgets = {}
        self._build_stat_cards()

        # --- Recherche ---
        search_frame = ttk.Frame(self.root, padding=(28, 14, 28, 6))
        search_frame.pack(fill="x")
        ttk.Label(search_frame, text="Que recherchez-vous ?", style="TLabel",
                  font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")

        search_row = ttk.Frame(search_frame)
        search_row.pack(fill="x", pady=(6, 0))
        self.search_var = StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var, font=(FONT_FAMILY, 12))
        search_entry.pack(side="left", fill="x", expand=True, ipady=6)
        search_entry.bind("<Return>", lambda e: self._run_search())
        ttk.Button(search_row, text="Rechercher", style="Primary.TButton",
                   command=self._run_search).pack(side="left", padx=(10, 0))

        examples_row = ttk.Frame(search_frame)
        examples_row.pack(fill="x", pady=(8, 0))
        ttk.Label(examples_row, text="Essayez :", style="Subtitle.TLabel").pack(side="left", padx=(0, 8))
        for example in ["facture", "photo vacances", "devis", "assurance", "musique"]:
            ttk.Button(examples_row, text=example, style="Chip.TButton",
                       command=lambda q=example: self._run_search(q)).pack(side="left", padx=4)

        # --- Résultats ---
        results_outer = ttk.Frame(self.root, padding=(28, 10, 28, 20))
        results_outer.pack(fill="both", expand=True)
        self.results_count_var = StringVar(value="")
        ttk.Label(results_outer, textvariable=self.results_count_var, style="Subtitle.TLabel").pack(anchor="w")

        canvas_frame = ttk.Frame(results_outer)
        canvas_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.results_canvas = Canvas(canvas_frame, bg=COLOR_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.results_canvas.yview)
        self.results_list_frame = ttk.Frame(self.results_canvas)
        self.results_list_frame.bind(
            "<Configure>",
            lambda e: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all")),
        )
        self.results_canvas.create_window((0, 0), window=self.results_list_frame, anchor="nw")
        self.results_canvas.configure(yscrollcommand=scrollbar.set)
        self.results_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_stat_cards(self):
        for widget in self.stats_frame.winfo_children():
            widget.destroy()
        self.stat_widgets = {}

        cards = [
            ("total_files", "Fichiers analysés", "0"),
            ("pdf", "PDF trouvés", "0"),
            ("images", "Photos trouvées", "0"),
            ("videos", "Vidéos trouvées", "0"),
            ("audio", "Fichiers audio", "0"),
            ("content_indexed", "Fichiers indexés (contenu)", "0"),
            ("duplicates", "Doublons potentiels", "0"),
            ("badly_named", "Fichiers mal nommés", "0"),
            ("total_size", "Espace occupé", "0 o"),
        ]
        for i, (key, label, default) in enumerate(cards):
            card = ttk.Frame(self.stats_frame, style="Card.TFrame", padding=(16, 12))
            card.grid(row=i // 4, column=i % 4, sticky="nsew", padx=6, pady=6)
            self.stats_frame.columnconfigure(i % 4, weight=1)
            num_label = ttk.Label(card, text=default, style="StatNumber.TLabel")
            num_label.pack(anchor="w")
            ttk.Label(card, text=label, style="StatLabel.TLabel").pack(anchor="w")
            self.stat_widgets[key] = num_label

    # -- actions -------------------------------------------------------------
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
        return list(dict.fromkeys(roots))  # dédoublonne en gardant l'ordre

    def _on_analyze_click(self):
        if self.scan_thread and self.scan_thread.is_alive():
            return
        roots = self._selected_roots()
        if not roots:
            self.status_var.set("Sélectionnez au moins un dossier avant de lancer l'analyse.")
            return

        self.analyze_btn.config(state="disabled", text="Analyse en cours…")
        self.progress.pack(fill="x", padx=28, pady=(0, 6))
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
                    shown = current_path if len(current_path) < 70 else "…" + current_path[-67:]
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
        self.analyze_btn.config(state="normal", text="▶  Relancer l'analyse")
        self.status_var.set(
            f"Analyse terminée : {result.total_files} fichiers, {human_size(result.total_size)} "
            f"— {result.content_indexed_count} fichiers indexés en contenu."
        )

        self.stat_widgets["total_files"].config(text=str(result.total_files))
        self.stat_widgets["pdf"].config(text=str(result.counts_by_category.get("pdf", 0)))
        self.stat_widgets["images"].config(text=str(result.counts_by_category.get("images", 0)))
        self.stat_widgets["videos"].config(text=str(result.counts_by_category.get("videos", 0)))
        self.stat_widgets["audio"].config(text=str(result.counts_by_category.get("audio", 0)))
        self.stat_widgets["content_indexed"].config(text=str(result.content_indexed_count))
        self.stat_widgets["duplicates"].config(text=str(result.duplicates_count))
        self.stat_widgets["badly_named"].config(text=str(result.badly_named_count))
        self.stat_widgets["total_size"].config(text=human_size(result.total_size))

    def _run_search(self, query: str = None):
        if query is None:
            query = self.search_var.get()
        else:
            self.search_var.set(query)

        if not self.scan_result.entries:
            self.results_count_var.set("Lancez d'abord une analyse pour pouvoir rechercher.")
            return

        matches = search_entries(self.scan_result.entries, query)
        self.results_count_var.set(
            f"{len(matches)} résultat(s) pour « {query} »" if query.strip() else ""
        )
        self._render_results(matches, query)

    def _render_results(self, matches: list, query: str = ""):
        for widget in self.results_list_frame.winfo_children():
            widget.destroy()

        if not matches:
            ttk.Label(self.results_list_frame, text="Aucun résultat pour le moment.",
                      style="TLabel").pack(anchor="w", pady=10)
            return

        for entry in matches:
            row = ttk.Frame(self.results_list_frame, style="Card.TFrame", padding=(14, 10))
            row.pack(fill="x", pady=4)

            icon = CATEGORY_ICONS.get(entry.category, "📁")
            top = ttk.Frame(row, style="Card.TFrame")
            top.pack(fill="x")
            ttk.Label(top, text=f"{icon}  {entry.name}", style="Card.TLabel",
                      font=(FONT_FAMILY, 11, "bold")).pack(side="left")
            if entry.badly_named:
                ttk.Label(top, text="  nom peu explicite", style="Card.TLabel",
                          foreground=COLOR_WARM, font=(FONT_FAMILY, 8, "bold")).pack(side="left")

            ttk.Label(row, text=os.path.dirname(entry.path), style="Card.TLabel",
                      foreground=COLOR_TEXT_MUTED).pack(anchor="w")

            snippet = content_snippet(entry, query) if query else ""
            if snippet:
                ttk.Label(row, text=f"«  {snippet}  »", style="Card.TLabel",
                          foreground=COLOR_ACCENT, font=(FONT_FAMILY, 9, "italic"),
                          wraplength=1000).pack(anchor="w", pady=(4, 0))

            btn_row = ttk.Frame(row, style="Card.TFrame")
            btn_row.pack(anchor="w", pady=(6, 0))
            ttk.Button(btn_row, text="Ouvrir le fichier", style="Ghost.TButton",
                       command=lambda p=entry.path: self._open_path(p)).pack(side="left", padx=(0, 6))
            ttk.Button(btn_row, text="Ouvrir le dossier", style="Ghost.TButton",
                       command=lambda p=entry.path: self._open_folder(p)).pack(side="left", padx=(0, 6))
            ttk.Button(btn_row, text="Copier le chemin", style="Ghost.TButton",
                       command=lambda p=entry.path: self._copy_path(p)).pack(side="left")

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
