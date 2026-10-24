"""The board must find an off-period Cyrillic title regardless of query case."""
from datetime import date

import psycopg
from playwright.sync_api import expect

from verticals.core import goals
from tests.ui.views import FIELD


def test_board_finds_cyrillic_title_regardless_of_case(ui_f2):
    session = ui_f2
    with psycopg.connect(session.backend.dsn, autocommit=True) as conn:
        target = goals.create(conn, owner='t1', title='Синица', vertical='day',
                              anchor_date=date(2028, 1, 1)).goal.id
    page = session.page
    field = page.locator(FIELD)
    page.keyboard.press('Control+k')
    for query in ['синица', 'СИНИЦА', 'сИнИцА']:
        with page.expect_response(lambda r: '/api/search?' in r.url and 'with=parents' in r.url) as response:
            field.fill(query)
        assert target in {g['id'] for g in response.value.json()['goals']}
        expect(page.locator(f'.pattern-vertical-board [data-goal-id="{target}"]').first).to_be_visible()
    field.press('Escape')
    expect(field).to_have_value('')
