"""Help window (header → Help, F1).

Left: a search box and the table of contents. Right: the page, with
screenshots. Two kinds of pages:

* Guide pages — hand-written HTML in assets/help/pages/*.html (step-by-step
  guides, every experiment, every result, troubleshooting …), screenshots
  in assets/help/img. Each file starts with a header comment:

      <!--
      id: quick-start
      title: Quick start — your first analysis
      section: 1. Getting started
      order: 2
      keywords: first, tutorial, begin
      -->

* Settings reference — one page per experiment, built from the help text
  every setting registers through gui.info_box.attach_info_box (the same
  text as the ⓘ boxes), so it always matches the real controls.

Search covers titles, keywords and the full text of both kinds; results
show where the words occur, and the opened page highlights them.
Links between pages: <a href="topic:page-id">.
"""
import glob
import os
import re
from html import escape, unescape

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QKeySequence, QTextCharFormat, QTextDocument
from PyQt5.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QShortcut, QSplitter, QStackedWidget,
    QTextBrowser, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import logger
from gui import theme

HELP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "help")

# (tab title, module, class) — experiments in the Settings reference.
from experiments.registry import EXPERIMENTS as _REG

EXPERIMENTS = tuple(
    (title, "gui.open_field_tab" if key == "open_field" else module, tab)
    for key, title, module, _batch, tab in _REG
)
EXP_KEY = {title: key for key, title, *_ in _REG}
SETTINGS_SECTION = "99. Settings reference (every control)"

_cache = {}   # title -> list of (card_name, [(title, text), ...])


# ── Settings reference (built from the real UI) ──────────────────────────

def _gather(title, module, cls_name, config):
    if title in _cache:
        return _cache[title]
    import importlib
    from gui.info_box import collect_help
    cfg = dict(config or {})
    for k in ("last_video", "recent_videos"):
        cfg.pop(k, None)
    cards = []
    try:
        cls = getattr(importlib.import_module(module), cls_name)
        with collect_help() as c:
            tab = cls(cfg)
        # Merge repeated cards, keep first-seen order.
        order, merged = [], {}
        for name, items in c.items:
            if name not in merged:
                order.append(name)
                merged[name] = []
            merged[name].extend(items)
        # Same order as the cards appear on screen.
        ui = [getattr(g, "_help_name", None) for g in getattr(tab, "_cards", [])]
        order.sort(key=lambda nm: ui.index(nm) if nm in ui else len(ui))
        cards = [(n, merged[n]) for n in order]
        tab.hide()
        QTimer.singleShot(3000, tab.deleteLater)   # after its own deferred init
    except Exception as e:
        logger.warn(f"help: could not gather {title}: {e}", source="ui")
    _cache[title] = cards
    return cards


def _settings_html(title, cards):
    key = EXP_KEY.get(title, "")
    parts = [f"<h1>{escape(title)} — every setting</h1>",
             "<p>Every control of this experiment's configuration cards, in the "
             "order they appear, with the same explanation as its ⓘ box. "
             f"For how to use them step by step, see "
             f"<a href='topic:exp-{key}'>{escape(title)}</a> and "
             "<a href='topic:card-video'>Setting up a video</a>.</p>"]
    if not cards:
        parts.append(f"<p>No setting help available for {escape(title)}.</p>")
    for name, items in cards:
        parts.append(f"<h2>{escape(name)}</h2>")
        for t, text in items:
            body = escape(text).replace("\n", "<br>")
            parts.append(f"<p><b>{escape(t)}</b><br>{body}</p>")
    return "".join(parts)


# ── Guide pages ───────────────────────────────────────────────────────────

_HEADER = re.compile(r"^\s*<!--(.*?)-->", re.S)


def load_pages(folder=None):
    """[page dict] from assets/help/pages, in table-of-contents order."""
    folder = folder or os.path.join(HELP_DIR, "pages")
    pages = []
    for path in sorted(glob.glob(os.path.join(folder, "*.html"))):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            logger.warn(f"help page unreadable ({path}): {e}", source="ui")
            continue
        m = _HEADER.match(text)
        meta = {}
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
        pid = meta.get("id") or os.path.splitext(os.path.basename(path))[0]
        pages.append({
            "id": pid,
            "title": meta.get("title", pid),
            "section": meta.get("section", "Other"),
            "order": float(meta.get("order", 50)),
            "keywords": meta.get("keywords", ""),
            "html": text[m.end():] if m else text,
        })
    pages.sort(key=lambda p: (_section_key(p["section"]), p["order"], p["title"]))
    return pages


def _section_key(section):
    m = re.match(r"\s*(\d+)", section)
    return (int(m.group(1)) if m else 999, section)


def _section_label(section):
    return re.sub(r"^\s*\d+\.\s*", "", section)


def plain_text(html_text):
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html_text, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", unescape(t)).strip()


def search(index, query, limit=60):
    """[(score, page_id, snippet)] for pages holding every word of `query`
    (title / keywords / text, case-insensitive), best first."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    if not words:
        return []
    out = []
    for p in index:
        title, kw, body = p["title"].lower(), p["keywords"].lower(), p["text_l"]
        hay = f"{title} {kw} {body}"
        if not all(w in hay for w in words):
            continue
        score = 0
        for w in words:
            score += 30 * title.count(w) + 12 * kw.count(w) + min(body.count(w), 20)
        if query.lower().strip() in title:
            score += 60
        i = min((body.find(w) for w in words if w in body), default=-1)
        if i >= 0:
            a = max(0, i - 60)
            snippet = ("…" if a else "") + p["text"][a:i + 110].strip() + "…"
        else:
            snippet = p["text"][:150] + "…"
        out.append((score, p["id"], snippet))
    out.sort(key=lambda t: -t[0])
    return out[:limit]


def _css():
    return f"""
    body {{ color: {theme.TEXT}; font-size: 13px; }}
    h1 {{ font-size: 22px; margin: 4px 0 10px 0; }}
    h2 {{ font-size: 17px; margin: 18px 0 6px 0; }}
    h3 {{ font-size: 14px; margin: 14px 0 4px 0; }}
    p, li {{ line-height: 145%; }}
    a {{ color: {theme.ACCENT}; }}
    code, kbd {{ font-family: 'JetBrains Mono', Consolas, monospace; }}
    kbd {{ background-color: {theme.SURFACE_2}; }}
    td, th {{ padding: 4px 8px; }}
    th {{ background-color: {theme.SURFACE_2}; text-align: left; }}
    .cap {{ color: {theme.TEXT_2}; font-size: 12px; }}
    """


def _decorate(html_text):
    """Callout boxes: <div class="tip|note|warn">…</div> → a tinted table
    (QTextBrowser draws table backgrounds, not div ones)."""
    colours = {"tip": (theme.OK_BG, "Tip"), "note": (theme.ACCENT_BG, "Note"),
               "warn": (theme.WARN_BG, "Important")}

    def box(m):
        kind, body = m.group(1), m.group(2)
        bg, label = colours.get(kind, colours["note"])
        return (f"<table width='100%' cellpadding='9' cellspacing='0' "
                f"style='margin:8px 0;' bgcolor='{bg}'><tr><td>"
                f"<b>{label}.</b> {body}</td></tr></table>")
    return re.sub(r'<div class="(tip|note|warn)">(.*?)</div>', box, html_text, flags=re.S)


# ── Window ────────────────────────────────────────────────────────────────

class HelpDialog(QDialog):
    HOME = "welcome"

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help — Mice Tracker")
        self.resize(1180, 800)
        self._config = config
        self._pages = {p["id"]: p for p in load_pages()}
        self._order = list(self._pages)
        for title, module, cls_name in EXPERIMENTS:
            pid = f"settings-{EXP_KEY[title]}"
            self._pages[pid] = {"id": pid, "title": title, "section": SETTINGS_SECTION,
                                "order": 0, "keywords": "settings controls reference",
                                "html": None, "gather": (title, module, cls_name)}
            self._order.append(pid)
        self._settings_indexed = False
        self._index = []
        self._rebuild_index()
        self._history, self._pos = [], -1
        self._terms = []

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # left: search + contents / results
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search help…  (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        self.search_box.returnPressed.connect(self._open_first_result)
        lv.addWidget(self.search_box)
        self.lbl_hits = QLabel("")
        self.lbl_hits.setProperty("role", "hint9")
        lv.addWidget(self.lbl_hits)
        self.left_stack = QStackedWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        self.tree.itemActivated.connect(self._on_tree_clicked)
        self.results = QTextBrowser()        # results as links with highlighted snippets
        self.results.setOpenLinks(False)
        self.results.anchorClicked.connect(self._on_result_link)
        self._hits = []
        self.left_stack.addWidget(self.tree)
        self.left_stack.addWidget(self.results)
        lv.addWidget(self.left_stack, 1)
        split.addWidget(left)

        # right: navigation + page
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        nav = QHBoxLayout()
        self.btn_back = QPushButton("◀ Back")
        self.btn_fwd = QPushButton("Forward ▶")
        self.btn_home = QPushButton("Contents")
        for b, fn in ((self.btn_back, self._back), (self.btn_fwd, self._forward),
                      (self.btn_home, lambda: self.open_page(self.HOME))):
            b.setFixedHeight(28)
            b.clicked.connect(fn)
            nav.addWidget(b)
        self.lbl_where = QLabel("")
        self.lbl_where.setProperty("role", "hint9")
        nav.addSpacing(10)
        nav.addWidget(self.lbl_where, 1)
        rv.addLayout(nav)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setSearchPaths([HELP_DIR])
        self.view.anchorClicked.connect(self._on_link)
        rv.addWidget(self.view, 1)
        split.addWidget(right)
        split.setSizes([300, 880])

        self._fill_tree()
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self._back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self._forward)
        QShortcut(QKeySequence("Escape"), self.search_box, activated=self.search_box.clear)
        self.open_page(self.HOME)

    # ── contents ──────────────────────────────────────────────────────
    def _fill_tree(self):
        self.tree.clear()
        self._tree_items = {}
        sections = {}
        for pid in self._order:
            p = self._pages[pid]
            sec = p["section"]
            if sec not in sections:
                top = QTreeWidgetItem([_section_label(sec)])
                f = top.font(0); f.setBold(True); top.setFont(0, f)
                top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
                self.tree.addTopLevelItem(top)
                sections[sec] = top
            it = QTreeWidgetItem([p["title"]])
            it.setData(0, Qt.UserRole, pid)
            sections[sec].addChild(it)
            self._tree_items[pid] = it
        for top in sections.values():
            top.setExpanded(not top.text(0).startswith("Settings reference"))

    def _on_tree_clicked(self, item, _col=0):
        pid = item.data(0, Qt.UserRole)
        if pid:
            self.open_page(pid)
        else:
            item.setExpanded(not item.isExpanded())

    # ── pages ─────────────────────────────────────────────────────────
    def _page_html(self, pid):
        p = self._pages[pid]
        if p["html"] is None and p.get("gather"):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                title, module, cls_name = p["gather"]
                p["html"] = _settings_html(title, _gather(title, module, cls_name, self._config))
            finally:
                QApplication.restoreOverrideCursor()
        return p["html"] or ""

    def open_page(self, pid, terms=None, record=True):
        if pid not in self._pages:
            logger.warn(f"help: no page '{pid}'", source="ui")
            pid = self.HOME if self.HOME in self._pages else self._order[0]
        body = _decorate(self._page_html(pid))
        self.view.document().setDefaultStyleSheet(_css())
        self.view.setHtml(f"<html><body>{body}</body></html>")
        p = self._pages[pid]
        self.lbl_where.setText(f"{_section_label(p['section'])}  ›  {p['title']}")
        if record:
            self._history = self._history[:self._pos + 1] + [pid]
            self._pos = len(self._history) - 1
        self.btn_back.setEnabled(self._pos > 0)
        self.btn_fwd.setEnabled(self._pos < len(self._history) - 1)
        it = self._tree_items.get(pid)
        if it is not None:
            self.tree.setCurrentItem(it)
        self._terms = terms or []
        self._highlight()

    def _highlight(self):
        sels, first = [], None
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFE066"))
        fmt.setForeground(QColor("#111111"))
        doc = self.view.document()
        for term in self._terms:
            cur = doc.find(term, 0)
            while not cur.isNull():
                s = QTextEdit.ExtraSelection()
                s.cursor, s.format = cur, fmt
                sels.append(s)
                if first is None or cur.position() < first.position():
                    first = cur
                cur = doc.find(term, cur)
        self.view.setExtraSelections(sels)
        if first is not None:
            c = self.view.textCursor()
            c.setPosition(first.position())
            self.view.setTextCursor(c)
            self.view.ensureCursorVisible()
        else:
            self.view.verticalScrollBar().setValue(0)

    def _on_link(self, url):
        s = url.toString()
        if s.startswith("topic:"):
            self.open_page(s[len("topic:"):])
        elif url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif s.startswith("#"):
            self.view.scrollToAnchor(s[1:])

    def _back(self):
        if self._pos > 0:
            self._pos -= 1
            self.open_page(self._history[self._pos], record=False)

    def _forward(self):
        if self._pos < len(self._history) - 1:
            self._pos += 1
            self.open_page(self._history[self._pos], record=False)

    # ── search ────────────────────────────────────────────────────────
    def _rebuild_index(self):
        self._index = []
        for pid in self._order:
            p = self._pages[pid]
            if p["html"] is None:
                continue
            text = plain_text(p["html"])
            self._index.append({"id": pid, "title": p["title"] if not p.get("gather")
                                else f"{p['title']} — settings",
                                "keywords": p["keywords"], "text": text,
                                "text_l": text.lower()})

    def _index_settings(self):
        """First search: build the settings-reference pages so their text
        is searchable too (builds each experiment's controls once)."""
        if self._settings_indexed:
            return
        self._settings_indexed = True
        self.lbl_hits.setText("Indexing every setting…")
        QApplication.processEvents()
        for pid in self._order:
            if self._pages[pid].get("gather"):
                self._page_html(pid)
        self._rebuild_index()

    def _focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def _on_search(self, text):
        q = text.strip()
        if not q:
            self.left_stack.setCurrentWidget(self.tree)
            self.lbl_hits.setText("")
            return
        self._index_settings()
        hits = search(self._index, q)
        self._hits = [pid for _s, pid, _snip in hits]
        words = [w for w in q.split() if w]
        mark = re.compile("|".join(re.escape(w) for w in words), re.I) if words else None
        rows = []
        for _score, pid, snippet in hits:
            p = self._pages[pid]
            name = p["title"] + (" — settings" if p.get("gather") else "")
            snip = escape(snippet)
            if mark is not None:
                snip = mark.sub(lambda m: f"<span style='background-color:#FFE066;"
                                          f"color:#111'>{m.group(0)}</span>", snip)
            rows.append(f"<p style='margin:0 0 12px 0;'><a href='topic:{pid}'><b>{escape(name)}</b></a>"
                        f"<br><span style='color:{theme.TEXT_2}; font-size:11px;'>"
                        f"{escape(_section_label(p['section']))}</span><br>"
                        f"<span style='font-size:12px;'>{snip}</span></p>")
        self.results.document().setDefaultStyleSheet(f"a {{ color: {theme.ACCENT}; text-decoration: none; }}")
        self.results.setHtml("".join(rows))
        self.lbl_hits.setText(f"{len(hits)} page(s) found — click one, or press Enter for the first"
                              if hits else "Nothing found — try fewer or other words.")
        self.left_stack.setCurrentWidget(self.results)

    def _on_result_link(self, url):
        terms = [w for w in self.search_box.text().split() if w]
        self.open_page(url.toString()[len("topic:"):], terms=terms)

    def _open_first_result(self):
        if self.left_stack.currentWidget() is self.results and self._hits:
            self._on_result_link(QUrl("topic:" + self._hits[0]))

    # ── entry point ───────────────────────────────────────────────────
    def show_tab(self, title):
        """Open on the page of the experiment in use (`title` = its name)."""
        key = EXP_KEY.get(title)
        pid = f"exp-{key}" if key and f"exp-{key}" in self._pages else self.HOME
        self.open_page(pid)
        self.show()
        self.raise_()
        self.activateWindow()
