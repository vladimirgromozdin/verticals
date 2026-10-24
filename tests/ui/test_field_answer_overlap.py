"""An old answer never covers a new draft pasted into the field."""
from playwright.sync_api import expect
from tests.ui.test_agent_conversation import ui_agent
from tests.ui.test_report import _say
from tests.ui.views import FIELD


def test_an_answer_chip_is_hidden_while_the_field_edits_a_new_draft(ui_agent):
    page=ui_agent.page
    page.wait_for_selector('.goal-card__row')
    _say(page, 1)
    expect(page.locator('[data-role="circle-answer"]')).to_be_visible()
    page.keyboard.press('Control+k')
    field=page.locator(FIELD)
    field.fill('A pasted draft\nwith a second line')
    expect(field).to_have_value('A pasted draft\nwith a second line')
    expect(page.locator('[data-role="circle-answer"]')).not_to_be_visible()
