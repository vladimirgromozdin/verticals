"""A goal opened with Space moves as a clicked goal does: it stays lit through the opening, over the board's veil."""
import struct
import zlib

import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession


@pytest.fixture
def ui_reduced_motion() -> str:
    return 'no-preference'


def _brightest_green(png: bytes) -> int:
    """The brightest green channel of an 8-bit RGB or RGBA PNG, as Chromium writes it: no interlace."""
    pos, data, width, channels = 8, b'', 0, 4
    while pos < len(png):
        size, kind = struct.unpack('>I4s', png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + size]
        if kind == b'IHDR':
            width, colour = struct.unpack('>I', body[:4])[0], body[9]
            channels = 4 if colour == 6 else 3
        elif kind == b'IDAT':
            data += body
        pos += size + 12
    raw, stride, prev, best = zlib.decompress(data), width * channels, bytearray(width * channels), 0
    for y in range(len(raw) // (stride + 1)):
        kind, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - channels] if i >= channels else 0
            b, c = prev[i], prev[i - channels] if i >= channels else 0
            if kind == 1: line[i] = (line[i] + a) & 255
            elif kind == 2: line[i] = (line[i] + b) & 255
            elif kind == 3: line[i] = (line[i] + (a + b) // 2) & 255
            elif kind == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        best = max(best, max(line[1::channels]))
        prev = line
    return best


def _brightest(page, box) -> int:
    """The brightest the goal's title gets: its words."""
    return _brightest_green(page.screenshot(clip={'x': box['x'] + 30, 'y': box['y'] + 4, 'width': 80, 'height': box['height'] - 8}))


def test_a_goal_opened_with_space_stays_lit_while_it_opens(ui_f2: UiSession):
    page = ui_f2.page
    page.emulate_media(color_scheme='dark')
    page.wait_for_selector('.goal-card__row')
    row = page.locator('[data-keyboard-column][data-vertical="month"] [data-section="planned"] > .goal-card > .goal-card__row').nth(1)
    row.focus()
    page.wait_for_timeout(300)
    before = _brightest(page, row.bounding_box())
    page.keyboard.press('Space')
    seen = []
    for _ in range(10):
        seen.append(_brightest(page, row.bounding_box()))
    expect(page.locator('#goal-detail')).to_be_visible()
    # A click on the goal shows a dimmer frame or two as the card starts to move, while the screenshot's clip catches the
    # words mid-move; the board's veil over the card dimmed three or four in a row.
    assert sum(seen_ < before - 25 for seen_ in seen) <= 2, (before, seen)



def test_marking_done_and_back_never_steps_back(ui_f2: UiSession):
    """E twice: the goal goes down done, then comes back up not done, and never returns to a state it left."""
    page = ui_f2.page
    page.wait_for_selector('.goal-card__row')
    rows = '[data-keyboard-column][data-vertical="month"] [data-section="planned"] > .goal-card'
    first = page.locator(f'{rows} > .goal-card__row').first
    goal = first.evaluate('el => el.closest("[data-goal-id]").dataset.goalId')
    page.evaluate('''([rows, goal]) => {
        window.__states = []
        const read = () => {
            const cards = [...document.querySelectorAll(rows)]
            const card = cards.find((c) => c.dataset.goalId === goal)
            if (!card) return
            const state = `${cards.indexOf(card)}:${card.querySelector('[data-cap=complete]').getAttribute('aria-checked')}`
            if (window.__states.at(-1) !== state) window.__states.push(state)
        }
        read()
        new MutationObserver(read).observe(document.body, { subtree: true, childList: true, attributes: true })
    }''', [rows, goal])
    # The hosted board answers in about 0.3 s, and the change feed rings after each write: a board asked for after the
    # first E lands after the second.
    def slow(route):
        answer = route.fetch()  # the board as it is now, handed over late
        page.wait_for_timeout(700)
        route.fulfill(response=answer)
    page.route('**/api/board?*', slow)
    first.focus()
    page.keyboard.press('e')
    page.wait_for_timeout(450)  # it goes down
    page.keyboard.press('e')
    page.wait_for_timeout(2500)  # it comes back; the feed's reloads land meanwhile
    states = page.evaluate('window.__states')
    done = [s.endswith('true') for s in states]
    # false… then true… then false…: one change each way, never back.
    flips = sum(1 for a, b in zip(done, done[1:]) if a != b)
    assert flips == 2, states
