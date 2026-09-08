#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrio — application Windows de recherche documentaire.

100% local : aucune analyse, aucun fichier et aucune requête n'est envoyé
sur Internet. Tout le traitement (parcours des dossiers, index, recherche)
se fait sur la machine de l'utilisateur.

Ne nécessite aucune dépendance externe : uniquement la bibliothèque
standard de Python (tkinter inclus).

Lancer :   python retrio.py
Compiler : voir build_exe.bat (utilise PyInstaller)
"""

import ctypes
import os
import queue
import re
import sys
import subprocess
import threading
import webbrowser
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import Tk, Canvas, StringVar, IntVar, BooleanVar
from tkinter import ttk, filedialog

APP_NAME = "Retrio"
APP_VERSION = "0.1.0 (bêta)"

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


@dataclass
class FileEntry:
    path: str
    name: str
    stem: str
    ext: str
    category: str
    size: int
    badly_named: bool


@dataclass
class ScanResult:
    entries: list = field(default_factory=list)
    counts_by_category: dict = field(default_factory=lambda: defaultdict(int))
    total_files: int = 0
    total_size: int = 0
    duplicates_count: int = 0
    badly_named_count: int = 0
    errors: int = 0


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["o", "Ko", "Mo", "Go", "To"]:
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Po"


def scan_folders(roots: list, progress_cb=None, stop_flag: threading.Event = None) -> ScanResult:
    """Parcourt récursivement les dossiers sélectionnés et construit les stats.

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
                category = categorize(ext)
                badly_named = is_badly_named(stem)

                entry = FileEntry(
                    path=full_path,
                    name=filename,
                    stem=stem,
                    ext=ext.lower(),
                    category=category,
                    size=stat.st_size,
                    badly_named=badly_named,
                )
                result.entries.append(entry)
                result.counts_by_category[category] += 1
                result.total_files += 1
                result.total_size += stat.st_size
                if badly_named:
                    result.badly_named_count += 1
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
# Recherche (démo par mots-clés avec quelques synonymes, en attendant une
# vraie recherche en langage naturel dans une version future)
# ---------------------------------------------------------------------------
SYNONYMS = {
    "facture": ["facture", "invoice", "reçu", "recu"],
    "assurance": ["assurance", "contrat", "attestation"],
    "photo": ["photo", "image", "img", "dsc"],
    "video": ["video", "vidéo", "film", "mov"],
    "musique": ["musique", "son", "audio", "mp3"],
    "devis": ["devis", "estimation", "proposition"],
    "cv": ["cv", "curriculum", "resume"],
    "impot": ["impot", "impôt", "taxe", "fiscal"],
    "banque": ["banque", "releve", "relevé", "compte"],
}


def expand_query(query: str) -> list:
    tokens = re.findall(r"[a-zà-ÿ0-9]+", query.lower())
    expanded = set(tokens)
    for token in tokens:
        for key, syns in SYNONYMS.items():
            if token == key or token in syns:
                expanded.update(syns)
                expanded.add(key)
    return list(expanded)


def search_entries(entries: list, query: str, limit: int = 60) -> list:
    if not query.strip():
        return []
    tokens = expand_query(query)
    scored = []
    for entry in entries:
        haystack = f"{entry.name} {entry.path}".lower()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))
    return [e for _, e in scored[:limit]]


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
        self.status_var.set("Analyse en cours…")
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
            f"Analyse terminée : {result.total_files} fichiers, {human_size(result.total_size)}."
        )

        self.stat_widgets["total_files"].config(text=str(result.total_files))
        self.stat_widgets["pdf"].config(text=str(result.counts_by_category.get("pdf", 0)))
        self.stat_widgets["images"].config(text=str(result.counts_by_category.get("images", 0)))
        self.stat_widgets["videos"].config(text=str(result.counts_by_category.get("videos", 0)))
        self.stat_widgets["audio"].config(text=str(result.counts_by_category.get("audio", 0)))
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
        self._render_results(matches)

    def _render_results(self, matches: list):
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
    Mretrio.pyLocaleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
