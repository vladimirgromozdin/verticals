"""The goal's menu (docs/design-handoff S5.P5; docs/design/goal-menu.md): its actions grouped by what they change (Agent,
Reschedule, Move, then Delete in red). Date opens in place with ‹ back the same grid as the date under an open goal's title,
and Into a goal finds a goal by typing and makes this one its step. F2, the
browser clock pinned to 2026-08-08 (a Saturday)."""

from __future__ import annotations

import re

import psycopg
from playwright.sync_api import Page, expect

from tests.ui.conftest import UiSession, activate_column
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401  (the fixture)

MENU = '[data-role="goal-context-menu"]'
STEP = f'{MENU} [data-role="move-step"]'


def _menu(page: Page, goal_id: str, vertical: str) -> None:
    activate_column(page, vertical)
    page.locator(f'[data-goal-id="{goal_id}"] > .goal-card__row').first.click(button="right")
    page.wait_for_selector(MENU)


def _groups(page: Page) -> list[dict]:
    """The open menu's groups from the top: the name, the small grey word, the items and whether a line stands above it."""
    return page.evaluate(
        """(menu) => [...document.querySelector(menu).querySelectorAll('[data-menu-section]')].map((section) => ({
          name: section.dataset.menuSection,
          heading: section.querySelector('.goal-actions__heading')?.textContent ?? null,
          items: [...section.querySelectorAll('[role=menuitem]')].map((item) => item.innerText.trim()),
          line: parseFloat(getComputedStyle(section).borderTopWidth) > 0,
        }))""",
        MENU,
    )


RESCHEDULE = {"name": "reschedule", "heading": "Reschedule", "items": ["Tomorrow", "Next week", "Date", "Repeat"], "line": False}
MOVE = {"name": "move", "heading": "Move", "items": ["Into a goal", "To Inbox"], "line": True}
DELETE = {"name": "delete", "heading": None, "items": ["Delete"], "line": True}


def _goal(ui: UiSession, goal_id: str) -> tuple:
    with psycopg.connect(ui.backend.dsn, autocommit=True) as conn:
        return conn.execute("SELECT vertical, period_key, anchor_date, parent_id FROM goals WHERE id = %s", (goal_id,)).fetchone()


def test_date_opens_the_schedule_grid_in_place(ui_f2: UiSession) -> None:
    """The date is picked one way everywhere: the menu's Date shows the grid of Life, the 3 years, the year and its
    quarters, the month, its weeks and days; ← goes back, and a week picked there schedules the goal and closes the menu."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    _menu(page, "SYNORD01", "week")
    page.click(f'{MENU} [data-move="date"]')
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Move to a date")
    for scale in ["life", "decade", "year", "month", "week", "day"]:
        expect(page.locator(f'{STEP} [data-scale="{scale}"]').first).to_be_visible()
    expect(page.locator(f'{STEP} [data-scale="quarter"]')).to_have_count(4)
    page.keyboard.press("ArrowLeft")
    expect(page.locator(f'{MENU} [data-move="date"]')).to_be_visible()
    page.click(f'{MENU} [data-move="date"]')
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNORD01/schedule")):
        page.click(f'{STEP} [data-scale="week"] [data-period-key="2026-W34"]')
    expect(page.locator(MENU)).to_have_count(0)
    vertical, period, _, _ = _goal(ui_f2, "SYNORD01")
    assert (vertical, period) == ("week", "2026-W34")


def test_the_grid_pages_months_in_the_menu_and_picks_a_day(ui_f2: UiSession) -> None:
    """The ‹ › steppers page the grid without closing the menu; a day picked a month ahead lands on that day."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNCOL01"]')
    _menu(page, "SYNCOL01", "day")
    page.click(f'{MENU} [data-move="date"]')
    month = page.locator(f'{STEP} [data-scale="month"] .schedule-popover__stepper-label')
    expect(month).to_have_text("August")
    page.click(f'{STEP} [aria-label="Next month"]')
    expect(month).to_have_text("September")
    expect(page.locator(STEP)).to_be_visible()
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNCOL01/schedule")):
        page.click(f'{STEP} [data-scale="day"] [data-period-key="2026-09-14"]')
    vertical, _, anchor, _ = _goal(ui_f2, "SYNCOL01")
    assert (vertical, str(anchor)) == ("day", "2026-09-14")


def test_into_a_goal_finds_a_goal_by_typing_and_makes_this_one_its_step(ui_f2: UiSession) -> None:
    """S5.P5.011, .012, .037: the search icon left, the circled × right; typing narrows by name; a click reparents."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD02"]')
    _menu(page, "SYNORD02", "week")
    page.click(f'{MENU} [data-move="under"]')
    expect(page.locator(f"{STEP} .move-step__title")).to_have_text("Into a goal")
    search = page.locator(f'{STEP} [data-role="move-under-search"]')
    expect(search).to_be_focused()
    search.fill("bicycles")
    match = page.locator(f'{STEP} [data-parent-id="SYNSCH01"]')
    expect(match).to_have_count(1, timeout=5000)
    expect(match.locator("strong")).to_have_text(re.compile("bicycles", re.IGNORECASE))
    expect(match.locator(".move-step__vertical")).to_have_text("Month")
    expect(page.locator(f"{STEP} .move-step__clear")).to_have_count(1)
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/api/goals/SYNORD02/parent")):
        match.click()
    assert _goal(ui_f2, "SYNORD02")[3] == "SYNSCH01"


def test_the_menu_groups_its_actions_by_what_they_change(ui_f2: UiSession) -> None:
    """Reschedule over Tomorrow, Next week, Date ›, Repeat ›; a line; Move over Into a goal ›, To Inbox; a line; Delete.
    Nothing says Agent, Comment or Complete: no agent here, a goal completes by its box, comments live in documents."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNCOL03"]')
    _menu(page, "SYNCOL03", "day")
    assert _groups(page) == [RESCHEDULE, MOVE, DELETE]
    for gone in ("discuss", "comment", "complete"):
        assert page.locator(f'{MENU} [data-menu-item="{gone}"]').count() == 0
    for chevron in ("date", "under"):
        assert page.locator(f'{MENU} [data-move="{chevron}"] [data-role="submenu-arrow"]').count() == 1
    assert page.locator(f'{MENU} [data-action="repeat"] [data-role="submenu-arrow"]').count() == 1


def test_a_goal_with_steps_has_the_same_menu_and_repeat_is_live(ui_f2: UiSession) -> None:
    """SYNDAY01 has three steps. Its menu used to open with Complete and show Repeat greyed with "Only for goals without
    subgoals"; now it reads like any goal's, and Repeat opens."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNDAY01"]')
    _menu(page, "SYNDAY01", "day")
    assert _groups(page) == [RESCHEDULE, MOVE, DELETE]
    repeat = page.locator(f'{MENU} [data-action="repeat"] button')
    expect(repeat).to_be_enabled()
    assert page.locator(f"{MENU} .goal-actions__why").count() == 0
    repeat.click()
    expect(page.locator('[data-role="repeat-menu"]')).to_be_visible()


def test_an_open_goal_keeps_tags_between_move_and_delete(ui_f2: UiSession) -> None:
    """The open card shows its date, its comments and the agent in its facts line, so its menu adds only its tags: after
    Move, before Delete, with a line of its own."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNORD01"]')
    activate_column(page, "week")
    page.locator('[data-goal-id="SYNORD01"] .goal-card__title').click(position={"x": 12, "y": 10})
    page.click('[data-goal-id="SYNORD01"].goal-card--detail-open [data-role="goal-actions-trigger"]')
    page.wait_for_selector(MENU)
    assert _groups(page) == [
        RESCHEDULE, MOVE, {"name": "tags", "heading": None, "items": ["Tags…"], "line": True}, DELETE,
    ]
    assert page.locator(f'{MENU} [data-menu-item="comment"]').count() == 0


def test_delete_shows_its_red(ui_f2: UiSession) -> None:
    """The class carried #c93a5b all along; the menu's own item colour (two classes) painted over it."""
    page = ui_f2.page
    page.wait_for_selector('[data-goal-id="SYNCOL03"]')
    _menu(page, "SYNCOL03", "day")
    delete = page.locator(f'{MENU} [data-action="delete"]')
    assert delete.evaluate("el => getComputedStyle(el).color") == "rgb(201, 58, 91)"
    others = page.locator(f'{MENU} [role="menuitem"]:not([data-action="delete"])')
    assert {others.nth(i).evaluate("el => getComputedStyle(el).color") for i in range(others.count())} == {"rgb(0, 0, 0)"}
    delete.hover()
    assert delete.evaluate("el => getComputedStyle(el).color") == "rgb(201, 58, 91)"


def test_the_agent_group_comes_first_and_only_where_an_agent_is(ui_agent: UiSession) -> None:  # noqa: F811
    """Agent over Discuss, Start work and Open in, then the rest; the other groups and their lines do not move for it."""
    page = ui_agent.page
    page.wait_for_selector('[data-goal-id="SYNCOL03"]')
    _menu(page, "SYNCOL03", "day")
    expect(page.locator(f'{MENU} [data-menu-section="agent"]')).to_have_count(1)
    assert _groups(page) == [
        {"name": "agent", "heading": "Agent", "items": ["Discuss", "Start work", "Open in"], "line": False},
        {**RESCHEDULE, "line": True},
        MOVE,
        DELETE,
    ]
