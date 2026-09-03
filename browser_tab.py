from PyQt6.QtCore import QUrl

from userscripts import UserScriptManager
from web_common import folder_viewer
from web_common.navigation import sync_address_bar
from web_common.tabs import (
    SPECIAL_LOCAL_EXTS, VIDEO_EXTS, UnifiedWebEnginePage, UnifiedWebTab,
    update_tab_icon, update_tab_title,
)

BrowserPage = UnifiedWebEnginePage


class BrowserTab(UnifiedWebTab):
    def __init__(self, profile, script_manager: UserScriptManager, main_window):
        self.main_window = main_window
        super().__init__(
            profile,
            parent_window=main_window,
            script_manager=script_manager,
            special_local_handler=main_window.handle_special_local_file,
            folder_view_handler=folder_viewer.render_folder_view,
            file_view_handler=folder_viewer.render_file_view,
            new_tab_handler=main_window.handle_new_tab_request,
            new_window_handler=main_window.handle_new_window_request,
            url_changed_handler=lambda tab, url: sync_address_bar(
                main_window.tabs, tab, url, main_window.address_bar,
                plus_widget=main_window.plus_widget,
                extra_callback=main_window._refresh_bookmark_icon,
            ),
            title_changed_handler=lambda tab, title: update_tab_title(
                main_window.tabs, tab, title, title_limit=22, muted_prefix="🔇 "
            ),
            icon_changed_handler=lambda tab, icon: update_tab_icon(
                main_window.tabs, tab, icon
            ),
            load_finished_handler=self._handle_load_finished,
        )

    def _handle_load_finished(self, _tab, ok):
        if ok:
            url = self.url().toString()
            title = self.title() or url
            if url and url != "about:blank":
                self.main_window.db.add_history(url, title, self.session_id)
