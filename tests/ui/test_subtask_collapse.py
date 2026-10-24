"""Hiding a task's steps changes its view without changing the tasks themselves."""

import httpx
from playwright.sync_api import expect

from tests.ui.conftest import UiSession, activate_column


def _family(session: UiSession) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {session.backend.token}"}
    url = f"{session.backend.base_url}/api/goals"
    parent = httpx.post(url, headers=headers, json={"title": "SYN parent with steps",
                       "vertical": "month", "anchor_date": "2026-08-08",
                       "body": "SYN notes remain available."}).json()["id"]
    child = httpx.post(url, headers=headers, json={"title": "SYN child to hide", "parent_id": parent,
                      "vertical": "month", "anchor_date": "2026-08-08"}).json()["id"]
    session.page.reload()
    activate_column(session.page, "month")
    return parent, child


def test_subtasks_can_be_hidden_and_shown_without_changing_the_family(ui_f2: UiSession) -> None:
    parent, child = _family(ui_f2)
    page = ui_f2.page
    card = page.locator(f'.goal-card[data-goal-id="{parent}"]').first
    toggle = card.locator('[data-role="subtasks-toggle"]')
    expect(page.locator(f'.goal-card[data-goal-id="{child}"]')).to_be_visible()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', 'false')
    expect(page.locator(f'.goal-card[data-goal-id="{child}"]')).not_to_be_visible()
    expect(page.locator('#goal-detail')).to_have_count(0)
    data = httpx.get(f"{ui_f2.backend.base_url}/api/goals/{parent}",
                     headers={"Authorization": f"Bearer {ui_f2.backend.token}"}).json()
    assert any(step['id'] == child for step in data['children'])
    toggle.focus()
    page.keyboard.press('Enter')
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator(f'.goal-card[data-goal-id="{child}"]')).to_be_visible()


def test_hidden_subtasks_stay_hidden_on_reload_and_leave_notes_accessible(ui_f2: UiSession) -> None:
    parent, child = _family(ui_f2)
    page = ui_f2.page
    card = page.locator(f'.goal-card[data-goal-id="{parent}"]').first
    card.locator('[data-role="subtasks-toggle"]').click()
    page.reload()
    activate_column(page, "month")
    card = page.locator(f'.goal-card[data-goal-id="{parent}"]').first
    expect(card.locator('[data-role="subtasks-toggle"]')).to_have_attribute('aria-expanded', 'false')
    card.locator('.goal-card__title').click()
    expect(page.locator('#goal-detail')).to_contain_text('SYN notes remain available.')
    expect(page.locator(f'.goal-card[data-goal-id="{child}"]')).not_to_be_visible()
    card.locator('[data-role="subtasks-toggle"]').click()
    expect(page.locator(f'.goal-card[data-goal-id="{child}"]')).to_be_visible()
    expect(page.locator('#goal-detail')).to_contain_text('SYN notes remain available.')
