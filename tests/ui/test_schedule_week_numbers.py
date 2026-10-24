"""The schedule popup's week rows carry ISO week numbers in every time zone. A week's number was worked out from the hours
between 1 January and the week's Thursday, and after the clocks go forward that is an hour short of whole days, so for
about seven months a year a zone with summer time named each week one too low: in Berlin the week of 19 October 2026,
ISO week 43, read W42, and W43 was not offered at all. The rest of the suite runs in the machine's zone, so this test
pins one with summer time."""

from __future__ import annotations

from datetime import date

import psycopg

from tests.ui.conftest import _DIALOG_RECORDER_SCRIPT, UiSession
from tests.ui.views import switch_view

GOAL = "SYNMAY01"  # in the Inbox, with no date
TRIGGER = '.goal-card--detail-open .goal-facts [data-cap="schedule"]'
POPOVER = '#dropdownPortal [data-popover-surface][data-state="open"]:has(.schedule-popover__row)'
WEEKS = f"{POPOVER} .schedule-popover__weeks [data-period-key]"


def test_week_rows_are_iso_weeks_in_a_zone_with_summer_time(ui_f2: UiSession) -> None:
    context = ui_f2.context.browser.new_context(timezone_id="Europe/Berlin", reduced_motion="reduce")
    context.add_init_script(script=_DIALOG_RECORDER_SCRIPT)
    page = context.new_page()
    try:
        page.clock.set_fixed_time("2026-10-19T09:00:00+02:00")
        page.goto(ui_f2.base_url)
        switch_view(page, "inbox")
        page.click(f'[data-cap="inbox"] [data-goal-id="{GOAL}"]')
        page.click(TRIGGER)
        page.wait_for_selector(WEEKS)

        keys = page.locator(WEEKS).evaluate_all("rows => rows.map(r => r.dataset.periodKey)")
        assert keys == ["2026-W40", "2026-W41", "2026-W42", "2026-W43", "2026-W44"], keys

        with page.expect_response(lambda r: r.url.endswith(f"/api/goals/{GOAL}/schedule")) as answer:
            page.click(f'{WEEKS}[data-period-key="2026-W43"]')
        assert answer.value.status == 200
        with psycopg.connect(ui_f2.backend.dsn, autocommit=True) as conn:
            row = conn.execute("SELECT vertical, period_key, anchor_date FROM goals WHERE id = %s", (GOAL,)).fetchone()
        assert row[:2] == ("week", "2026-W43"), row
        assert date(2026, 10, 19) <= row[2] <= date(2026, 10, 25), row
    finally:
        context.close()
