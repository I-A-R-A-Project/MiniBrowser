import os

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QLineEdit, QFileDialog, QWidget,
    QApplication, QMessageBox, QMenu,
)
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEngineSettings, QWebEngineDownloadRequest
)
from PyQt6.QtCore import QStandardPaths, QUrl, Qt

from config import (
    APP_NAME, USERSCRIPTS_DIR, DB_PATH, SESSION_FILE, PROFILE_STORAGE,
    SIDEBAR_APPS_FILE, GAMES_FILE, DEFAULT_SIDEBAR_APPS, DEFAULT_GAMES,
    GAMES_CACHE_DIR,
)
from database import Database
from userscripts import UserScriptManager
from downloads import DownloadManager
from browser_tab import BrowserTab, VIDEO_EXTS
from dialogs import ListDialog, DownloadsDialog, SettingsDialog, HistoryDialog
from new_tab_page import render_new_tab_page
from offline_games import OfflineGameDownloader
from web_common import local_viewer
from web_common.pdf_tab import PdfTab
from web_common.navbar import BasicNavbar, address_to_url, save_web_page
from web_common.downloader_handoff import entry_from_url, launch_downloader
from web_common.json_store import SidebarAppsStore, GamesStore
from web_common.session import (
    is_navigation_title,
    load_tab_session,
    restore_tab_metadata,
    save_tab_session,
)
from web_common.sidebar import SidebarRail, AppPanelOverlay, SidebarContainer
from web_common.video_tab import VideoTab
from web_common.web_profiles import build_web_profile


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1150, 780)

        # Historial y marcadores en sqlite.
        self.db = Database(DB_PATH)
        # Apps de barra lateral y juegos en archivos JSON (fácil de
        # editar/exportar/importar).
        self.sidebar_apps_store = SidebarAppsStore(SIDEBAR_APPS_FILE, DEFAULT_SIDEBAR_APPS)
        self.games_store = GamesStore(GAMES_FILE, DEFAULT_GAMES)

        self.script_manager = UserScriptManager(USERSCRIPTS_DIR)
        self.script_manager.create_example_script()
        self.script_manager.reload()
        self.download_manager = DownloadManager()
        # Descargas de juegos offline (.zip) en curso: game_id -> OfflineGameDownloader.
        # Se guarda la referencia para que el QThread no se destruya a mitad
        # de la descarga y para no permitir dos descargas simultáneas del
        # mismo juego.
        self._active_game_downloads = {}

        self.profile = self._build_profile()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.tabs.tabBarClicked.connect(self._on_tab_bar_clicked)
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)
        self._setup_plus_tab()

        # Riel de íconos: FIJO, docked, parte del layout normal (no flota).
        # Cada app puede tener su propio ícono (elegido por el usuario desde
        # Ajustes -> Apps de barra lateral); si no tiene, se muestran las
        # iniciales del nombre.
        self.rail = SidebarRail()
        self.rail.on_toggle = self._on_sidebar_app_clicked
        self.rail.rebuild(self.sidebar_apps_store.all())

        # Panel de la app anclada: esto SÍ es overlay, flota por encima de
        # las pestañas sin modificar su tamaño.
        self.app_panel = AppPanelOverlay(self.profile)
        self.app_panel.on_new_window_request = self.handle_new_window_request

        container = SidebarContainer(self.rail, self.tabs, self.app_panel)
        self.setCentralWidget(container)

        self._build_toolbar()
        self._build_shortcuts()

        if not self._restore_session_or_default():
            self.new_tab()

    def closeEvent(self, event):
        self._save_session()
        pages = []
        for view in self.app_panel.views.values():
            pages.append(view.page())
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget is not self.plus_widget and hasattr(widget, "page"):
                pages.append(widget.page())
            if widget is not self.plus_widget and isinstance(widget, VideoTab):
                widget.stop()

        for page in pages:
            page.deleteLater()

        QApplication.processEvents()
        super().closeEvent(event)

    # -- perfil con cookies persistentes y descargas -------------------------
    def _build_profile(self):
        profile = build_web_profile(
            "MiniBrowserProfile",
            self,
            PROFILE_STORAGE,
            os.path.join(PROFILE_STORAGE, "cache"),
        )
        profile.downloadRequested.connect(self.on_download_requested)
        return profile

    # -- barra lateral --------------------------------------------------------
    def _on_sidebar_app_clicked(self, app):
        app_id = app["id"]
        if self.app_panel.is_open_for(app_id):
            # ya estaba abierta -> colapsar panel, dejar solo el riel
            self.app_panel.close_panel()
            self.rail.set_checked(app_id, False)
        else:
            self.rail.uncheck_all()
            self.app_panel.open_app(app)
            self.rail.set_checked(app_id, True)

    def refresh_sidebar(self):
        self.rail.rebuild(self.sidebar_apps_store.all(), self.app_panel.active_app_id)

    def toggle_sidebar_visibility(self, visible):
        self.rail.setVisible(visible)
        if not visible:
            self.app_panel.close_panel()
            self.rail.uncheck_all()

    # -- toolbar --------------------------------------------------------------
    def _build_toolbar(self):
        navbar = BasicNavbar(self)
        navbar.on_back = lambda: self.current_tab().back()
        navbar.on_forward = lambda: self.current_tab().forward()
        navbar.on_reload = lambda: self.current_tab().reload()
        navbar.on_stop = lambda: self.current_tab().stop()
        navbar.on_address_bar_enter = self.navigate_to_address
        navbar.on_save_page = lambda: save_web_page(
            self.current_tab(),
            target_dir=Path(__file__).resolve().parent / "saved_pages",
            status_callback=self.statusBar().showMessage,
        )

        # Guardar referencia a address_bar
        self.address_bar = navbar.address_bar
        
        # Agregar bookmark ☆ entre direccion y otros botones
        self.bookmark_action = QAction("☆", navbar)
        self.bookmark_action.triggered.connect(self.toggle_bookmark)
        navbar.addAction(self.bookmark_action)
        
        # Agregar botones especificos de Browser
        bookmarks_action = QAction("🌟​", navbar)
        bookmarks_action.setToolTip("Marcadores")
        bookmarks_action.triggered.connect(self.show_bookmarks)
        navbar.addAction(bookmarks_action)

        games_action = QAction("🎮", navbar)
        games_action.setToolTip("Juegos")
        games_action.triggered.connect(self.show_games)
        navbar.addAction(games_action)

        history_action = QAction("🕖", navbar)
        history_action.setToolTip("Historial")
        history_action.triggered.connect(self.show_history)
        navbar.addAction(history_action)

        downloads_action = QAction("📥", navbar)
        downloads_action.setToolTip("Descargas")
        downloads_action.triggered.connect(self.show_downloads)
        navbar.addAction(downloads_action)

        sidebar_toggle = QAction("🚀​", navbar)
        sidebar_toggle.setToolTip("Mostrar/ocultar barra lateral")
        sidebar_toggle.setCheckable(True)
        sidebar_toggle.setChecked(True)
        sidebar_toggle.toggled.connect(self.toggle_sidebar_visibility)
        navbar.addAction(sidebar_toggle)

        settings_action = QAction("⚙", navbar)
        settings_action.setToolTip("Ajustes y personalizaciones")
        settings_action.triggered.connect(self.show_settings)
        navbar.addAction(settings_action)
        
        self.addToolBar(navbar)

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+T"), self, activated=lambda: self.new_tab())
        QShortcut(QKeySequence("Ctrl+W"), self, activated=lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.address_bar.setFocus())
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.show_history)
        QShortcut(QKeySequence("Ctrl+J"), self, activated=self.show_downloads)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_local_file)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, activated=self.open_local_folder)

    # -- pestañas ---------------------------------------------------------
    def current_tab(self) -> BrowserTab:
        return self.tabs.currentWidget()

    def new_tab(self, url=None):
        """Si no se pasa url, se abre la página local de "nueva pestaña"
        (buscador + accesos rápidos a marcadores) en vez de una web fija."""
        tab = BrowserTab(self.profile, self.script_manager, self)
        insert_at = self.tabs.indexOf(self.plus_widget)
        index = self.tabs.insertTab(insert_at, tab, "Nueva pestaña")
        self.tabs.setCurrentIndex(index)
        if url:
            tab.setUrl(QUrl(url))
        else:
            self._load_new_tab_page(tab)
        return tab

    def _load_new_tab_page(self, tab):
        html = render_new_tab_page(self.db.get_bookmarks())
        tab.page().setHtml(html, QUrl("about:blank"))

    def _save_session(self):
        try:
            save_tab_session(SESSION_FILE, self.tabs, skip_widgets=(self.plus_widget,))
        except Exception:
            pass

    def _restore_session_or_default(self):
        session = load_tab_session(SESSION_FILE)
        tabs = session.get("tabs") or []
        if not tabs:
            return False

        opened = 0
        for entry in tabs:
            url = entry.get("url", "")
            if not url:
                continue
            if url.startswith("file://"):
                local_path = QUrl(url).toLocalFile()
                ext = os.path.splitext(local_path)[1].lower()
                if ext in VIDEO_EXTS:
                    self.open_path_in_new_tab(local_path)
                    opened += 1
                    continue
            tab = self.new_tab("about:blank")
            restore_tab_metadata(self.tabs, self.tabs.indexOf(tab), entry)
            tab.setUrl(QUrl(url))
            opened += 1

        if not opened:
            return False

        active_index = session.get("active_index")
        if isinstance(active_index, int):
            max_index = max(0, self.tabs.indexOf(self.plus_widget) - 1)
            self.tabs.setCurrentIndex(max(0, min(active_index, max_index)))
        return True

    def close_tab(self, index):
        if self.tabs.widget(index) is self.plus_widget:
            return
        was_current = index == self.tabs.currentIndex()
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if isinstance(widget, VideoTab):
            widget.stop()
        widget.deleteLater()
        if self.tabs.count() <= 1:
            self.new_tab()
            return
        if was_current:
            self.tabs.setCurrentIndex(max(0, index - 1))

    def update_tab_title(self, tab, title):
        index = self.tabs.indexOf(tab)
        if index != -1:
            session_title = tab.property("_session_title")
            if is_navigation_title(title) and session_title:
                self.tabs.setTabText(index, session_title)
                return
            if not is_navigation_title(title):
                tab.setProperty("_session_title", "")
            short = (title[:22] + "…") if len(title) > 22 else title
            text = short or "Nueva pestaña"
            if hasattr(tab, "page") and tab.page().isAudioMuted():
                text = "🔇 " + text
            self.tabs.setTabText(index, text)

    def update_tab_icon(self, tab, icon):
        index = self.tabs.indexOf(tab)
        if index != -1:
            self.tabs.setTabIcon(index, icon)

    def _on_current_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if tab is None or tab is self.plus_widget:
            return
        self.update_address_bar(tab, tab.url())

    def _setup_plus_tab(self):
        self.plus_widget = QWidget()
        index = self.tabs.addTab(self.plus_widget, "+")
        bar = self.tabs.tabBar()
        bar.setTabButton(index, bar.ButtonPosition.RightSide, None)
        bar.setTabButton(index, bar.ButtonPosition.LeftSide, None)

    def _on_tab_bar_clicked(self, index):
        if self.tabs.widget(index) is self.plus_widget:
            self.new_tab()

    def _on_tab_moved(self, from_index, to_index):
        # Evita que arrastrando pestañas la "+" termine en el medio.
        plus_index = self.tabs.indexOf(self.plus_widget)
        last = self.tabs.count() - 1
        if plus_index != last:
            self.tabs.tabBar().moveTab(plus_index, last)

    # -- click derecho en pestaña: enmudecer / cerrar a la derecha o izquierda --
    def _show_tab_context_menu(self, pos):
        bar = self.tabs.tabBar()
        index = bar.tabAt(pos)
        if index == -1 or self.tabs.widget(index) is self.plus_widget:
            return

        tab = self.tabs.widget(index)
        last_real_index = self.tabs.indexOf(self.plus_widget) - 1

        menu = QMenu(self)

        if hasattr(tab, "page"):
            muted = tab.page().isAudioMuted()
            mute_action = menu.addAction("Activar sonido" if muted else "Enmudecer pestaña")
            mute_action.triggered.connect(lambda: self._toggle_mute_tab(index))
            menu.addSeparator()

        close_right_action = menu.addAction("Cerrar pestañas a la derecha")
        close_right_action.setEnabled(index < last_real_index)
        close_right_action.triggered.connect(lambda: self._close_tabs_to_right(index))

        close_left_action = menu.addAction("Cerrar pestañas a la izquierda")
        close_left_action.setEnabled(index > 0)
        close_left_action.triggered.connect(lambda: self._close_tabs_to_left(index))

        menu.exec(bar.mapToGlobal(pos))

    def _toggle_mute_tab(self, index):
        tab = self.tabs.widget(index)
        if not hasattr(tab, "page"):
            return
        page = tab.page()
        page.setAudioMuted(not page.isAudioMuted())
        self.update_tab_title(tab, tab.title())

    def _close_multiple_tabs(self, indices):
        for i in sorted(indices, reverse=True):
            widget = self.tabs.widget(i)
            if widget is None or widget is self.plus_widget:
                continue
            self.tabs.removeTab(i)
            widget.deleteLater()
        if self.tabs.count() <= 1:
            self.new_tab()

    def _close_tabs_to_right(self, from_index):
        last_real_index = self.tabs.indexOf(self.plus_widget) - 1
        self._close_multiple_tabs(range(from_index + 1, last_real_index + 1))

    def _close_tabs_to_left(self, from_index):
        self._close_multiple_tabs(range(0, from_index))

    def handle_new_window_request(self, request):
        tab = self.new_tab("about:blank")
        request.openIn(tab.page())

    def handle_new_tab_request(self):
        return self.new_tab("about:blank").page()

    # -- barra de direcciones -----------------------------------------------
    def update_address_bar(self, tab, qurl: QUrl):
        if tab != self.current_tab():
            return
        text = qurl.toString()
        self.address_bar.setText("" if text == "about:blank" else text)
        self.address_bar.setCursorPosition(0)
        self._refresh_bookmark_icon(text)

    def navigate_to_address(self, text: str):
        text = self.address_bar.text().strip()
        if not text:
            return

        url = address_to_url(text, search_url="https://www.google.com/search?q={query}")
        if url is None:
            return
        if url.isLocalFile():
            # Si es uno de nuestros tipos especiales (pdf/zip/rar/7z/epub/
            # video), BrowserPage.acceptNavigationRequest intercepta esta
            # misma navegación y llama a handle_special_local_file; para el
            # resto (carpetas, texto, html, imágenes...) Chromium la
            # muestra directamente.
            self.current_tab().setUrl(url)
            return

        self.current_tab().setUrl(url)

    # -- abrir archivos/carpetas locales --------------------------------------
    def open_local_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir archivo")
        if path:
            self.open_path_in_new_tab(path)

    def open_local_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Abrir carpeta")
        if path:
            self.open_path_in_new_tab(path)

    def open_path_in_new_tab(self, path):
        """Abre una ruta local (usada por el diálogo de Descargas y por los
        selectores de archivo/carpeta) en una pestaña nueva."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            self.open_pdf_tab(path)
            return
        if ext in VIDEO_EXTS:
            self.open_video_tab(path)
            return
        tab = self.new_tab("about:blank")
        tab.setUrl(QUrl.fromLocalFile(path))

    def handle_special_local_file(self, tab, local_path):
        """Llamado por BrowserPage cuando una pestaña de navegación (la
        barra de direcciones, o un clic dentro del listado nativo de una
        carpeta file://) intenta ir a un .pdf/.zip/.rar/.7z/.epub/video.
        Acá decidimos cómo mostrarlo en lugar de dejar que Chromium lo
        trate como una descarga o se quede con el <video> HTML5 sin poder
        reproducir el archivo."""
        ext = os.path.splitext(local_path)[1].lower()
        if ext == ".pdf":
            self.open_pdf_tab(local_path)
            return
        if ext in VIDEO_EXTS:
            # Igual que el PDF: el video necesita un reproductor propio
            # (QtMultimedia) porque el <video> HTML5 de QtWebEngine no
            # siempre trae codecs propietarios (H.264/AAC).
            self.open_video_tab(local_path)
            return
        self._open_local_target(tab, local_path)

    def open_video_tab(self, path):
        """Abre un video local en una pestaña propia con reproductor
        nativo QtMultimedia. Se usa en vez del <video> HTML5 de Chromium
        porque muchas builds de QtWebEngine no traen codecs propietarios
        (H.264/AAC) y el video se queda con los controles trabados en
        0:00 sin reproducir nada."""
        tab = VideoTab(path, self)
        title = os.path.basename(path)
        short = (title[:22] + "…") if len(title) > 22 else title
        index = self.tabs.addTab(tab, short or "Video")
        self.tabs.setCurrentIndex(index)
        file_url = tab.url().toString()
        self.db.add_history(file_url, title)
        return tab

    def open_pdf_tab(self, path):
        tab = PdfTab(path, self)
        title = os.path.basename(path)
        index = self.tabs.addTab(tab, title[:22] or "PDF")
        self.tabs.setCurrentIndex(index)
        return tab

    def _open_local_target(self, tab, local_path):
        """Decide cómo mostrar una ruta local que NO es un pdf ni un video.
        Los .zip y .7z se descomprimen y se navegan como carpeta; los
        .rar se listan (no se pueden extraer sin una herramienta externa);
        los .epub se abren en su primer capítulo. El resto (carpetas,
        .txt, .html, imágenes, etc.) se lo dejamos directamente a
        Chromium."""
        ext = os.path.splitext(local_path)[1].lower()
        try:
            if ext == ".zip":
                dest = local_viewer.extract_zip(local_path)
                tab.setUrl(QUrl.fromLocalFile(dest))
                return

            if ext == ".7z":
                dest = local_viewer.extract_7z(local_path)
                if dest is None:
                    tab.page().setHtml(
                        local_viewer.render_missing_dependency(local_path, "py7zr"),
                        QUrl.fromLocalFile(local_path),
                    )
                else:
                    tab.setUrl(QUrl.fromLocalFile(dest))
                return

            if ext == ".rar":
                try:
                    html = local_viewer.render_rar_listing(local_path)
                except ImportError:
                    html = local_viewer.render_missing_dependency(
                        local_path, "rarfile",
                        "Además necesitás tener instalado `unrar` o `unar` en el sistema "
                        "para que rarfile pueda leer el archivo.",
                    )
                tab.page().setHtml(html, QUrl.fromLocalFile(local_path))
                return

            if ext == ".epub":
                target = local_viewer.extract_epub_root(local_path)
                tab.setUrl(QUrl.fromLocalFile(target))
                return
        except Exception as e:
            tab.page().setHtml(
                local_viewer.render_error(local_path, f"Error al procesar el archivo: {e}"),
                QUrl.fromLocalFile(local_path),
            )
            return

        # Carpetas, .txt, .html, imágenes, etc.
        tab.setUrl(QUrl.fromLocalFile(local_path))

    # -- marcadores -----------------------------------------------------------
    def toggle_bookmark(self):
        tab = self.current_tab()
        url = tab.url().toString()
        title = tab.title() or url
        if self.db.is_bookmarked(url):
            self.db.remove_bookmark(url)
        else:
            self.db.add_bookmark(url, title)
        self._refresh_bookmark_icon(url)

    def _refresh_bookmark_icon(self, url):
        self.bookmark_action.setText("★" if self.db.is_bookmarked(url) else "☆")

    def show_bookmarks(self):
        def build_items(query=""):
            rows = self.db.search_bookmarks(query) if query else self.db.get_bookmarks()
            return [(title or url, url) for url, title in rows]

        dialog = ListDialog(
            "Marcadores", build_items(),
            on_open=lambda url: self.new_tab(url),
            on_delete=lambda url: self.db.remove_bookmark(url),
            on_search=build_items,
        )
        dialog.exec()

    # -- juegos -----------------------------------------------------------------
    def show_games(self):
        items = [(g["name"], g) for g in self.games_store.all()]
        dialog = ListDialog(
            "Juegos", items,
            on_open=self._open_game,
        )
        dialog.exec()

    def _open_game(self, game):
        """Abre un juego de la lista. Los juegos normales (kind="link")
        se abren directo por URL. Los juegos offline (kind="offline_zip")
        se abren desde el .html ya descomprimido en caché si existe; si
        todavía no se descargaron, se descargan y descomprimen una sola
        vez (las próximas veces se abre el html cacheado directamente,
        sin volver a descargar nada)."""
        if game.get("kind") == "offline_zip":
            local_entry = game.get("local_entry")
            if local_entry and os.path.exists(local_entry):
                self.new_tab(QUrl.fromLocalFile(local_entry).toString())
            else:
                self._download_offline_game(game)
        else:
            self.new_tab(game["url"])

    def _download_offline_game(self, game):
        game_id = game["id"]
        if game_id in self._active_game_downloads:
            self.statusBar().showMessage(f"'{game['name']}' ya se está descargando…", 4000)
            return

        dest_dir = os.path.join(GAMES_CACHE_DIR, f"game_{game_id}")
        downloader = OfflineGameDownloader(game_id, game["download_url"], dest_dir, self)
        self._active_game_downloads[game_id] = downloader

        downloader.progress.connect(self._on_offline_game_progress)
        downloader.finished.connect(self._on_offline_game_finished)
        downloader.error.connect(self._on_offline_game_error)

        self.statusBar().showMessage(f"Descargando '{game['name']}'…", 0)
        downloader.start()

    def _on_offline_game_progress(self, received, total):
        if total:
            pct = int(received * 100 / total)
            self.statusBar().showMessage(f"Descargando juego… {pct}%", 0)
        else:
            self.statusBar().showMessage(f"Descargando juego… {received // 1024} KB", 0)

    def _on_offline_game_finished(self, game_id, entry_html):
        self._active_game_downloads.pop(game_id, None)
        self.games_store.set_local_entry(game_id, entry_html)
        self.statusBar().showMessage("Juego descargado y listo.", 4000)
        self.new_tab(QUrl.fromLocalFile(entry_html).toString())

    def _on_offline_game_error(self, game_id, message):
        self._active_game_downloads.pop(game_id, None)
        self.statusBar().showMessage("Error al descargar el juego.", 5000)
        QMessageBox.critical(self, "Error al descargar el juego", message)

    # -- historial --------------------------------------------------------------
    def show_history(self):
        dialog = HistoryDialog(self.db, on_open=lambda url: self.new_tab(url))
        dialog.exec()

    # -- descargas --------------------------------------------------------------
    def on_download_requested(self, request: QWebEngineDownloadRequest):
        url = request.url().toString()
        if url and not url.startswith(("blob:", "data:", "file:")):
            download_dir = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DownloadLocation
            ) or os.path.join(os.path.expanduser("~"), "Downloads")
            ok, error = launch_downloader(
                [entry_from_url(url, path=download_dir, title=request.downloadFileName())],
                __file__,
            )
            if ok:
                request.cancel()
                self.statusBar().showMessage("Descarga enviada al Downloader", 5000)
                return
            self.statusBar().showMessage(error, 7000)

        item = self.download_manager.handle_download(request)
        self.statusBar().showMessage(f"Descargando: {item.filename}", 5000)

    def show_downloads(self):
        dialog = DownloadsDialog(self.download_manager, on_open=self.open_path_in_new_tab)
        dialog.exec()

    # -- ajustes / personalizaciones --------------------------------------------
    def show_settings(self):
        dialog = SettingsDialog(
            self.script_manager, self.sidebar_apps_store, self.games_store,
            on_sidebar_change=self.refresh_sidebar,
        )
        dialog.exec()
        self.script_manager.reload()
        self.refresh_sidebar()
