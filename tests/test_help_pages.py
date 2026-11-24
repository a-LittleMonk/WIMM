"""The Help pages: every link and image resolves, every experiment has a page,
and search finds what it should."""
import os
import re

import pytest

from gui.help_dialog import HELP_DIR, load_pages, plain_text, search
from experiments.registry import KEYS

PAGES = load_pages()
IDS = {p["id"] for p in PAGES} | {f"settings-{k}" for k in KEYS}


def test_pages_load_with_unique_ids():
    ids = [p["id"] for p in PAGES]
    assert len(ids) == len(set(ids))
    assert "welcome" in ids


def test_every_experiment_has_a_guide_page():
    for k in KEYS:
        assert f"exp-{k}" in IDS, k


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p["id"])
def test_links_and_images_resolve(page):
    for target in re.findall(r"href=['\"]topic:([^'\"]+)['\"]", page["html"]):
        assert target in IDS, f"{page['id']} links to missing page {target}"
    for src in re.findall(r"<img[^>]+src=['\"]([^'\"]+)['\"]", page["html"]):
        assert os.path.exists(os.path.join(HELP_DIR, src)), f"{page['id']}: missing {src}"


def test_search_ranks_title_matches_first():
    index = [{"id": p["id"], "title": p["title"], "keywords": p["keywords"],
              "text": plain_text(p["html"]), "text_l": plain_text(p["html"]).lower()}
             for p in PAGES]
    hits = search(index, "discrimination index")
    assert hits and hits[0][1] in ("exp-nor", "exp-nol")
    assert search(index, "fps override")
    assert search(index, "zzzz-not-a-word") == []
