import os

APP_NAME = "MiniBrowser"

BASE_DIR = os.path.join(os.path.expanduser("~"), ".minibrowser")
USERSCRIPTS_DIR = os.path.join(BASE_DIR, "userscripts")
DB_PATH = os.path.join(BASE_DIR, "browser.db")
SESSION_FILE = os.path.join(BASE_DIR, "session.json")
ZOOM_FILE = os.path.join(BASE_DIR, "zoom.json")
PROFILE_STORAGE = os.path.join(BASE_DIR, "profile")
ICONS_DIR = os.path.join(BASE_DIR, "icons")

SIDEBAR_APPS_FILE = os.path.join(BASE_DIR, "sidebar_apps.json")
GAMES_FILE = os.path.join(BASE_DIR, "games.json")

# Carpeta donde se extraen (una sola vez) los .zip / .7z / .epub que se
# abren desde el navegador, para poder navegarlos como si fueran carpetas.
ARCHIVES_CACHE_DIR = os.path.join(BASE_DIR, "archivos_extraidos")

# Carpeta donde se descargan y descomprimen (una sola vez) los juegos
# offline agregados como .zip. Cada juego tiene su propia subcarpeta
# "game_<id>" con el .zip ya descomprimido adentro.
GAMES_CACHE_DIR = os.path.join(BASE_DIR, "games_cache")

for _dir in (BASE_DIR, USERSCRIPTS_DIR, PROFILE_STORAGE, ICONS_DIR, ARCHIVES_CACHE_DIR, GAMES_CACHE_DIR):
    os.makedirs(_dir, exist_ok=True)


# ---------------------------------------------------------------------------
# Íconos para las apps ancladas de la barra lateral: el usuario elige el
# archivo (svg/png/jpg/ico) a mano desde Ajustes -> Apps de barra lateral.
# Se copian a ICONS_DIR y la ruta local se guarda en el item (icon_path).
# ---------------------------------------------------------------------------
# Valores por defecto para los archivos JSON (solo se usan la primera vez,
# cuando el archivo todavía no existe)
# ---------------------------------------------------------------------------
DEFAULT_SIDEBAR_APPS = []

DEFAULT_GAMES = []

