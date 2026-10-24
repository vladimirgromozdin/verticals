"""The normal document window exposes deletion and names the document before it removes it."""

import httpx
import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.views import open_page


@pytest.mark.parametrize('linked', [False, True])
def test_a_document_can_be_deleted_from_its_window_after_confirmation(ui_f2: UiSession, linked: bool) -> None:
    api = ui_f2.backend.base_url
    headers = {'Authorization': f'Bearer {ui_f2.backend.token}'}
    goal = httpx.post(f'{api}/api/goals', headers=headers, json={'title': 'SYN task to keep'}).json()['id']
    doc = httpx.post(f'{api}/api/docs', headers=headers, json={'path': 'syn/remove.md', 'title': 'SYN document to remove',
                     'body': f'[Task](goal:{goal})' if linked else 'SYN independent document.'}).json()['id']
    if linked:
        httpx.patch(f'{api}/api/goals/{goal}', headers=headers, json={'body': '[Document](doc:syn/remove.md)'})
    page = ui_f2.page
    page.goto(f'{ui_f2.base_url}/#docs')
    open_page(page, doc)
    page.locator('.vt-window [data-role="doc-delete"]').click()
    confirmation = page.locator('[data-role="doc-delete-confirmation"]')
    expect(confirmation).to_contain_text('SYN document to remove')
    confirmation.get_by_role('button', name='Cancel', exact=True).click()
    assert httpx.get(f'{api}/api/docs/{doc}', headers=headers).status_code == 200
    body = page.locator('.vt-window [data-role="doc-body"]')
    body.click()
    body.fill('SYN an edit still waiting for its save.')
    page.locator('.vt-window [data-role="doc-delete"]').click()
    if linked:
        expect(confirmation).to_contain_text('1 task')
    confirmation.get_by_role('button', name='Delete document', exact=True).click()
    expect(page.locator('.vt-window[data-window="doc"]')).to_have_count(0)
    expect(page.locator(f'[data-doc-id="{doc}"]')).to_have_count(0)
    assert httpx.get(f'{api}/api/docs/{doc}', headers=headers).status_code == 404
    assert httpx.get(f'{api}/api/goals/{goal}', headers=headers).status_code == 200
