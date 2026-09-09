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

APP_NAME = "Retrio"
EXE_NAME = "RetrioWeb.exe"
DOWNLOAD_URL = "https://github.com/FloFish44/retrio/releases/download/v0.5.0-beta/RetrioWeb.zip"
DOWNLOAD_SHA256 = "55D1141D5F8953652069421557C29E2168C1A783702D502133B8CC6C7A316F1A"
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
            urllib.request.install_opener(opener)

            def progress(block, size, total):
                if total > 0:
                    self.js("updateProgress", min(70, 5 + int(block * size * 65 / total)), "Téléchargement de Retrio…")
            urllib.request.urlretrieve(DOWNLOAD_URL, archive, reporthook=progress)

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

            icon = INSTALL_DIR / "retrio_icon.ico"
            shutil.copy2(resource_path("retrio_icon.ico"), icon)
            create_shortcut(desktop_path() / "Retrio.lnk", self.target, self.target.parent, icon)
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            self.js("installDone")
        except Exception as exc:
            archive.unlink(missing_ok=True)
            self.js("installFailed", str(exc))
        finally:
            self.running = False

    def launch(self):
        if self.target and self.target.exists():
            subprocess.Popen([str(self.target)], cwd=str(self.target.parent))
        self.window.destroy()

    def close(self):
        self.window.destroy()


def main():
    import webview
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Retrio.Installer")
    api = Api()
    api.window = webview.create_window("Installation de Retrio", url=str(resource_path("installer.html")),
                                       js_api=api, width=560, height=570, resizable=False,
                                       background_color="#FBF8F0")
    webview.start(icon=str(resource_path("retrio_icon.ico")))


if __name__ == "__main__":
    main()
