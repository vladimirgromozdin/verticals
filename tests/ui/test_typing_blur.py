"""Conversation drafts do not apply the board's search styling to window titles."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.ui.conftest import UiSession
from tests.ui.test_agent_conversation import ui_agent  # noqa: F401
from tests.ui.test_goal_window import _discuss, GOAL
from tests.ui.views import FIELD


@pytest.mark.parametrize('words', ['Q3 ground', 'Q4 follow', 'An unrelated message'])
def test_typing_keeps_background_stable(ui_agent: UiSession, words: str) -> None:
    page = ui_agent.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    _discuss(page)
    blur = page.locator('.vt-window--front .pblur')
    expect(blur).to_have_class('pblur pblur--under')
    expect(blur.locator('.pblur__lens > *')).to_have_count(4)
    page.wait_for_timeout(500)  # opening has settled before measuring the draft
    blur.evaluate('''el => {
      window.blurChanges = [];
      window.blurObserver = new MutationObserver(rs => window.blurChanges.push(...rs.map(r => ({
        type:r.type, attr:r.attributeName, target:r.target.className
      }))));
      window.blurObserver.observe(el, {subtree:true, attributes:true, childList:true, characterData:true});
    }''')
    field = page.locator(FIELD)
    field.press_sequentially(words, delay=80)
    page.wait_for_timeout(250)
    expect(blur.locator('.goal-card__title-text--finding')).to_have_count(0)
    expect(blur.locator('.goal-card__title-text strong')).to_have_count(0)
    for key in ['ArrowLeft', 'Backspace', 'Shift+Enter']:
        field.press(key)
    field.fill('Pasted text\nA second line')
    field.fill('')
    page.wait_for_timeout(250)
    changes = page.evaluate('window.blurChanges')
    page.evaluate('window.blurObserver.disconnect()')
    assert changes == [], 'Draft edits must not rebuild or restyle the background window'

    # The card is still usable when brought forward, and the chat can open again.
    box = page.locator('.vt-window--front').bounding_box()
    assert box is not None
    page.mouse.click(box['x'] + 20, box['y'] + box['height'] - 20)
    expect(blur).to_have_class('pblur pblur--none')
    blur.locator('.pblur__live [data-cap="edit-title"]').first.click()
    editor = blur.locator('textarea[data-cap="edit-title"]')
    editor.fill('Updated groundwork')
    editor.press('Enter')
    expect(blur.locator('.pblur__live .goal-card__title-text').first).to_have_text('Updated groundwork')
    page.keyboard.press('Escape')
    expect(page.locator('.vt-window')).to_have_count(0)
    _discuss(page)
    expect(blur).to_have_class('pblur pblur--under')
    for lens in blur.locator('.pblur__lens').all():
        expect(lens.locator('.goal-card__title-text').first).to_have_text('Updated groundwork')
    page.keyboard.press('Control+k')
    field.fill('Q3')
    expect(field).to_have_value('Q3')


def test_board_search_still_highlights_matches(ui_f2: UiSession) -> None:
    page = ui_f2.page
    page.wait_for_selector(f'[data-goal-id="{GOAL}"]')
    page.keyboard.press('Control+k')
    page.locator(FIELD).fill('Q3')
    title = page.locator(f'[data-goal-id="{GOAL}"] .goal-card__title-text').first
    expect(title).to_have_class(re.compile('goal-card__title-text--finding'))
    expect(title.locator('strong')).to_have_text('Q3')
