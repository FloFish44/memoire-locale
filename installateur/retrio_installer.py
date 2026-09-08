import os
import sys
import threading
import subprocess
import urllib.request
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "Retrio"
EXE_NAME = "RetrioWeb.exe"
# Archive contenant le dossier de l'app en mode "onedir" (RetrioWeb.exe + _internal/)
DOWNLOAD_URL = "https://github.com/FloFish44/retrio/releases/download/v0.1.0-beta/RetrioWeb.zip"
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "Retrio")

# --- Design tokens (from the Claude Design handoff, "Retrio Setup") ---
BG = "#FBF8F0"
HEADER_BG = "#1B4332"
HEADER_TEXT = "#F5F1E6"
ICON_BG = "#95D5B2"
ICON_TEXT = "#0E1B14"
TITLE_COLOR = "#14251C"
BODY_TEXT = "#4C5A50"
INFO_BG = "#EEF3EC"
INFO_BORDER = "#DED4BC"
INFO_DOT = "#2F6B4A"
INFO_TEXT = "#3C4A40"
TROUGH = "#EEE8D8"
PROGRESS_COLOR = "#2F6B4A"
STATUS_MONO = "#7A7161"
FOOTER_MONO = "#9AA79E"
SEPARATOR = "#DED4BC"
BTN_READY = "#1B4332"
BTN_INSTALLING = "#5B7364"
BTN_DONE = "#2F6B4A"


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def create_shortcut(shortcut_path, target_path, working_dir, icon_path=None):
    icon_line = f"$Shortcut.IconLocation = '{icon_path}';" if icon_path else ""
    ps_script = (
        "$WshShell = New-Object -ComObject WScript.Shell;"
        f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}');"
        f"$Shortcut.TargetPath = '{target_path}';"
        f"$Shortcut.WorkingDirectory = '{working_dir}';"
        f"{icon_line}"
        "$Shortcut.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )


class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.phase = "ready"
        root.title(f"Installation de {APP_NAME}")
        root.geometry("520x460")
        root.minsize(520, 460)
        root.configure(bg=BG)
        try:
            root.iconbitmap(resource_path("retrio_icon.ico"))
        except Exception:
            pass

        # --- Custom header bar (mimics the design's title bar) ---
        header = tk.Frame(root, bg=HEADER_BG, height=46)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        icon_lbl = tk.Label(
            header, text="R", bg=ICON_BG, fg=ICON_TEXT,
            font=("Georgia", 11, "bold"), width=2, height=1,
        )
        icon_lbl.pack(side="left", padx=(16, 10), pady=12)

        tk.Label(
            header, text=f"Installation de {APP_NAME}", bg=HEADER_BG, fg=HEADER_TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", pady=12)

        # --- Body ---
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=36, pady=(28, 24))

        self.headline_label = tk.Label(
            body, text="", bg=BG, fg=TITLE_COLOR, font=("Georgia", 17, "bold"),
            anchor="w", justify="left", wraplength=440,
        )
        self.headline_label.pack(fill="x", pady=(0, 14))

        tk.Label(
            body,
            text=f"Cet assistant va télécharger et installer {APP_NAME} sur votre\n"
                 "ordinateur, puis créer un raccourci sur le Bureau.",
            bg=BG, fg=BODY_TEXT, font=("Segoe UI", 10), justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 18))

        info = tk.Frame(body, bg=INFO_BG, highlightbackground=INFO_BORDER, highlightthickness=1)
        info.pack(fill="x", pady=(0, 24))
        info_inner = tk.Frame(info, bg=INFO_BG)
        info_inner.pack(fill="x", padx=12, pady=9)
        dot = tk.Canvas(info_inner, width=8, height=8, bg=INFO_BG, highlightthickness=0)
        dot.create_oval(0, 0, 7, 7, fill=INFO_DOT, outline="")
        dot.pack(side="left", padx=(0, 9))
        tk.Label(
            info_inner,
            text="Une connexion Internet est nécessaire pour cette étape — le traitement\n"
                 "de vos fichiers, lui, reste 100% local.",
            bg=INFO_BG, fg=INFO_TEXT, font=("Segoe UI", 9), justify="left", anchor="w",
        ).pack(side="left")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Retrio.Horizontal.TProgressbar",
            troughcolor=TROUGH, background=PROGRESS_COLOR, bordercolor=TROUGH,
            lightcolor=PROGRESS_COLOR, darkcolor=PROGRESS_COLOR, thickness=10,
        )
        self.progress = ttk.Progressbar(
            body, style="Retrio.Horizontal.TProgressbar", length=440, mode="determinate",
        )
        self.progress.pack(fill="x", pady=(0, 8))

        status_row = tk.Frame(body, bg=BG)
        status_row.pack(fill="x", pady=(0, 22))
        self.status_label = tk.Label(
            status_row, text="Prêt à installer.", bg=BG, fg=STATUS_MONO,
            font=("Consolas", 9), anchor="w",
        )
        self.status_label.pack(side="left")
        self.percent_label = tk.Label(
            status_row, text="0%", bg=BG, fg=STATUS_MONO, font=("Consolas", 9), anchor="e",
        )
        self.percent_label.pack(side="right")

        self.action_button = tk.Button(
            body, text="Installer", command=self.on_button_click,
            bg=BTN_READY, fg="#F5F1E6", activebackground=BTN_READY, activeforeground="#F5F1E6",
            font=("Segoe UI", 10, "bold"), relief="flat", bd=0, padx=0, pady=12,
            cursor="hand2",
        )
        self.action_button.pack(fill="x")

        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", pady=(20, 0))
        sep = tk.Canvas(footer, height=1, bg=BG, highlightthickness=0)
        sep.pack(fill="x")
        for x in range(0, 460, 6):
            sep.create_line(x, 0, x + 3, 0, fill=SEPARATOR)
        tk.Label(
            footer, text="Windows 10/11 · v1.0", bg=BG, fg=FOOTER_MONO, font=("Consolas", 8),
        ).pack(anchor="e", pady=(8, 0))

        self.target_exe = None
        self.working_dir = None
        self.set_phase("ready")

    # --- Phase / state machine (ready -> installing -> done) ---
    def set_phase(self, phase):
        self.phase = phase
        if phase == "ready":
            self.headline_label.config(text=f"Bienvenue dans l'installation de {APP_NAME}")
            self.status_label.config(text="Prêt à installer.")
            self.action_button.config(
                text="Installer", bg=BTN_READY, activebackground=BTN_READY,
                state="normal", cursor="hand2",
            )
        elif phase == "installing":
            self.headline_label.config(text="Installation en cours…")
            self.status_label.config(text="Copie des fichiers, ne fermez pas cette fenêtre.")
            self.action_button.config(
                text="Installation…", bg=BTN_INSTALLING, activebackground=BTN_INSTALLING,
                state="disabled", cursor="arrow",
            )
        elif phase == "done":
            self.headline_label.config(text=f"{APP_NAME} est installé.")
            self.status_label.config(text="Raccourci créé sur le Bureau.")
            self.action_button.config(
                text=f"Ouvrir {APP_NAME}", bg=BTN_DONE, activebackground=BTN_DONE,
                state="normal", cursor="hand2",
            )

    def on_button_click(self):
        if self.phase == "ready":
            self.start_install()
        elif self.phase == "done":
            self.launch_and_close()

    def set_progress(self, value):
        value = max(0, min(100, value))
        self.root.after(0, lambda: (
            self.progress.config(value=value),
            self.percent_label.config(text=f"{int(value)}%"),
        ))

    def start_install(self):
        self.set_phase("installing")
        threading.Thread(target=self.run_install, daemon=True).start()

    def run_install(self):
        try:
            os.makedirs(INSTALL_DIR, exist_ok=True)
            self.set_progress(5)

            # GitHub (et le stockage de release-assets vers lequel il redirige)
            # rejette les requêtes sans en-tête User-Agent avec un 404 trompeur.
            # urlretrieve n'en envoie pas par défaut : on installe un opener
            # global qui en ajoute un avant de télécharger.
            opener = urllib.request.build_opener()
            opener.addheaders = [("User-Agent", "Retrio-Installer/1.0 (Windows)")]
            urllib.request.install_opener(opener)

            zip_path = os.path.join(INSTALL_DIR, "_retrio_app.zip")

            def report(block_num, block_size, total_size):
                if total_size > 0:
                    # Téléchargement : 5% -> 70%
                    pct = min(70, 5 + int(block_num * block_size * 65 / total_size))
                    self.set_progress(pct)

            urllib.request.urlretrieve(DOWNLOAD_URL, zip_path, reporthook=report)
            self.set_progress(72)

            # Réinstallation propre : on vide un ancien dossier applicatif s'il existe,
            # pour éviter de mélanger d'anciens fichiers _internal avec les nouveaux.
            app_dir = os.path.join(INSTALL_DIR, "app")
            if os.path.isdir(app_dir):
                shutil.rmtree(app_dir, ignore_errors=True)
            os.makedirs(app_dir, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(app_dir)
            self.set_progress(88)

            os.remove(zip_path)

            # L'archive peut contenir directement les fichiers, ou un sous-dossier
            # (ex: RetrioWeb/RetrioWeb.exe) selon la façon dont elle a été zippée.
            target_exe = os.path.join(app_dir, EXE_NAME)
            if not os.path.isfile(target_exe):
                for root_dir, _dirs, files in os.walk(app_dir):
                    if EXE_NAME in files:
                        target_exe = os.path.join(root_dir, EXE_NAME)
                        break
            working_dir = os.path.dirname(target_exe)
            self.set_progress(92)

            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            shortcut_path = os.path.join(desktop, f"{APP_NAME}.lnk")
            icon_path = None
            try:
                bundled_icon = resource_path("retrio_icon.ico")
                if os.path.exists(bundled_icon):
                    icon_path = bundled_icon
            except Exception:
                pass
            create_shortcut(shortcut_path, target_exe, working_dir, icon_path)
            self.set_progress(100)

            self.target_exe = target_exe
            self.working_dir = working_dir
            self.root.after(0, lambda: self.set_phase("done"))
        except Exception as exc:
            self.root.after(0, self.on_error, str(exc))

    def launch_and_close(self):
        try:
            if self.target_exe:
                subprocess.Popen([self.target_exe], cwd=getattr(self, "working_dir", INSTALL_DIR))
        finally:
            self.root.destroy()

    def on_error(self, message):
        self.set_phase("ready")
        self.set_progress(0)
        messagebox.showerror(
            "Erreur d'installation",
            f"L'installation a échoué :\n{message}\n\nVérifiez votre connexion Internet et réessayez.",
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = InstallerApp(root)
    root.mainloop()
