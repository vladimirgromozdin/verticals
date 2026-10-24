"""Adding in a displayed period uses that period, including Tomorrow."""
import httpx
from playwright.sync_api import expect
from tests.ui.conftest import activate_column


def test_add_in_tomorrow_stays_in_tomorrow_after_reload(ui_f2):
    page=ui_f2.page
    page.wait_for_selector('[data-vertical="day"]')
    activate_column(page,'day')
    column=page.locator('[data-role="column-strip"] > [data-vertical="day"]')
    column.locator('[data-cap="period-mode"]').click()
    column=page.locator('[data-role="spans-row"] > [data-period-key="2026-08-09"]')
    expect(column).to_be_visible()
    add=column.locator('[data-cap="create-goal"]').last
    add.click()
    editor=add.locator('[data-role="column-add-editor"]')
    editor.fill('SYN Tomorrow appointment')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/goals')) as response:
        editor.press('Enter')
    data=response.value.json()
    assert data['anchor_date']=='2026-08-09'
    expect(column.locator(f'[data-goal-id="{data["id"]}"]')).to_be_visible()
    page.reload()
    page.wait_for_selector('[data-vertical="day"]')
    activate_column(page,'day')
    page.locator('[data-role="column-strip"] > [data-vertical="day"] [data-cap="period-mode"]').click()
    expect(column.locator(f'[data-goal-id="{data["id"]}"]')).to_be_visible()
