import os
import shutil
import ssl
import tempfile
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal
from web_common.local_viewer import extract_archive

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    # Si no está instalado certifi, se sigue usando el almacén de
    # certificados del sistema (puede fallar con "certificate has expired"
    # en Windows si ese almacén quedó desactualizado). Se recomienda:
    #   pip install certifi
    _SSL_CONTEXT = ssl.create_default_context()


class OfflineGameDownloader(QThread):
    """Descarga un .zip (juego HTML offline) desde una URL de descarga
    directa, lo descomprime dentro de dest_dir/content
    y detecta cuál es el archivo .html de entrada.
    Se ejecuta en un hilo aparte para no congelar la UI mientras
    descarga y descomprime.
    """

    progress = pyqtSignal(int, int)   # bytes recibidos, bytes totales (0 si se desconoce)
    finished = pyqtSignal(int, str)   # game_id, ruta absoluta al html de entrada
    error = pyqtSignal(int, str)      # game_id, mensaje de error

    def __init__(self, game_id, download_url, dest_dir, parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self.download_url = download_url
        self.dest_dir = dest_dir

    def run(self):
        zip_path = None
        try:
            zip_path = self._download()
            entry_html = self._extract_and_find_entry(zip_path)
            self.finished.emit(self.game_id, entry_html)
        except Exception as e:
            self.error.emit(self.game_id, str(e))
        finally:
            if zip_path and os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass

    def _download(self):
        os.makedirs(self.dest_dir, exist_ok=True)
        req = urllib.request.Request(
            self.download_url,
            headers={"User-Agent": "Mozilla/5.0 (MiniBrowser offline game downloader)"},
        )
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", dir=self.dest_dir)
        received = 0
        with os.fdopen(fd, "wb") as out, \
                urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                received += len(chunk)
                self.progress.emit(received, total)
        return tmp_path

    def _extract_and_find_entry(self, zip_path):
        # Si había un intento anterior fallido, limpiar el contenido viejo.
        extract_dir = os.path.join(self.dest_dir, "content")
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        extract_archive(zip_path, extract_dir)

        html_files = []
        for root, _dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith((".html", ".htm")):
                    html_files.append(os.path.join(root, fname))

        if not html_files:
            raise RuntimeError("El .zip no contiene ningún archivo .html")

        # Preferir "index.html" y, entre varios, el más cercano a la raíz.
        def score(path):
            rel = os.path.relpath(path, extract_dir)
            depth = rel.count(os.sep)
            is_index = os.path.basename(path).lower() == "index.html"
            return (0 if is_index else 1, depth)

        html_files.sort(key=score)
        return html_files[0]
