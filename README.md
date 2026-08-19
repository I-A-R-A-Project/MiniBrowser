# MiniBrowser

Navegador de escritorio hecho con `PyQt6` y `QtWebEngine`, con pestañas, historial, marcadores, descargas y soporte para contenido local.

## Funciones

- Pestañas navegables con barra de direcciones, atrás, adelante y recarga.
- Marcadores y historial persistidos en `sqlite`.
- Panel lateral fijo para apps ancladas, con panel flotante por app.
- Userscripts estilo Tampermonkey cargados desde carpeta local.
- Descargas administradas desde una ventana propia.
- Visor nativo para `PDF`.
- Reproductor nativo para video local.
- Apertura de archivos locales especiales:
  - `.zip` y `.7z` se extraen una sola vez y se navegan como carpeta.
  - `.rar` se muestra como listado de solo lectura.
  - `.epub` se abre en su primer capítulo cuando es posible.
- Juegos guardados en JSON, incluyendo juegos online y juegos offline empaquetados como `.zip`.

## Entrada principal

- `main.py`: arranque de la aplicación.
- `window.py`: ventana principal y coordinación de pestañas, barra lateral, historial y descargas.

## Instalación

Requiere Python 3 y `PyQt6`.

Dependencias base:

```bash
pip install PyQt6
```

Dependencias opcionales para funciones extra:

```bash
pip install certifi py7zr rarfile
```

Notas:

- `certifi` mejora la validación SSL para descargas de juegos offline.
- `py7zr` habilita la extracción de `.7z`.
- `rarfile` habilita la vista de listado de `.rar`.
- Para leer `.rar` normalmente también hace falta `unrar` o `unar` instalado en el sistema.

## Ejecución

```bash
python browser.py
```

## Datos locales

La aplicación guarda su estado en `~/.minibrowser`:

- `browser.db`: historial y marcadores.
- `profile/`: perfil persistente de `QtWebEngine` y cookies.
- `userscripts/`: scripts de usuario.
- `sidebar_apps.json`: apps de la barra lateral.
- `games.json`: lista de juegos.
- `icons/`: íconos importados para apps.
- `archivos_extraidos/`: caché de archivos comprimidos abiertos.
- `games_cache/`: caché de juegos offline descargados.

## Userscripts

Los scripts se leen desde `~/.minibrowser/userscripts` y usan comentarios tipo:

```js
// @name    Mi script
// @match   *://*.dominio.com/*
// @run-at  document-idle
```

La carpeta incluye un ejemplo generado automáticamente: `ejemplo.js`.

## Estructura

- `browser_tab.py`: pestañas web y bloqueo de navegación local especial.
- `pdf_tab.py`: visor PDF.
- `video_tab.py`: reproductor de video.
- `sidebar.py`: barra lateral y panel flotante.
- `dialogs.py`: diálogos de historial, marcadores, descargas y ajustes.
- `database.py`: persistencia de historial y marcadores.
- `json_store.py`: listas JSON para apps y juegos.
- `local_viewer.py`: extracción y renderizado de archivos locales.
- `offline_games.py`: descarga y descompresión de juegos offline.
- `downloads.py`: administración de descargas.
- `userscripts.py`: carga e inyección de userscripts.

## Licencia

No hay licencia declarada en este repositorio.
