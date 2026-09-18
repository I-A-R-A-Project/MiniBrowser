# MiniBrowser

MiniBrowser es una aplicación de escritorio independiente basada en PyQt6 y
QtWebEngine. Ofrece navegación web con pestañas, una barra lateral de
aplicaciones, sesiones persistentes y herramientas para trabajar con archivos
locales.


## Funciones

- Pestañas movibles y cerrables, pestaña nueva, ventanas emergentes con
  pestañas y menú contextual para silenciar o cerrar grupos de pestañas.
- Navegación atrás, adelante, recarga, recarga completa y barra de
  direcciones con búsqueda.
- Sesión persistente de pestañas y perfil aislado de QtWebEngine.
- Historial compartido y marcadores almacenados en SQLite.
- Panel lateral para aplicaciones y juegos configurables.
- Userscripts locales con metadatos `@name`, `@match` y `@run-at`.
- Descargas enviadas al Downloader cuando corresponde y panel de estado de
  descargas del navegador.
- Botón explícito para enviar URL actual al Downloader. No intercepta ni
  redirige navegación automáticamente; Downloader intenta resolver URL.
- Visor PDF integrado de Chromium mediante `PdfViewerEnabled` y
  `PluginsEnabled`.
- Reproductor QtMultimedia para videos locales.
- Carpetas y archivos locales, incluyendo edición de archivos de texto.
- Extracción y navegación de `.zip`, `.7z`, `.rar` y `.epub`. Los archivos
  `.rar` pueden requerir WinRAR, UnRAR, 7-Zip o `unar` instalado en el sistema.
- Juegos online y juegos offline descargados como `.zip`, con caché local.

## Instalación

Se requiere Python 3.10 o superior:

```bash
python -m pip install PyQt6 PyQt6-WebEngine
```

Dependencias opcionales:

```bash
python -m pip install certifi py7zr rarfile
```

`py7zr` habilita un fallback Python para `.7z`; `rarfile` agrega un fallback
para `.rar`. 7-Zip no se instala con `pip`: es una aplicación externa.

## Ejecución

Desde esta carpeta:

```bash
python main.py
```

`main.py` agrega automáticamente la raíz de IARA al `sys.path`, por lo que
puede importar los módulos compartidos de `web_common`. No se debe convertir
esta aplicación en un paquete ni cambiar ese punto de entrada.

## Datos y configuración

El estado se guarda en `%APPDATA%\IARA\MiniBrowser`:

| Ruta | Contenido |
| --- | --- |
| `browser.db` | Historial compartido y marcadores |
| `profile\` | Cookies, almacenamiento y caché persistente de QtWebEngine |
| `session.json` | Pestañas restaurables |
| `userscripts\` | Userscripts locales |
| `sidebar_apps.json` | Aplicaciones de la barra lateral |
| `games.json` | Juegos configurados |
| `archivos_extraidos\` | Caché de archivos comprimidos |
| `games_cache\` | Juegos offline descargados |
| `icons\` | Íconos importados para aplicaciones |

Estas rutas se crean desde `config.py`. No deben incluirse en commits.

## Userscripts

Los scripts se colocan en `%APPDATA%\IARA\MiniBrowser\userscripts\`:

```javascript
// @name    Mi script
// @match   *://*.dominio.com/*
// @run-at  document-idle
```

El navegador genera un ejemplo si la carpeta todavía no contiene uno.

## Estructura

- `main.py`: punto de entrada de la aplicación.
- `window.py`: ventana principal, pestañas, barra lateral, sesión y acciones.
- `browser_tab.py`: pestaña web y coordinación con handlers locales.
- `database.py`: persistencia SQLite de marcadores.
- `dialogs.py`: diálogos de marcadores, descargas y ajustes.
- `downloads.py`: gestión de descargas de QtWebEngine.
- `local_viewer.py`: extracción y renderizado de contenido local.
- `offline_games.py`: descarga y extracción de juegos offline.
- `new_tab_page.py`: página HTML de nueva pestaña.
- `userscripts.py`: carga e inyección de userscripts.
- `web_common\`: pestañas, perfiles, visores, sesiones, historial y utilidades
  compartidas con WebAgent. El historial se implementa en
  `web_common\history.py` mediante `HistoryStore` y `HistoryDialog`.

Los cambios en `web_common` pueden afectar a MiniBrowser y WebAgent; los
cambios propios de MiniBrowser deben mantenerse compatibles con su ejecución
directa mediante `python main.py`.

## Licencia

No hay licencia declarada en este repositorio.
