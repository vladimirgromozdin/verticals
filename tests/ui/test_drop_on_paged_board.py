"""A goal dropped on a column of a board paged away from today lands in that column's period, not in today's. The drop's
date came from the schedule popup's grid, which knows only the periods around today and answers today for any other, so a
goal dragged onto next month's Month column was saved into this month and left the paged board."""

from __future__ import annotations

import httpx
import psycopg
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column
from tests.ui.test_board_undo import GRIP, board

STRIP = '[data-role="column-strip"]'


def _page_to(page, vertical: str, period_key: str) -> None:
    """Step one column's side bar until it shows `period_key`; the board pages as one."""
    column = page.locator(f"{STRIP} > [data-vertical='{vertical}']")
    for _ in range(40):
        shown = column.get_attribute("data-period-key")
        if shown == period_key:
            return
        column.hover()
        column.locator('[data-cap="period-next"]').click()
        expect(column).not_to_have_attribute("data-period-key", shown or "", timeout=5000)
    raise AssertionError(f"the {vertical} column never showed {period_key}")


def test_a_drop_on_a_paged_board_lands_in_the_shown_period(ui_f2: UiSession) -> None:
    session = ui_f2
    made = httpx.post(
        f"{session.backend.base_url}/api/goals",
        headers={"Authorization": f"Bearer {session.backend.token}"},
        json={"title": "A day in the week paged to", "vertical": "day", "anchor_date": "2026-09-08"},
    )
    assert made.status_code == 201, made.text
    goal_id = made.json()["id"]
    page = board(session)
    _page_to(page, "day", "2026-09-08")
    expect(page.locator(f"{STRIP} > [data-vertical='week']")).to_have_attribute("data-period-key", "2026-W37")
    activate_column(page, "day")
    row = f'[data-goal-id="{goal_id}"] > .goal-card__row'
    page.wait_for_selector(row)

    session.gestures.drag(row, '[data-vertical="week"] .pattern-vertical-board__body', source_position=GRIP, target_position=GRIP)
    page.wait_for_selector(f'[data-vertical="week"] [data-goal-id="{goal_id}"]', timeout=5000)

    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        for _ in range(50):
            stored = conn.execute("SELECT vertical, period_key FROM goals WHERE id = %s", (goal_id,)).fetchone()
            if stored[0] == "week":
                break
            page.wait_for_timeout(100)
    assert stored == ("week", "2026-W37"), stored
    expect(page.locator(f'[data-vertical="week"] [data-goal-id="{goal_id}"]')).to_have_count(1)
