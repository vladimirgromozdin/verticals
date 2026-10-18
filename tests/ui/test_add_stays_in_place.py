"""A goal added with Enter stays in its column while the server makes it (lib/boardPlacement.ts `createPlacement`).
Before, the field closed at once and the title was gone until the create and a reload of the whole board came back: on a
slow connection the goal went away, then came back. Here the create is held, as a slow server would hold it."""

from __future__ import annotations

import httpx
import psycopg
from playwright.sync_api import FloatRect, Locator, Page, Route, expect

from tests.ui.conftest import UiSession, activate_column
from tests.ui.test_board_undo import board
from tests.ui.undo_helpers import wait_for

ADD = '[data-vertical="week"] [data-cap=create-goal]'


def _hold_creates(page: Page) -> list[Route]:
    held: list[Route] = []
    page.route("**/api/goals", lambda route: held.append(route) if route.request.method == "POST" else route.continue_())
    return held


def _add(page: Page, title: str) -> None:
    page.click(ADD)
    editor = page.locator(f'{ADD} [data-role="column-add-editor"]')
    editor.fill(title)
    editor.press("Enter")
    page.mouse.move(0, 0)  # a card under the pointer lifts, and a pending card does not take the pointer


def _card(page: Page, title: str) -> Locator:
    return page.locator('[data-vertical="week"] .goal-card', has_text=title)


def _made(dsn: str, title: str) -> list[tuple[str]]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute("SELECT id FROM goals WHERE title = %s", (title,)).fetchall()


def _same_place(a: FloatRect | None, b: FloatRect | None) -> bool:
    return a is not None and b is not None and abs(a["x"] - b["x"]) < 1 and abs(a["y"] - b["y"]) < 1


def test_a_goal_added_with_enter_stays_in_its_column(ui_f2: UiSession) -> None:
    session = ui_f2
    page = board(session)
    held = _hold_creates(page)
    activate_column(page, "week")
    _add(page, "SYN stays put")

    wait_for(page, lambda: len(held), 1, "the create is on its way")
    card = _card(page, "SYN stays put")
    expect(card).to_be_visible()  # while the server has not answered yet
    held_at = card.bounding_box()

    held.pop().continue_()
    wait_for(page, lambda: len(_made(session.backend.dsn, "SYN stays put")), 1, "the goal is made")
    ((goal_id,),) = _made(session.backend.dsn, "SYN stays put")
    made = page.locator(f'[data-vertical="week"] [data-goal-id="{goal_id}"]')
    expect(made).to_have_count(1)
    expect(card).to_have_count(1)
    assert _same_place(held_at, made.bounding_box()), "the goal stays where it stood while the server made it"


def test_two_goals_added_one_after_the_other_both_stay(ui_f2: UiSession) -> None:
    session = ui_f2
    page = board(session)
    held = _hold_creates(page)
    activate_column(page, "week")
    _add(page, "SYN first of two")
    _add(page, "SYN second of two")

    wait_for(page, lambda: len(held), 2, "both creates are on their way")
    expect(_card(page, "SYN first of two")).to_be_visible()
    expect(_card(page, "SYN second of two")).to_be_visible()

    held.pop(0).continue_()  # the first answer brings a reload, which must keep the second card
    wait_for(page, lambda: len(_made(session.backend.dsn, "SYN first of two")), 1, "the first goal is made")
    page.wait_for_timeout(500)
    expect(_card(page, "SYN second of two")).to_be_visible()

    held.pop().continue_()
    wait_for(page, lambda: len(_made(session.backend.dsn, "SYN second of two")), 1, "the second goal is made")
    expect(_card(page, "SYN first of two")).to_have_count(1)
    expect(_card(page, "SYN second of two")).to_have_count(1)


def test_a_write_from_elsewhere_does_not_take_the_new_goal_away(ui_f2: UiSession) -> None:
    session = ui_f2
    page = board(session)
    held = _hold_creates(page)
    activate_column(page, "week")
    _add(page, "SYN stays through a write")
    wait_for(page, lambda: len(held), 1, "the create is on its way")

    # An agent's write rings the live feed while the create waits. The board it fetches has no card for the new goal.
    elsewhere = httpx.post(
        f"{session.backend.base_url}/api/goals",
        json={"title": "SYN from elsewhere", "vertical": "week", "anchor_date": "2026-08-08"},
        headers={"Authorization": f"Bearer {session.backend.token}"},
        timeout=10,
    )
    assert elsewhere.status_code == 201, elsewhere.text
    expect(_card(page, "SYN from elsewhere")).to_be_visible()  # the live feed's board is in
    card = _card(page, "SYN stays through a write")
    expect(card).to_be_visible()

    held.pop().continue_()
    wait_for(page, lambda: len(_made(session.backend.dsn, "SYN stays through a write")), 1, "the goal is made")
    expect(_card(page, "SYN from elsewhere")).to_have_count(1)
    expect(card).to_have_count(1)


def test_a_create_that_fails_takes_the_card_away(ui_f2: UiSession) -> None:
    session = ui_f2
    session.expects_network_failures = True  # the refused create is this test's own doing
    page = board(session)
    held = _hold_creates(page)
    activate_column(page, "week")
    _add(page, "SYN never made")
    wait_for(page, lambda: len(held), 1, "the create is on its way")
    card = _card(page, "SYN never made")
    expect(card).to_be_visible()

    held.pop().abort()
    expect(card).to_have_count(0)
    expect(page.locator(".toast-stack .toast__text")).to_be_visible()
    assert _made(session.backend.dsn, "SYN never made") == []
