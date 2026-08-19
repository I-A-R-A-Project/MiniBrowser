from PyQt6.QtCore import QUrl

from userscripts import UserScriptManager
from web_common.tabs import SPECIAL_LOCAL_EXTS, VIDEO_EXTS, UnifiedWebEnginePage, UnifiedWebTab

BrowserPage = UnifiedWebEnginePage


class BrowserTab(UnifiedWebTab):
    def __init__(self, profile, script_manager: UserScriptManager, main_window):
        self.main_window = main_window
        super().__init__(
            profile,
            parent_window=main_window,
            script_manager=script_manager,
            special_local_handler=main_window.handle_special_local_file,
            new_tab_handler=main_window.handle_new_tab_request,
            new_window_handler=main_window.handle_new_window_request,
            url_changed_handler=self._handle_url_changed,
            title_changed_handler=lambda tab, title: main_window.update_tab_title(tab, title),
            icon_changed_handler=lambda tab, icon: main_window.update_tab_icon(tab, icon),
            load_finished_handler=self._handle_load_finished,
        )

    def _handle_url_changed(self, _tab, qurl: QUrl):
        self.main_window.update_address_bar(self, qurl)

    def _handle_load_finished(self, _tab, ok):
        if ok:
            url = self.url().toString()
            title = self.title() or url
            if url and url != "about:blank":
                self.main_window.db.add_history(url, title, self.session_id)
