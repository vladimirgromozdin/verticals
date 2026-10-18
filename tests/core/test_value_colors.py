"""A goal that becomes a value without a colour takes one (core/value_colors.py).

D231 took the colour picker out of the app, so a value made there had no colour, and nor did anything under it. Now a
value takes the palette colour the fewest of the owner's values have, ties going to the palette's order. A colour a
caller gives is kept. Real Postgres, no mocks.
"""

from __future__ import annotations

from datetime import date

import psycopg

from verticals.core import board, goals, moves
from verticals.core.field_rules import VALUE_PALETTE

OWNER = "SYN-value-colors"
OTHER = "SYN-value-colors-other"
TODAY = date.today()


def _value(conn: psycopg.Connection, title: str, color: str | None = None, owner: str = OWNER):
    return goals.create(conn, owner=owner, title=title, vertical="life", anchor_date=TODAY, color=color).goal


def test_new_values_take_the_palette_in_order(db: psycopg.Connection) -> None:
    made = [_value(db, f"SYN value {n}").color for n in range(len(VALUE_PALETTE))]
    assert made == list(VALUE_PALETTE)


def test_a_seventh_value_takes_the_colour_fewest_values_have(db: psycopg.Connection) -> None:
    first = _value(db, "SYN value 0")
    for n in range(1, len(VALUE_PALETTE)):
        _value(db, f"SYN value {n}")
    assert _value(db, "SYN value 6").color == first.color
    assert _value(db, "SYN value 7").color == VALUE_PALETTE[1]


def test_a_given_colour_is_kept_and_counts(db: psycopg.Connection) -> None:
    assert _value(db, "SYN value given", VALUE_PALETTE[0]).color == VALUE_PALETTE[0]
    assert _value(db, "SYN value next").color == VALUE_PALETTE[1]


def test_another_owners_values_do_not_count(db: psycopg.Connection) -> None:
    _value(db, "SYN other value", owner=OTHER)
    assert _value(db, "SYN own value").color == VALUE_PALETTE[0]


def test_the_board_shows_the_colour_on_the_value_and_under_it(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value")
    child = goals.create(
        db, owner=OWNER, title="SYN child", parent_id=value.id, vertical="day", anchor_date=TODAY
    ).goal
    shown = board.board(db, owner=OWNER, date=TODAY)
    day = next(column for column in shown.columns if column.vertical == "day")
    assert {g.id: g.color for g in day.goals}[child.id] == value.color
    assert goals.goal(db, owner=OWNER, id=value.id).goal.color == value.color


def test_goals_that_are_not_values_take_no_colour(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value")
    step = goals.create(db, owner=OWNER, title="SYN step", parent_id=value.id, vertical="life", anchor_date=TODAY).goal
    day = goals.create(db, owner=OWNER, title="SYN day root", vertical="day", anchor_date=TODAY).goal
    stored = dict(db.execute("SELECT id, color FROM goals WHERE id = ANY(%s)", ([step.id, day.id],)).fetchall())
    assert stored == {step.id: None, day.id: None}


def test_a_life_step_taken_out_of_its_value_becomes_a_value_with_a_colour(db: psycopg.Connection) -> None:
    value = _value(db, "SYN value")
    step = goals.create(db, owner=OWNER, title="SYN step", parent_id=value.id, vertical="life", anchor_date=TODAY).goal
    assert moves.reparent(db, owner=OWNER, id=step.id, parent_id=None).color == VALUE_PALETTE[1]


def test_a_parentless_goal_moved_to_life_becomes_a_value_with_a_colour(db: psycopg.Connection) -> None:
    year = goals.create(db, owner=OWNER, title="SYN year root", vertical="year", anchor_date=TODAY).goal
    moved = moves.schedule(db, owner=OWNER, id=year.id, vertical="life", anchor_date=TODAY).goal
    assert moved.color == VALUE_PALETTE[0]
