import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from config import APP_NAME
from window import MainWindow
from web_common.instance import acquire_browser_instance


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    instance_server = acquire_browser_instance()
    if instance_server is None:
        return

    window = MainWindow()
    instance_server.set_handler(window.open_instance_popup)
    window.show()
    try:
        sys.exit(app.exec())
    finally:
        instance_server.close()


if __name__ == "__main__":
    main()
