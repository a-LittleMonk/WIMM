import os
import sys

# Keep every file the app writes inside the app folder — matplotlib's font
# cache included (it defaults to ~/.matplotlib). Must run before matplotlib
# is imported anywhere.
from core.app_paths import CACHE_DIR
os.environ.setdefault("MPLCONFIGDIR", os.path.join(CACHE_DIR, "matplotlib"))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from gui.main_window import MainWindow, load_config
from gui.theme import apply_theme, load_aurora, register_bundled_fonts


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Mice Tracker")
    register_bundled_fonts()
    config = load_config()
    load_aurora(config)
    apply_theme(app, config.get("theme", "dark"))   # first start: dark · Graphite
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
