"""Application theme — implements the "Mice Tracker Redesign v2" look.

Warm neutral greys, a single deep-navy accent (light theme) / soft steel-blue
accent (dark theme), Instrument Sans + JetBrains Mono (falls back to
Segoe UI / Consolas when the fonts aren't installed).

`apply_theme(app, mode)` installs palette + stylesheet; `set_mode()` swaps the
colour tokens at runtime and `notifier.changed` fires so custom-painted
widgets can repaint.  Modules read tokens as `theme.TEXT`, `theme.ACCENT` ...
(attribute access at call time — don't `from gui.theme import TEXT`).
"""
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette

# ── Design tokens (from the redesign) ──────────────────────────────────────
# Names map to the mock-up's CSS variables:
#   BG=--bg  SURFACE=--p  SURFACE_2=--p2  BORDER=--ln  BORDER_2=--ln2
#   TEXT=--ink  TEXT_2/MUTED=--ink2  FAINT=--ink3  ACCENT=--ac
#   ACCENT_BG=--acs  ACCENT_LINE=--acl  ON_ACCENT=--onac  HOVER=--hv  INPUT=--inp
# Translucent tokens of the dark theme are pre-blended over SURFACE so they
# stay valid for QColor() as well as QSS.
LIGHT = {
    "BG": "#ECECE7", "SURFACE": "#FBFBF9", "SURFACE_2": "#F3F3EF",
    "HOVER": "#F0F0EB", "INPUT": "#FFFFFF",
    "BORDER": "#E2E1DB", "BORDER_2": "#CFCEC6",
    "TEXT": "#16181B", "TEXT_2": "#4D535A", "MUTED": "#4D535A", "FAINT": "#8A8F95",
    "DISABLED": "#B4B8BC",
    "ACCENT": "#1B2436", "ACCENT_HI": "#2A3650", "ACCENT_BG": "#E6E8ED",
    "ACCENT_LINE": "#C4C9D3", "ON_ACCENT": "#F4F5F7", "ACCENT_DIS": "#9AA1AF",
    "OK": "#2F7A4B", "OK_BG": "#E2EFE6",
    "WARN": "#86672E", "WARN_BG": "#F0EADD",
    "ERR": "#B3382E", "ERR_BG": "#F6E1DE", "ERR_LINE": "#E6BDB7",
    "SCROLL": "#CFCEC6", "SCROLL_HI": "#B4B3AA",
}
DARK = {
    "BG": "#0B0D0F", "SURFACE": "#131619", "SURFACE_2": "#181C20",
    "HOVER": "#1A1E22", "INPUT": "#0F1215",
    "BORDER": "#22272C", "BORDER_2": "#30363C",
    "TEXT": "#E7E9EB", "TEXT_2": "#A4ABB2", "MUTED": "#A4ABB2", "FAINT": "#6B737B",
    "DISABLED": "#4A525A",
    "ACCENT": "#B3BDD1", "ACCENT_HI": "#C6CEDF", "ACCENT_BG": "#23272B",
    "ACCENT_LINE": "#3D4149", "ON_ACCENT": "#121826", "ACCENT_DIS": "#4B5566",
    "OK": "#5DBB85", "OK_BG": "#1D2D28",
    "WARN": "#C7AA74", "WARN_BG": "#292824",
    "ERR": "#E0695E", "ERR_BG": "#302223", "ERR_LINE": "#5A3431",
    "SCROLL": "#39414A", "SCROLL_HI": "#4F5963",
}

VIDEO_BG = "#101316"   # video canvas stays dark in both themes

SANS_STACK = ["Instrument Sans", "Segoe UI", "Helvetica Neue", "Arial"]
MONO_STACK = ["JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"]

# Live tokens — populated by set_mode(); defaults keep static analysers happy.
BG = SURFACE = SURFACE_2 = HOVER = INPUT = BORDER = BORDER_2 = ""
TEXT = TEXT_2 = MUTED = FAINT = DISABLED = ""
ACCENT = ACCENT_HI = ACCENT_BG = ACCENT_LINE = ON_ACCENT = ACCENT_DIS = ""
OK = OK_BG = WARN = WARN_BG = ERR = ERR_BG = ERR_LINE = ""
SCROLL = SCROLL_HI = ""
STATUS_STYLE = {}
_mode = "light"


class _Notifier(QObject):
    changed = pyqtSignal(str)


notifier = _Notifier()


def mode():
    return _mode


def set_mode(new_mode):
    """Swap the live colour tokens. Returns the mode actually applied."""
    global _mode
    _mode = "dark" if new_mode == "dark" else "light"
    globals().update(DARK if _mode == "dark" else LIGHT)
    # Video-row status colours: (background, border, dot, text)
    STATUS_STYLE.clear()
    STATUS_STYLE.update({
        "needs":   (SURFACE, BORDER,      FAINT,  MUTED),
        "ready":   (SURFACE, BORDER,      ACCENT, TEXT),
        "running": (ACCENT_BG, ACCENT_LINE, ACCENT, TEXT),
        "done":    (SURFACE, BORDER,      OK,     TEXT),
        "error":   (ERR_BG, ERR_LINE,     ERR,    ERR),
    })
    return _mode


set_mode("light")


def set_tone(widget, tone, css=""):
    """Colour a widget's text by semantic tone (text / text2 / muted / faint /
    accent / ok / warn / err) via the global stylesheet, so it follows
    light/dark switches. `css` carries any non-colour inline styling."""
    widget.setProperty("tone", tone)
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)
    st = widget.style()
    st.unpolish(widget)
    st.polish(widget)
    widget.update()


def _assets():
    """Render the small raster assets QSS can't draw itself (checkbox tick,
    radio dot, combo / spin arrows) for the current mode. Returns
    {name: forward-slash path}. Each asset also gets an @2x twin for HiDPI."""
    import os
    import tempfile
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QBrush, QPainter, QPen, QPixmap
    from gui import icons

    folder = os.path.join(tempfile.gettempdir(), "mice_tracker_theme", _mode)
    os.makedirs(folder, exist_ok=True)
    out = {}

    def save(name, size, draw, height=None):
        height = height or size
        for scale, suffix in ((1, ""), (2, "@2x")):
            pm = QPixmap(size * scale, height * scale)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(scale, scale)
            draw(p, scale)
            p.end()
            pm.save(os.path.join(folder, f"{name}{suffix}.png"), "PNG")
        # quoted: the temp path may contain spaces
        out[name] = '"' + os.path.join(folder, f"{name}.png").replace("\\", "/") + '"'

    def box(checked, hover=False):
        def draw(p, _s):
            r = QRectF(0.5, 0.5, 13, 13)
            p.setPen(QPen(QColor(ACCENT if (checked or hover) else BORDER_2), 1))
            p.setBrush(QBrush(QColor(ACCENT if checked else INPUT)))
            p.drawRoundedRect(r, 3, 3)
            if checked:
                p.setBrush(Qt.NoBrush)
                pen = QPen(QColor(ON_ACCENT), 1.8)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawPolyline(*[QPointF(x, y) for x, y in ((3.6, 7.2), (6.0, 9.6), (10.4, 4.8))])
        return draw

    def radio(checked):
        def draw(p, _s):
            p.setPen(QPen(QColor(ACCENT if checked else BORDER_2), 1))
            p.setBrush(QBrush(QColor(INPUT)))
            p.drawEllipse(QRectF(0.5, 0.5, 13, 13))
            if checked:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(ACCENT)))
                p.drawEllipse(QRectF(3.5, 3.5, 7, 7))
        return draw

    def glyph(name, size, color):
        def draw(p, scale):
            p.drawPixmap(0, 0, icons.pixmap(name, size, color, dpr=scale))
        return draw

    def switch(on, disabled=False):
        def draw(p, _s):
            track = QColor(ACCENT if on else SCROLL)
            if disabled:
                track.setAlphaF(0.45)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(track))
            p.drawRoundedRect(QRectF(0, 0, 30, 18), 9, 9)
            p.setBrush(QBrush(QColor("#FFFFFF" if not disabled else "#EEEEEE")))
            p.drawEllipse(QRectF(14 if on else 2, 2, 14, 14))
        return draw

    save("switch_off", 30, switch(False), 18)
    save("switch_on", 30, switch(True), 18)
    save("switch_off_dis", 30, switch(False, True), 18)
    save("switch_on_dis", 30, switch(True, True), 18)
    save("check_off", 14, box(False))
    save("check_off_hover", 14, box(False, True))
    save("check_on", 14, box(True))
    save("radio_off", 14, radio(False))
    save("radio_on", 14, radio(True))
    save("arrow_down", 10, glyph("chevron_d", 10, FAINT))
    save("arrow_up", 10, glyph("chevron_u", 10, FAINT))
    save("step_minus", 12, glyph("minus", 12, TEXT_2))
    save("step_plus", 12, glyph("plus", 12, TEXT_2))
    return out


def _first_available(candidates):
    families = set(QFontDatabase().families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


def sans_family():
    return _first_available(SANS_STACK)


def mono_family():
    return _first_available(MONO_STACK)


def _palette():
    p = QPalette()
    p.setColor(QPalette.Window, QColor(BG))
    p.setColor(QPalette.WindowText, QColor(TEXT))
    p.setColor(QPalette.Base, QColor(INPUT))
    p.setColor(QPalette.AlternateBase, QColor(SURFACE_2))
    p.setColor(QPalette.Text, QColor(TEXT))
    p.setColor(QPalette.Button, QColor(SURFACE))
    p.setColor(QPalette.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ToolTipBase, QColor(TEXT))
    p.setColor(QPalette.ToolTipText, QColor(SURFACE))
    p.setColor(QPalette.Highlight, QColor(ACCENT))
    p.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    p.setColor(QPalette.Link, QColor(ACCENT))
    p.setColor(QPalette.PlaceholderText, QColor(FAINT))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(DISABLED))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DISABLED))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(DISABLED))
    return p


def _qss(sans, mono, A):
    return f"""
* {{ font-family: "{sans}"; }}
QWidget {{ font-size: 12px; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {TEXT}; color: {SURFACE}; border: 0; padding: 4px 6px; }}

/* ── Menus ────────────────────────────────────────────────────── */
QMenuBar {{ background: transparent; border: 0; padding: 0; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; color: {TEXT_2}; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {HOVER}; color: {TEXT}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 5px; color: {TEXT}; }}
QMenu::item:selected {{ background: {HOVER}; color: {TEXT}; }}
QMenu::item:disabled {{ color: {DISABLED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; font-size: 11px; min-height: 26px; }}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ font-size: 11px; color: {MUTED}; }}

/* ── Buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 3px 10px; color: {TEXT};
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {ACCENT_BG}; }}
QPushButton:disabled {{ color: {DISABLED}; background: {SURFACE_2}; border-color: {BORDER}; }}
QPushButton:checked {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:focus {{ outline: none; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton[primary="true"]:disabled {{ background: {ACCENT_DIS}; border-color: {ACCENT_DIS}; color: {ON_ACCENT}; }}
QPushButton[flat="true"], QPushButton[ghost="true"] {{
    background: transparent; border: 1px solid transparent; color: {MUTED};
}}
QPushButton[flat="true"]:hover, QPushButton[ghost="true"]:hover {{ background: {HOVER}; }}
QToolButton {{ background: transparent; border: 0; border-radius: 4px; padding: 2px; color: {TEXT_2}; }}
QToolButton:hover {{ background: {HOVER}; }}

/* ── Inputs ───────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 2px 6px; min-height: 22px; selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {SURFACE_2}; color: {DISABLED}; border-color: {BORDER};
}}
QLineEdit:read-only {{ background: {SURFACE_2}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox::down-arrow {{ image: url({A["arrow_down"]}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER_2}; selection-background-color: {HOVER};
    selection-color: {TEXT}; outline: 0;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: 0; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({A["arrow_up"]}); width: 8px; height: 8px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({A["arrow_down"]}); width: 8px; height: 8px; }}
QPlainTextEdit, QTextEdit {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px;
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}

/* ── Checkbox / radio ─────────────────────────────────────────── */
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{ image: url({A["check_off"]}); }}
QCheckBox::indicator:unchecked:hover {{ image: url({A["check_off_hover"]}); }}
QCheckBox::indicator:checked {{ image: url({A["check_on"]}); }}
QCheckBox[switch="true"] {{ spacing: 8px; }}
QCheckBox[switch="true"]::indicator {{ width: 30px; height: 18px; }}
QCheckBox[switch="true"]::indicator:unchecked {{ image: url({A["switch_off"]}); }}
QCheckBox[switch="true"]::indicator:unchecked:hover {{ image: url({A["switch_off"]}); }}
QCheckBox[switch="true"]::indicator:checked {{ image: url({A["switch_on"]}); }}
QCheckBox[switch="true"]::indicator:unchecked:disabled {{ image: url({A["switch_off_dis"]}); }}
QCheckBox[switch="true"]::indicator:checked:disabled {{ image: url({A["switch_on_dis"]}); }}
QRadioButton::indicator:unchecked {{ image: url({A["radio_off"]}); }}
QRadioButton::indicator:checked {{ image: url({A["radio_on"]}); }}

/* ── Sliders / progress ───────────────────────────────────────── */
QSlider::groove:horizontal {{ height: 4px; background: {BORDER_2}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; border: 2px solid {SURFACE}; width: 10px; height: 10px;
    margin: -6px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}
QProgressBar {{
    background: {BORDER}; border: 0; border-radius: 2px; max-height: 4px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

/* ── Tabs (underline style) ───────────────────────────────────── */
QTabWidget::pane {{ border: 0; border-top: 1px solid {BORDER}; background: {SURFACE}; top: -1px; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {FAINT}; padding: 8px 14px; margin-right: 2px;
    border: 0; border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:disabled {{ color: {DISABLED}; }}

/* ── Group boxes → flat sections ──────────────────────────────── */
QGroupBox {{
    background: transparent; border: 0; border-top: 1px solid {BORDER};
    margin-top: 12px; padding: 10px 2px 4px 2px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 4px 0 0; color: {TEXT}; }}

/* ── Scroll areas / bars ──────────────────────────────────────── */
QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 28px; margin: 1px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 4px; min-width: 28px; margin: 1px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HI}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── Tables / lists ───────────────────────────────────────────── */
QTableView, QTableWidget, QListView, QListWidget, QTreeView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: {HOVER}; alternate-background-color: {SURFACE_2};
    selection-background-color: {ACCENT_BG}; selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE_2}; color: {MUTED}; font-weight: 500; padding: 5px 8px;
    border: 0; border-bottom: 1px solid {BORDER};
}}
QTableCornerButton::section {{ background: {SURFACE_2}; border: 0; }}

/* ── Splitter ─────────────────────────────────────────────────── */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:hover {{ background: {ACCENT}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ── Named parts used by the redesign ─────────────────────────── */
QLabel[role="pane-header"] {{
    color: {TEXT}; font-family: "{mono}"; font-size: 11px; font-weight: 600; letter-spacing: 1px;
    padding: 0 12px; background: {SURFACE}; border-bottom: 1px solid {BORDER};
}}
QLabel[role="muted"] {{ color: {FAINT}; font-size: 11px; }}
QLabel[role="mono"] {{ font-family: "{mono}"; }}
QLabel[role="caps"] {{
    font-family: "{mono}"; font-size: 11px; font-weight: 600; letter-spacing: 1px; color: {TEXT};
}}
QLabel[role="faint"] {{ color: {FAINT}; }}
QLabel[role="faint11"] {{ color: {FAINT}; font-size: 11px; }}
QLabel[role="muted10"] {{ color: {MUTED}; font-size: 10px; }}
QLabel[role="muted11"] {{ color: {MUTED}; font-size: 11px; }}
QLabel[role="metric-name"], QLabel[role="metric-val"] {{ border: 0; background: transparent; }}
QLabel[role="metric-name"] {{ color: {TEXT_2}; }}
QLabel[state="ok"] {{ color: {OK}; }}
QLabel[state="err"] {{ color: {ERR}; }}
QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame[role="hline"] {{ background: {BORDER}; border: 0; }}
QWidget[role="metric-row"] {{ border-bottom: 1px dashed {BORDER}; }}
QWidget[role="meas-section"] {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#GridCells {{ background: {BORDER}; border: 1px solid {BORDER}; border-radius: 7px; }}
QWidget#GridCell {{ background: {SURFACE}; }}
QLabel[role="cellcap"] {{ font-size: 10px; color: {FAINT}; letter-spacing: 0.5px; background: transparent; }}
QFrame#HeroTile {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; }}
QFrame#HeroTile QLabel {{ background: transparent; }}
QLabel#AccentDot {{ background: {ACCENT}; border-radius: 3px; }}
QLabel#ZonePill {{ border-radius: 5px; padding: 0 9px; font-size: 11.5px; font-weight: 600;
    background: {SURFACE_2}; color: {TEXT_2}; }}
QLabel#ZonePill[zone="center"] {{ background: {ACCENT_BG}; color: {ACCENT}; }}

/* Semantic text tones — see set_tone() */
QWidget[tone="text"] {{ color: {TEXT}; }}
QWidget[tone="text2"] {{ color: {TEXT_2}; }}
QWidget[tone="muted"] {{ color: {MUTED}; }}
QWidget[tone="faint"] {{ color: {FAINT}; }}
QWidget[tone="accent"] {{ color: {ACCENT}; }}
QWidget[tone="ok"] {{ color: {OK}; }}
QWidget[tone="warn"] {{ color: {WARN}; }}
QWidget[tone="err"] {{ color: {ERR}; }}

/* Header */
QWidget#AppHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#HeaderSep {{ background: {BORDER}; border: 0; }}
QLabel#BrandMark {{ background: {ACCENT}; border-radius: 6px; }}
QLabel#BrandName {{ font-size: 13px; font-weight: 700; }}
QLabel#BrandTag {{
    font-family: "{mono}"; font-size: 9px; letter-spacing: 1px; color: {FAINT};
}}
QToolButton#TestPicker {{
    background: {SURFACE_2}; border: 1px solid {BORDER_2}; border-radius: 6px;
    padding: 0 8px; font-weight: 600; color: {TEXT};
}}
QToolButton#TestPicker:hover {{ background: {HOVER}; }}
QToolButton#TestPicker::menu-indicator {{ image: none; width: 0; }}
QLabel#Crumb {{ font-family: "{mono}"; font-size: 11px; font-weight: 500; color: {TEXT}; }}
QLabel#CrumbSep {{ color: {BORDER_2}; }}
QLabel#StatusPill {{
    background: {ACCENT_BG}; color: {TEXT}; border: 1px solid {ACCENT_LINE};
    border-radius: 11px; padding: 0 10px; font-size: 11px;
}}
QFrame#Segmented {{ border: 1px solid {BORDER_2}; border-radius: 6px; background: {SURFACE_2}; }}
QFrame#Segmented QPushButton {{
    border: 0; border-radius: 0; padding: 0 10px; background: transparent;
    color: {FAINT}; font-size: 11px; min-height: 0;
}}
QFrame#Segmented QPushButton:hover {{ background: {HOVER}; color: {TEXT}; }}
QFrame#Segmented QPushButton:checked {{ background: {SURFACE}; color: {TEXT}; font-weight: 600; }}

/* Launcher */
QLabel#LauncherMark {{ background: {ACCENT}; border-radius: 8px; }}
QLabel#LauncherTitle {{ font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
QLabel#LauncherSub {{ font-size: 12px; color: {MUTED}; }}
QPushButton#TestCard {{
    font-size: 13px; font-weight: 600; background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#TestCard:hover {{ border-color: {ACCENT}; background: {ACCENT_BG}; }}
QPushButton#TestCard:disabled {{ color: {FAINT}; font-weight: 400; background: {SURFACE_2}; }}

/* Redesign v2 building blocks */
QWidget#FooterBar {{ background: transparent; }}
QWidget#FooterBar QLabel {{ font-size: 10.5px; color: {TEXT_2}; background: transparent; }}
QCheckBox[chip="true"] {{
    spacing: 0; padding: 0 9px; height: 22px; border-radius: 11px; font-size: 11px;
    background: {SURFACE_2}; color: {FAINT}; border: 1px solid {BORDER};
}}
QCheckBox[chip="true"]:checked {{ background: {ACCENT_BG}; color: {ACCENT}; border: 1px solid {ACCENT_LINE}; }}
QCheckBox[chip="true"]::indicator {{ width: 0px; height: 0px; }}
QFrame#Section {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 0; }}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; background: transparent; }}
QLabel#PathBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 0 8px;
    font-family: "{mono}"; font-size: 11px; color: {TEXT};
}}
QFrame#ExportSeg {{ border: 1px solid {BORDER_2}; border-radius: 4px; background: {SURFACE}; }}
QPushButton[segbtn="true"] {{
    border: 0; border-left: 1px solid {BORDER}; border-radius: 0; background: {SURFACE}; padding: 0 8px;
    font-size: 11px; min-height: 0; color: {TEXT};
}}
QPushButton[segbtn="true"]:first-child {{ border-left: 0; }}
QPushButton[segbtn="true"]:hover {{ background: {HOVER}; }}
QPushButton[graphitem="true"] {{
    border: 0; border-radius: 4px; background: transparent; text-align: left; padding: 0;
}}
QPushButton[graphitem="true"]:hover {{ background: {BORDER}; }}
QPushButton[graphitem="true"]:checked {{ background: {ACCENT_BG}; }}
QLabel[role="graphname"] {{ font-size: 12px; font-weight: 500; color: {TEXT}; background: transparent; }}
QLabel[role="graphdesc"] {{ font-size: 10.5px; color: {FAINT}; background: transparent; }}
QPushButton[graphitem="true"]:checked QLabel[role="graphname"] {{ color: {ACCENT}; }}
QWidget#OutFooter {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QWidget#SubTabHeader {{ background: {SURFACE_2}; border-bottom: 1px solid {BORDER}; }}
QPushButton[subtab="true"] {{
    border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent;
    color: {FAINT}; padding: 0 10px; font-size: 12px; min-height: 0; height: 37px;
}}
QPushButton[subtab="true"]:hover {{ color: {TEXT}; background: transparent; }}
QPushButton[subtab="true"]:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabWidget#ExcelTabs::pane {{ border: 0; background: {BG}; top: 0; }}
QWidget#OutPage {{ background: {BG}; }}
QFrame#OutPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 0; }}
QWidget#OutPanelBar {{ background: {SURFACE}; border: 0; border-bottom: 1px solid {BORDER}; }}
QLabel#OutPanelTitle {{ font-size: 13px; font-weight: 600; background: transparent; }}
QTableWidget[out="true"] {{
    background: {SURFACE}; border: 0; border-radius: 0; gridline-color: {BORDER};
    alternate-background-color: {SURFACE}; selection-background-color: {ACCENT_BG}; selection-color: {TEXT};
    outline: 0;
}}
QTableWidget[out="true"] QHeaderView::section {{
    background: {SURFACE_2}; color: {TEXT_2}; font-weight: 500; font-size: 11px; padding: 0 14px;
    border: 0; border-bottom: 1px solid {BORDER}; height: 30px;
}}
QTableWidget[out="true"]::item {{ padding: 0 14px; border-bottom: 1px solid {BORDER}; }}
QTableWidget[out="true"]::item:hover {{ background: {SURFACE_2}; }}
QWidget#MainTabHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QPushButton[maintab="true"] {{
    border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent;
    color: {FAINT}; padding: 0 12px; font-size: 12.5px; min-height: 0; height: 39px;
}}
QPushButton[maintab="true"]:hover {{ color: {TEXT}; background: transparent; }}
QPushButton[maintab="true"]:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QLabel#MetaChip {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 4px; padding: 0 8px; font-size: 11px;
}}
QLabel#TrackedChip {{ background: {OK_BG}; border-radius: 11px; padding: 0 10px; font-size: 11px; }}
QSpinBox, QDoubleSpinBox {{ font-family: "{mono}"; font-size: 11px; }}
QAbstractSpinBox[stepper="true"] {{ padding: 0 28px; qproperty-alignment: AlignCenter; }}
QAbstractSpinBox[stepper="true"]::down-button {{
    subcontrol-origin: border; subcontrol-position: left; width: 26px;
    border: 0; border-right: 1px solid {BORDER}; background: {SURFACE_2};
    border-top-left-radius: 5px; border-bottom-left-radius: 5px;
}}
QAbstractSpinBox[stepper="true"]::up-button {{
    subcontrol-origin: border; subcontrol-position: right; width: 26px;
    border: 0; border-left: 1px solid {BORDER}; background: {SURFACE_2};
    border-top-right-radius: 5px; border-bottom-right-radius: 5px;
}}
QAbstractSpinBox[stepper="true"]::down-arrow {{ image: url({A["step_minus"]}); width: 12px; height: 12px; }}
QAbstractSpinBox[stepper="true"]::up-arrow {{ image: url({A["step_plus"]}); width: 12px; height: 12px; }}
QPushButton[link="true"] {{
    background: transparent; border: 0; color: {ACCENT}; padding: 0 6px; min-height: 0; font-size: 11px;
}}
QPushButton[link="true"]:hover {{ background: {ACCENT_BG}; }}
QPushButton[link="true"]:disabled {{ color: {DISABLED}; }}
QFrame#SegTabs {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame#SegTabs QPushButton {{
    border: 1px solid transparent; border-radius: 4px; background: transparent; color: {FAINT};
    font-size: 11px; min-height: 0; height: 22px; padding: 0 4px;
}}
QFrame#SegTabs QPushButton:hover {{ color: {TEXT}; }}
QFrame#SegTabs QPushButton:checked {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; }}
QPushButton[tile="true"] {{
    text-align: left; padding: 0 10px; border-radius: 6px; font-size: 11.5px;
    background: {SURFACE}; color: {TEXT_2}; border: 1px solid {BORDER_2};
}}
QPushButton[tile="true"]:hover {{ background: {HOVER}; }}
QPushButton[tile="true"]:checked {{ background: {ACCENT_BG}; color: {ACCENT}; border: 1px solid {ACCENT_LINE}; }}
QPushButton#ArenaMode {{
    background: {INPUT}; border: 1px solid {BORDER_2}; border-radius: 6px; padding: 0 24px 0 8px;
    text-align: left; color: {TEXT}; font-size: 12px;
}}
QPushButton#ArenaMode:hover {{ background: {INPUT}; border-color: {ACCENT_LINE}; }}
QPushButton#ArenaMode:disabled {{ background: {SURFACE_2}; color: {DISABLED}; border-color: {BORDER}; }}
QPushButton#ArenaMode::menu-indicator {{ image: url({A["arrow_down"]}); subcontrol-origin: padding;
    subcontrol-position: right center; right: 8px; width: 10px; height: 10px; }}
QFrame#SensBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame#SensBox QLabel {{ background: transparent; }}
QLabel[role="sensval"] {{ font-family: "{mono}"; font-size: 13px; font-weight: 500; color: {ACCENT}; }}
QLabel[role="valuepill"] {{
    font-family: "{mono}"; font-size: 11px; padding: 2px 0; border-radius: 4px;
    background: {SURFACE_2}; border: 1px solid {BORDER};
}}
QLabel[role="hint9"] {{ font-size: 9.5px; color: {FAINT}; }}
QLabel[role="subcaps"] {{
    font-family: "{mono}"; font-size: 9.5px; letter-spacing: 1px; color: {FAINT};
}}

QToolButton[ibtn] {{ background: transparent; border: 0; border-radius: 5px; padding: 0; }}
QToolButton[ibtn]:hover {{ background: {HOVER}; }}
QToolButton[ibtn="danger"]:hover {{ background: {ERR_BG}; }}
QToolButton[ibtn="border"] {{ border: 1px solid {BORDER_2}; background: {SURFACE}; }}
QToolButton[ibtn]:disabled {{ background: transparent; }}
QWidget#PaneHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QLabel[role="keyhint"] {{
    font-family: "{mono}"; font-size: 10px; color: {FAINT}; padding: 0 4px;
    border: 1px solid {BORDER}; border-radius: 3px; background: transparent;
}}
QLabel[role="countpill"] {{
    font-family: "{mono}"; font-size: 10px; color: {FAINT}; padding: 1px 6px;
    border-radius: 8px; background: {SURFACE_2}; border: 1px solid {BORDER};
}}
QLabel[role="statlabel"] {{ font-size: 9.5px; color: {FAINT}; letter-spacing: 0.5px; }}
QFrame#StatGrid {{ background: {BORDER}; border: 0; border-bottom: 1px solid {BORDER}; }}
QWidget#StatCell {{ background: {SURFACE}; }}
QFrame#RunPanel {{ background: {SURFACE_2}; border-top: 1px solid {BORDER}; }}
QFrame#VideoRow {{ background: transparent; border: 1px solid transparent; border-radius: 7px; }}
QFrame#VideoRow:hover {{ background: {HOVER}; }}
QFrame#VideoRow[selected="true"] {{ background: {ACCENT_BG}; border: 1px solid {ACCENT_LINE}; }}
QLabel#RowName {{ color: {TEXT}; background: transparent; }}
QLabel#RowState {{ font-size: 10.5px; background: transparent; color: {TEXT_2}; }}
QLabel#RowState[vstate="done"] {{ color: {OK}; }}
QLabel#RowState[vstate="running"] {{ color: {ACCENT}; }}
QLabel#RowState[vstate="ready"] {{ color: {TEXT_2}; }}
QLabel#RowState[vstate="needs"] {{ color: {FAINT}; }}
QLabel#RowState[vstate="error"] {{ color: {ERR}; }}

/* Experiment tab surfaces (objectNames set in gui/experiment*_tab.py) */
QWidget#Pane {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#ResultCard {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QFrame#TransportCard {{ background: {SURFACE}; border: 0; border-top: 1px solid {BORDER}; }}
QFrame#TransportGroup {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 7px; }}
QFrame#FrameBlock {{ background: transparent; border: 0; border-left: 1px solid {BORDER}; }}
QFrame#FrameBlock QLabel {{ background: transparent; }}
QLabel#ErrDot {{ background: {ERR}; border-radius: 2px; }}
QToolButton[ibtn="primary"] {{ background: {ACCENT}; border-radius: 5px; }}
QToolButton[ibtn="primary"]:hover {{ background: {ACCENT_HI}; }}
QToolButton[ibtn="primary"]:disabled {{ background: {ACCENT_DIS}; }}
QLabel[role="scrub"] {{ font-family: "{mono}"; font-size: 19px; font-weight: 500; color: {TEXT}; letter-spacing: -0.3px; }}
QLabel[role="scrubtotal"] {{ font-family: "{mono}"; font-size: 11.5px; color: {FAINT}; }}
QLabel[role="slidervalue"] {{ font-family: "{mono}"; font-size: 10.5px; color: {TEXT_2}; }}
QLabel[role="frame"] {{ font-family: "{mono}"; font-size: 11.5px; color: {TEXT}; }}
QGroupBox#StepGroup {{
    margin: 0; background: transparent; border: 0; border-bottom: 1px solid {BORDER};
    padding: 46px 0px 0px 0px; font-size: 12px; color: {TEXT};
}}
QGroupBox#StepGroup::title {{ subcontrol-origin: margin; height: 0px; padding: 0; }}
QToolButton#InfoBtn {{
    color: {MUTED}; font-size: 12px; padding: 0; background: transparent;
    border: 1px solid {BORDER_2}; border-radius: 9px;
}}
QToolButton#InfoBtn:hover {{ background: {ACCENT_BG}; border-color: {ACCENT}; color: {TEXT}; }}
QToolButton#InfoBtn:pressed {{ background: {ACCENT_LINE}; }}

/* Right-hand measurements sidebar */
QScrollArea#Measurements {{ background: {SURFACE}; border-left: 1px solid {BORDER}; }}
QWidget#MeasBody {{ background: {SURFACE}; }}
"""


def apply_theme(app, new_mode=None):
    """Install palette, font and global stylesheet on the QApplication.

    Pass `new_mode` ("light" / "dark") to switch tokens first; the
    `notifier.changed` signal is emitted so custom-painted widgets refresh.
    """
    if new_mode is not None:
        set_mode(new_mode)
    app.setStyle("Fusion")
    sans, mono = sans_family(), mono_family()
    font = QFont(sans)
    font.setPixelSize(12)
    app.setFont(font)
    app.setPalette(_palette())
    app.setStyleSheet(_qss(sans, mono, _assets()))
    notifier.changed.emit(_mode)
