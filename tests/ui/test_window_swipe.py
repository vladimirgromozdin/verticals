"""A horizontal gesture changes windows once, including its trailing wheel events."""

import httpx
import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import open_page


def _windows(session: UiSession) -> None:
    headers = {"Authorization": f"Bearer {session.backend.token}"}
    goal = httpx.post(f"{session.backend.base_url}/api/goals", headers=headers,
                     json={"title": "SYN swipe task"}).json()
    doc = httpx.post(f"{session.backend.base_url}/api/docs", headers=headers,
                    json={"path": "syn/swipe.md", "title": "SYN swipe document",
                          "body": f"[SYN swipe task](goal:{goal['id']})\n\n" + "A paragraph to scroll.\n\n" * 60}).json()
    page = session.page
    page.goto(f"{session.base_url}/#docs")
    open_page(page, doc["id"])
    page.locator('[data-role="doc-linked-goal-chip"]').click()
    expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'goal')
    expect(page.locator('.goal-window .goal-card')).to_be_visible()
    expect(page.locator('.vt-window-enter-active')).to_have_count(0)


def _wheel(page, dx: int, dy: int = 0) -> None:
    page.locator('.vt-window--front').dispatch_event('wheel', {"deltaX": dx, "deltaY": dy})


@pytest.mark.parametrize("direction", [-1, 1])
def test_one_swipe_keeps_its_destination_through_the_inertial_tail(ui_f2: UiSession, direction: int) -> None:
    _windows(ui_f2)
    page = ui_f2.page
    if direction == 1:
        page.keyboard.press('Meta+BracketLeft')
    destination = 'doc' if direction == -1 else 'goal'
    for distance in [70, 12, 10, 8, 4, 1]:
        _wheel(page, direction * distance)
        expect(page.locator('.vt-window--front'), f'wheel delta {direction * distance}').to_have_attribute('data-window', destination)


def test_a_new_swipe_can_return_after_the_previous_gesture_ends(ui_f2: UiSession) -> None:
    _windows(ui_f2)
    page = ui_f2.page
    _wheel(page, -70)
    expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'doc')
    page.wait_for_timeout(400)
    _wheel(page, 70)
    expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'goal')
    for distance in [12, 8, 1]:
        _wheel(page, distance)
        expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'goal')


def test_an_edge_swipe_does_not_bounce_to_the_other_window(ui_f2: UiSession) -> None:
    _windows(ui_f2)
    page = ui_f2.page
    page.keyboard.press('Meta+BracketLeft')
    for distance in [-70, -12, -4]:
        _wheel(page, distance)
        expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'doc')


def test_vertical_and_overflowing_content_scroll_without_changing_windows(ui_f2: UiSession) -> None:
    _windows(ui_f2)
    page = ui_f2.page
    page.keyboard.press('Meta+BracketLeft')
    body = page.locator('.vt-window--front .vt-window__body')
    body.hover()
    page.mouse.wheel(0, 240)
    page.wait_for_function("document.querySelector('.vt-window--front .vt-window__body').scrollTop > 0")
    expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'doc')
    body.evaluate("el => { const wide = document.createElement('div'); wide.style.width = '1400px'; el.append(wide) }")
    body.dispatch_event('wheel', {"deltaX": 100, "deltaY": 0})
    expect(page.locator('.vt-window--front')).to_have_attribute('data-window', 'doc')
