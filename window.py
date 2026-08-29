import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QToolBar, QLineEdit, QFileDialog, QWidget,
    QApplication, QMessageBox,
)
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEngineSettings, QWebEngineDownloadRequest
)
from PyQt6.QtCore import QStandardPaths, QTimer, QUrl, Qt

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
from web_common.navbar import BasicNavbar, address_to_url, save_web_page
from web_common.downloader_handoff import (
    entry_from_url, handoff_url_to_downloader, launch_downloader,
)
from web_common.json_store import SidebarAppsStore, GamesStore
from web_common.session import (
    load_tab_session,
    restore_tab_metadata,
    SessionAutoSaver,
    save_tab_session,
)
from web_common.sidebar import SidebarRail, AppPanelOverlay, SidebarContainer
from web_common.tabs import (
    ContextTabBar, add_plus_tab, install_tab_context_menu, keep_plus_tab_last,
    update_tab_icon, update_tab_title,
)
from web_common.media_tabs import open_video_tab as add_video_tab
from web_common.video_tab import VideoTab
from web_common.epub_tab import EpubTab
from web_common import folder_viewer
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
        self.session_autosaver = SessionAutoSaver(self._save_session)
        # Descargas de juegos offline (.zip) en curso: game_id -> OfflineGameDownloader.
        # Se guarda la referencia para que el QThread no se destruya a mitad
        # de la descarga y para no permitir dos descargas simultáneas del
        # mismo juego.
        self._active_game_downloads = {}

        self.profile = self._build_profile()

        self.tabs = QTabWidget()
        self.tabs.setTabBar(ContextTabBar(self.tabs))
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self._setup_plus_tab()
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.tabs.tabBarClicked.connect(self._on_tab_bar_clicked)
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)
        install_tab_context_menu(
            self.tabs,
            close_tab=self.close_tab,
            plus_widget=self.plus_widget,
            toggle_mute=self._toggle_mute_tab,
            direct_right_click=True,
        )

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

        send_action = QAction("⬇", navbar)
        send_action.setToolTip("Enviar URL actual al Downloader")
        send_action.triggered.connect(self.send_current_url_to_downloader)
        navbar.addAction(send_action)
        
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

    def send_current_url_to_downloader(self):
        tab = self.current_tab()
        url = tab.url().toString() if tab else ""
        download_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        handoff_url_to_downloader(
            url,
            __file__,
            path=download_dir,
            title=tab.title() if tab else "",
            status_callback=self.statusBar().showMessage,
        )

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+T"), self, activated=lambda: self.new_tab())
        QShortcut(QKeySequence("Ctrl+W"), self, activated=lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.address_bar.setFocus())
        QShortcut(QKeySequence("Ctrl+Shift+R"), self, activated=self.hard_reload_current)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.toggle_bookmark)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.show_history)
        QShortcut(QKeySequence("Ctrl+J"), self, activated=self.show_downloads)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_local_file)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, activated=self.open_local_folder)

    def hard_reload_current(self):
        tab = self.current_tab()
        if tab is None:
            return

        url = tab.url()
        tab.page().profile().clearHttpCache()
        tab.page().runJavaScript(
            """
            (async () => {
                if (navigator.serviceWorker) {
                    const registrations = await navigator.serviceWorker.getRegistrations();
                    await Promise.all(registrations.map(registration => registration.unregister()));
                }
                if (window.caches) {
                    const cacheNames = await caches.keys();
                    await Promise.all(cacheNames.map(cacheName => caches.delete(cacheName)));
                }
                return true;
            })();
            """,
            lambda _result: self._reload_after_cache_clear(tab, url),
        )

    def _reload_after_cache_clear(self, tab, url):
        if tab is None or url.isEmpty():
            return
        tab.setUrl(QUrl("about:blank"))
        QTimer.singleShot(250, lambda: tab.setUrl(url))

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
        self.session_autosaver.schedule()
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
        elif was_current:
            self.tabs.setCurrentIndex(max(0, index - 1))
        self.session_autosaver.schedule()

    def update_tab_title(self, tab, title):
        update_tab_title(
            self.tabs, tab, title, title_limit=22, muted_prefix="🔇 "
        )

    def update_tab_icon(self, tab, icon):
        update_tab_icon(self.tabs, tab, icon)

    def _on_current_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if tab is None or tab is self.plus_widget:
            return
        self.update_address_bar(tab, tab.url())

    def _setup_plus_tab(self):
        self.plus_widget = add_plus_tab(self.tabs)

    def _on_tab_bar_clicked(self, index):
        if self.tabs.widget(index) is self.plus_widget:
            self.new_tab()

    def _on_tab_moved(self, from_index, to_index):
        # Evita que arrastrando pestañas la "+" termine en el medio.
        keep_plus_tab_last(self.tabs, self.plus_widget)

    def _toggle_mute_tab(self, index):
        tab = self.tabs.widget(index)
        if not hasattr(tab, "page"):
            return
        page = tab.page()
        page.setAudioMuted(not page.isAudioMuted())
        self.update_tab_title(tab, tab.title())

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
        if ext in VIDEO_EXTS:
            add_video_tab(
                self.tabs, path, self, title_limit=22,
                on_open=lambda tab, title: self.db.add_history(
                    tab.url().toString(), title
                ),
            )
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
        if ext in VIDEO_EXTS:
            # Igual que el PDF: el video necesita un reproductor propio
            # (QtMultimedia) porque el <video> HTML5 de QtWebEngine no
            # siempre trae codecs propietarios (H.264/AAC).
            add_video_tab(
                self.tabs, local_path, self, title_limit=22,
                on_open=lambda tab, title: self.db.add_history(
                    tab.url().toString(), title
                ),
            )
            return
        self._open_local_target(tab, local_path)

    def render_folder_view(self, page, folder_path):
        folder_viewer.render_folder_view(page, folder_path)

    def render_file_view(self, page, file_path):
        folder_viewer.render_file_view(page, file_path)

    def _open_local_target(self, tab, local_path):
        """Decide cómo mostrar una ruta local que NO es un pdf ni un video.
        Los .zip y .7z se descomprimen y se navegan como carpeta; los
        .rar se listan (no se pueden extraer sin una herramienta externa);
        los .epub se abren en su primer capítulo. El resto (carpetas,
        .txt, .html, imágenes, etc.) se lo dejamos directamente a
        Chromium."""
        cache_dir = Path.home() / ".minibrowser" / "archives_cache"
        local_viewer.open_local_target(
            tab,
            local_path,
            cache_dir,
            epub_handler=self._replace_tab_with_epub,
        )

    def _replace_tab_with_epub(self, tab, local_path, cache_dir):
        epub = EpubTab(
            tab.page().profile(),
            local_path,
            cache_dir=cache_dir,
            parent=self,
        )
        index = self.tabs.indexOf(tab)
        self.tabs.removeTab(index)
        self.tabs.insertTab(index, epub, epub.title())
        self.tabs.setCurrentIndex(index)
        tab.deleteLater()

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
