import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
import traceback

APP_NAME = "Retrio"
EXE_NAME = "RetrioWeb.exe"
DOWNLOAD_URL = "https://github.com/FloFish44/retrio/releases/download/v0.5.0-beta/RetrioWeb.zip"
DOWNLOAD_SHA256 = "715F0EE5B0952B46E753C9FA64F0A9EAC31C0C4828FD4141D968C81E9B9318F5"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / "Retrio"


def resource_path(name):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / name


def desktop_path():
    if sys.platform == "win32":
        import ctypes
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
            return Path(buffer.value)
    return Path.home() / "Desktop"


def create_shortcut(shortcut_path, target_path, working_dir, icon_path):
    def ps(value):
        return str(value).replace("'", "''")
    script = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{ps(shortcut_path)}');"
        f"$s.TargetPath='{ps(target_path)}';"
        f"$s.WorkingDirectory='{ps(working_dir)}';"
        f"$s.IconLocation='{ps(icon_path)}';$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


class Api:
    def __init__(self):
        self.window = None
        self.running = False
        self.target = None
        self._maximized = False

    def js(self, function, *values):
        if self.window:
            args = ",".join(json.dumps(value, ensure_ascii=False) for value in values)
            self.window.evaluate_js(f"{function}({args})")

    def start_install(self):
        if self.running:
            return False
        self.running = True
        threading.Thread(target=self.install, daemon=True).start()
        return True

    def install(self):
        archive = INSTALL_DIR / "retrio-download.zip"
        staging = INSTALL_DIR / "app-new"
        current = INSTALL_DIR / "app"
        previous = INSTALL_DIR / "app-previous"
        try:
            INSTALL_DIR.mkdir(parents=True, exist_ok=True)
            opener = urllib.request.build_opener()
            opener.addheaders = [("User-Agent", "Retrio-Installer/0.5 (Windows)")]
            self.js("updateProgress", 5, "Connexion au téléchargement…")
            # Lire par blocs de 1 Mio évite les milliers d'appels JavaScript qui
            # saturaient la fenêtre et faisaient afficher « Ne répond pas ».
            with opener.open(DOWNLOAD_URL, timeout=30) as response, archive.open("wb") as destination:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                last_percent = -1
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                    downloaded += len(chunk)
                    percent = min(70, 5 + int(downloaded * 65 / total)) if total else 10
                    if percent >= last_percent + 2:
                        last_percent = percent
                        detail = f"Téléchargement de Retrio… {downloaded // (1024 * 1024)} Mo"
                        self.js("updateProgress", percent, detail)

            digest = hashlib.sha256()
            with archive.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().upper() != DOWNLOAD_SHA256:
                raise RuntimeError("Le téléchargement est incomplet ou ne correspond pas à la version officielle.")
            self.js("updateProgress", 74, "Vérification terminée…")

            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir()
            self.js("updateProgress", 78, "Installation des fichiers…")
            with zipfile.ZipFile(archive) as package:
                base = staging.resolve()
                for member in package.infolist():
                    destination = (staging / member.filename).resolve()
                    if os.path.commonpath([base, destination]) != str(base):
                        raise RuntimeError("L’archive contient un chemin invalide.")
                package.extractall(staging)
            archive.unlink(missing_ok=True)

            found = next(staging.rglob(EXE_NAME), None)
            if not found:
                raise RuntimeError("Le programme Retrio est absent de l’archive.")
            relative_exe = found.relative_to(staging)
            if previous.exists():
                shutil.rmtree(previous)
            if current.exists():
                current.replace(previous)
            staging.replace(current)
            self.target = current / relative_exe

            # Le premier chargement de Python, WebView2 et des bibliothèques
            # peut être contrôlé par Windows Defender. On le fait ici, sans
            # fenêtre, pour que le premier vrai lancement soit immédiat.
            self.js("updateProgress", 92, "Préparation du premier démarrage…")
            try:
                subprocess.run(
                    [str(self.target), "--warmup"],
                    cwd=str(self.target.parent),
                    timeout=120,
                    check=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                # Une préparation refusée par un antivirus ne rend pas
                # l'installation inutilisable : Retrio chargera normalement.
                pass

            icon = INSTALL_DIR / "retrio_icon.ico"
            shutil.copy2(resource_path("retrio_icon.ico"), icon)
            create_shortcut(desktop_path() / "Retrio.lnk", self.target, self.target.parent, icon)
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            self.js("installDone")
        except Exception as exc:
            archive.unlink(missing_ok=True)
            try:
                (INSTALL_DIR / "installer.log").write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            self.js("installFailed", str(exc))
        finally:
            self.running = False

    def launch(self):
        if self.target and self.target.exists():
            subprocess.Popen([str(self.target)], cwd=str(self.target.parent))
        self.window.destroy()

    def close(self):
        self.window.destroy()

    def minimize(self):
        self.window.minimize()

    def toggle_maximize(self):
        if self._maximized:
            self.window.restore()
        else:
            self.window.maximize()
        self._maximized = not self._maximized


def main():
    import webview
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Retrio.Installer")
    api = Api()
    api.window = webview.create_window("Installation de Retrio", url=str(resource_path("installer.html")),
                                       js_api=api, frameless=True, easy_drag=False,
                                       width=620, height=680, min_size=(580, 640), resizable=True,
                                       background_color="#FBF8F0")
    webview.start(icon=str(resource_path("retrio_icon.ico")))


if __name__ == "__main__":
    main()
