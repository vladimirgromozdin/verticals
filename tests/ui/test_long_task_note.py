"""A long inline task is saved, with its complete original text in notes."""
import httpx
import pytest
from playwright.sync_api import expect
from tests.ui.conftest import activate_column


@pytest.mark.parametrize('words', ['A detailed task description. '*14, '🧭'*251], ids=['words','unicode'])
def test_long_board_task_keeps_its_text_in_notes(ui_f2, words):
    page=ui_f2.page
    page.wait_for_selector('[data-vertical="week"]')
    activate_column(page,'week')
    add=page.locator('[data-role="column-strip"] > [data-vertical="week"] [data-cap="create-goal"]').last
    add.click()
    field=add.locator('[data-role="column-add-editor"]')
    field.fill(words)
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/goals')) as response:
        field.press('Enter')
    assert response.value.status==201
    made=response.value.json()
    assert len(made['title'])<=250
    detail=httpx.get(ui_f2.backend.base_url+'/api/goals/'+made['id'],headers={'Authorization':f'Bearer {ui_f2.backend.token}'}).json()
    assert detail['body']==words.strip()
    expect(page.locator(f'[data-goal-id="{made["id"]}"]')).to_be_visible()
    page.reload()
    expect(page.locator(f'[data-goal-id="{made["id"]}"]')).to_be_visible()
