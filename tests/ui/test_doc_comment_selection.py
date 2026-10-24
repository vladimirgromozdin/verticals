"""Selection-to-comment through real mouse and keyboard input, including an active editor."""

from pathlib import Path

import psycopg
import pytest
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession
from tests.ui.doc_comments import (
    BODY, CARD, LONG, MARK, SHORT, _card, _doc, _fresh_open, _open, _server_threads, _thread,
)


def _drag_words(page: Page, phrase: str) -> None:
    points = page.locator(BODY).evaluate(
        """(body, phrase) => {
          const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT)
          let node
          while ((node = walker.nextNode())) {
            const start = node.textContent.indexOf(phrase)
            if (start < 0) continue
            const range = document.createRange()
            range.setStart(node, start)
            range.setEnd(node, start + phrase.length)
            const rects = [...range.getClientRects()]
            const first = rects[0], last = rects.at(-1)
            return { x1: first.left + .5, y1: first.top + first.height / 2,
                     x2: last.right - .5, y2: last.top + last.height / 2 }
          }
          throw new Error('Missing phrase: ' + phrase)
        }""",
        phrase,
    )
    page.mouse.move(points["x1"], points["y1"])
    page.mouse.down()
    page.mouse.move(points["x2"], points["y2"], steps=12)
    page.mouse.up()
    assert page.evaluate("getSelection().toString()") == phrase


@pytest.mark.parametrize("mode,width", [("reading", 1458), ("editing", 1458), ("marked", 1458), ("keyboard", 1458), ("reading", 390), ("multiline", 1458), ("multiline", 390)])
def test_selected_words_can_always_be_commented(ui_f2: UiSession, mode: str, width: int) -> None:
    session, page = ui_f2, ui_f2.page
    page.set_viewport_size({"width": width, "height": 844 if width == 390 else 779})
    phrase = "The release" if mode == "keyboard" else "Added text." if mode == "editing" else "the sample board"
    if mode == "multiline":
        phrase = SHORT.split("\n\n")[0]
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc = _doc(conn, "syn-selection/plan.md", "Selection review", SHORT)
        if mode == "marked":
            _thread(conn, doc, phrase, "An earlier note.")
    page.reload()
    _open(page, doc)
    if mode in ("editing", "keyboard"):
        page.locator(f"{BODY} p").first.click(position={"x": 2, "y": 8})
        expect(page.locator(BODY)).to_have_attribute("contenteditable", "true")
        if mode == "editing":
            page.keyboard.press("End")
            page.keyboard.type(" Added text.")
    if mode == "keyboard":
        page.keyboard.press("Home")
        for _ in phrase:
            page.keyboard.press("Shift+ArrowRight")
        assert page.evaluate("getSelection().toString()") == phrase
    else:
        _drag_words(page, phrase)

    shots = Path("artifacts/doc-selection")
    shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shots / f"{mode}-{width}.png"), animations="disabled")
    expect(page.locator('[data-cap="comment-selection"]')).to_be_visible()
    button = page.locator('[data-cap="comment-selection"]').bounding_box()
    words = page.evaluate("""() => {
      const range = getSelection().getRangeAt(0)
      const rect = range.getBoundingClientRect()
      return { right: rect.right, bottom: rect.bottom, lines: range.getClientRects().length }
    }""")
    assert button and abs(button["x"] + button["width"] / 2 - words["right"]) < 2
    assert 8 <= button["y"] - words["bottom"] <= 12
    assert 8 <= button["x"] and button["x"] + button["width"] <= width - 8
    if mode == "multiline":
        assert words["lines"] > 1
    expect(page.locator(CARD)).to_have_count(0)
    if mode == "keyboard":
        page.locator('[data-cap="comment-selection"]').focus()
        page.keyboard.press("Enter")
    else:
        page.locator('[data-cap="comment-selection"]').click()
    card = _card(page)
    expect(card).to_have_attribute("data-kind", "new")
    expect(page.locator(BODY)).to_have_attribute("contenteditable", "false")
    expect(page.locator(f'{BODY} {MARK}[data-thread-id="draft"]')).to_have_text(phrase)
    card.locator('[data-role="comment-field"]').fill("Clarify these words.")
    page.keyboard.press("Enter")
    expect(page.locator(CARD)).to_have_count(0)

    _fresh_open(session, doc)
    if mode == "editing":
        expect(page.locator(BODY)).to_contain_text(" Added text.")
    saved = [t for t in _server_threads(session, doc) if t["messages"][0]["body"] == "Clarify these words."]
    assert len(saved) == 1 and saved[0]["anchor"]["quote"] == phrase
    page.locator(f'{BODY} {MARK}[data-thread-id="{saved[0]["id"]}"]').click()
    expect(_card(page)).to_contain_text("Clarify these words.")
    page.screenshot(path=str(shots / f"{mode}-{width}-saved.png"), animations="disabled")


def test_comment_button_follows_selection_changes(ui_f2: UiSession) -> None:
    session, page = ui_f2, ui_f2.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc = _doc(conn, "syn-selection/clear.md", "Selection changes", SHORT)
    page.reload()
    _open(page, doc)
    _drag_words(page, "the sample board")
    expect(page.locator('[data-cap="comment-selection"]')).to_be_visible()
    page.locator('[data-role="doc-title"]').click()
    expect(page.locator('[data-cap="comment-selection"]')).to_have_count(0)
    assert _server_threads(session, doc) == []


def test_comment_button_closes_when_its_words_scroll_away(ui_f2: UiSession) -> None:
    session, page = ui_f2, ui_f2.page
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        doc = _doc(conn, "syn-selection/scroll.md", "Long selection review", LONG)
    page.reload()
    _open(page, doc)
    _drag_words(page, "The first words of the plan")
    expect(page.locator('[data-cap="comment-selection"]')).to_be_visible()
    page.locator(BODY).hover()
    page.mouse.wheel(0, 600)
    expect(page.locator('[data-cap="comment-selection"]')).to_have_count(0)
    assert _server_threads(session, doc) == []
