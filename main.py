import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from gui.main_window import MainWindow, load_config
from gui.theme import apply_theme, load_aurora, load_fonts


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Mice Tracker")
    config = load_config()
    load_aurora(config)
    load_fonts(config)
    apply_theme(app, config.get("theme", "light"))
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
