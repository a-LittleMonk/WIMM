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


def _keep_log_on_disk():
    """WARN / ERROR entries also go to settings/wimm.log, so they survive
    closing the app (the Logs button only holds this session)."""
    from core import logger
    from core.app_paths import SETTINGS_DIR, ensure_dir
    path = os.path.join(ensure_dir(SETTINGS_DIR), "wimm.log")
    try:
        if os.path.getsize(path) > 2_000_000:          # keep one old file
            os.replace(path, path + ".old")
    except OSError:
        pass

    def write(entry):
        if entry[1] in ("WARN", "ERROR"):
            with open(path, "a", encoding="utf-8") as f:
                f.write(logger.format_entry(entry) + "\n")
    logger.subscribe(write)


def _report_crash(kind, value, tb):
    """An error escaping a button handler would otherwise end PyQt5 (and a
    batch held only in memory): log it, tell the user, keep running."""
    import traceback
    from core import logger
    text = "".join(traceback.format_exception(kind, value, tb))
    logger.error(f"Unexpected error:\n{text}", source="app")
    if QApplication.instance() is not None:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "Unexpected error",
                             f"{value}\n\nThe app keeps running; details are in "
                             "the Logs button and settings/wimm.log.")


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    _keep_log_on_disk()
    sys.excepthook = _report_crash
    if sys.platform == "win32":
        # Own taskbar identity, so Windows shows the WIMM icon instead of
        # python.exe's when started from Run WIMM.bat.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WIMM.app")
    app = QApplication(sys.argv)
    app.setApplicationName("Mice Tracker")
    from PyQt5.QtGui import QIcon
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "wimm.ico")))
    register_bundled_fonts()
    config = load_config()
    load_aurora(config)
    apply_theme(app, config.get("theme", "light"))   # first start: light · Mist
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
