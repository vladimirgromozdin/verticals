"""Repeatable goals through real core calls and real Postgres; no mocks or in-memory doubles."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import psycopg
import pytest

from verticals.core import docs, goals, moves, privacy
from verticals.core.errors import ValidationError
from verticals.models import Goal

OWNER = "repeat-core"


def _scheduled(conn: psycopg.Connection, title: str = "Recurring task"):
    return goals.create(
        conn, owner=OWNER, title=title, body="Shared notes", tags=["repeat"],
        vertical="day", anchor_date=date(2026, 8, 10),
    ).goal


def test_repeat_completion_materializes_one_normal_history_row(db: psycopg.Connection) -> None:
    first = _scheduled(db)
    configured = goals.update(
        db, owner=OWNER, id=first.id, repeat={"frequency": "daily", "interval": 1}
    ).goal
    assert configured.repeat_series_id == first.id
    assert configured.repeat_index == 0

    goals.update(db, owner=OWNER, id=first.id, done=True)
    rows = db.execute(
        "SELECT id, done_at, anchor_date, repeat_index, title, body, tags"
        " FROM goals WHERE owner = %s AND repeat_series_id = %s ORDER BY repeat_index",
        (OWNER, first.id),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] is not None and rows[1][1] is None
    assert rows[1][2:4] == (date(2026, 8, 11), 1)
    assert rows[1][4:] == ("Recurring task", "Shared notes", ["repeat"])


def test_repeat_completion_replay_is_idempotent(db: psycopg.Connection) -> None:
    first = _scheduled(db)
    goals.update(db, owner=OWNER, id=first.id, repeat={"frequency": "weekly", "weekdays": [1, 3]})
    goals.update(db, owner=OWNER, id=first.id, done=True)
    goals.update(db, owner=OWNER, id=first.id, done=True)
    (count,) = db.execute(
        "SELECT count(*) FROM goals WHERE owner = %s AND repeat_series_id = %s",
        (OWNER, first.id),
    ).fetchone()
    assert count == 2


def test_a_completion_hands_back_the_occurrence_it_made_and_a_replay_does_not(db: psycopg.Connection) -> None:
    """The page takes the occurrence back with the tick that made it (docs/design/board-undo.md), so the call says which one
    it made; one that was already there is not the call's own."""
    first = _scheduled(db)
    goals.update(db, owner=OWNER, id=first.id, repeat={"frequency": "daily"})

    ticked = goals.update(db, owner=OWNER, id=first.id, done=True)
    assert ticked.spawned is not None
    assert (ticked.spawned.repeat_index, ticked.spawned.anchor_date) == (1, date(2026, 8, 11))
    assert ticked.spawned.done_at is None and ticked.spawned.title == "Recurring task"

    assert goals.update(db, owner=OWNER, id=first.id, done=True).spawned is None, "a replay finds it there"
    assert goals.update(db, owner=OWNER, id=first.id, done=False).spawned is None, "reopening makes nothing"
    assert goals.update(db, owner=OWNER, id=first.id, title="Retitled").spawned is None

    # Taken back: the occurrence goes, and the tick played again makes it again, under another id.
    goals.delete(db, owner=OWNER, id=ticked.spawned.id)
    goals.update(db, owner=OWNER, id=first.id, done=False)
    again = goals.update(db, owner=OWNER, id=first.id, done=True)
    assert again.spawned is not None and again.spawned.id != ticked.spawned.id
    assert again.spawned.repeat_index == 1


def test_a_goal_that_does_not_repeat_hands_back_nothing(db: psycopg.Connection) -> None:
    plain = _scheduled(db, "Plain")
    assert goals.update(db, owner=OWNER, id=plain.id, done=True).spawned is None


def test_repeat_concurrent_completion_has_one_next_occurrence(db_dsn: str) -> None:
    with psycopg.connect(db_dsn, autocommit=True) as conn:
        first = _scheduled(conn)
        goals.update(conn, owner=OWNER, id=first.id, repeat={"frequency": "daily"})

    def complete() -> None:
        with psycopg.connect(db_dsn, autocommit=True) as conn:
            goals.update(conn, owner=OWNER, id=first.id, done=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: complete(), range(2)))
    with psycopg.connect(db_dsn, autocommit=True) as conn:
        indexes = conn.execute(
            "SELECT repeat_index FROM goals WHERE owner = %s AND repeat_series_id = %s"
            " ORDER BY repeat_index",
            (OWNER, first.id),
        ).fetchall()
    assert indexes == [(0,), (1,)]


def test_repeat_end_date_stops_materialization(db: psycopg.Connection) -> None:
    first = _scheduled(db)
    goals.update(
        db, owner=OWNER, id=first.id,
        repeat={"frequency": "daily", "end_date": date(2026, 8, 10)},
    )
    goals.update(db, owner=OWNER, id=first.id, done=True)
    (count,) = db.execute(
        "SELECT count(*) FROM goals WHERE owner = %s AND repeat_series_id = %s",
        (OWNER, first.id),
    ).fetchone()
    assert count == 1


@pytest.mark.parametrize(
    ("rule", "field"),
    [
        ({"frequency": "daily", "interval": 2}, "repeat.interval"),
        ({"frequency": "weekly", "interval": 2, "weekdays": [1]}, "repeat.weekdays"),
        ({"frequency": "monthly", "month_days": []}, "repeat.month_days"),
        ({"frequency": "yearly", "months": [1], "quarters": [1]}, "repeat.weekdays,repeat.month_days,repeat.months,repeat.quarters"),
        ({"frequency": "daily", "count": 4}, "repeat.count"),
    ],
)
def test_repeat_invalid_rule_is_refused_without_storage(
    db: psycopg.Connection, rule: dict, field: str
) -> None:
    first = _scheduled(db, title=str(rule))
    with pytest.raises(ValidationError) as exc:
        goals.update(db, owner=OWNER, id=first.id, repeat=rule)
    assert exc.value.detail["field"] == field
    assert goals.goal(db, owner=OWNER, id=first.id).goal.repeat_rule is None


def test_repeat_refuses_an_unscheduled_goal(db: psycopg.Connection) -> None:
    unscheduled = goals.create(db, owner=OWNER, title="Unscheduled").goal
    with pytest.raises(ValidationError) as exc:
        goals.update(db, owner=OWNER, id=unscheduled.id, repeat={"frequency": "daily"})
    assert exc.value.detail["field"] == "repeat"


# --- a goal with steps repeats (docs/design/goal-menu.md): each new time brings its steps back, unticked ---------------


def _occurrence(db: psycopg.Connection, first_id: str, index: int) -> str:
    (found,) = db.execute(
        "SELECT id FROM goals WHERE owner = %s AND repeat_series_id = %s AND repeat_index = %s",
        (OWNER, first_id, index),
    ).fetchone()
    return found


def _step(db: psycopg.Connection, parent_id: str, title: str, **fields: object) -> Goal:
    return goals.create(db, owner=OWNER, parent_id=parent_id, title=title, **fields).goal


def _repeating_review(db: psycopg.Connection, rule: dict | None = None) -> tuple[Goal, Goal, Goal, Goal, Goal]:
    """A daily goal with three steps (the first with notes and a tag, the second with a step of its own); the first step
    and the nested one are ticked."""
    review = _scheduled(db, "Daily review")
    check = _step(db, review.id, "Check the inbox", body="Every account", tags=["admin"])
    plan = _step(db, review.id, "Plan the day")
    pick = _step(db, plan.id, "Pick three goals")
    pay = _step(db, review.id, "Pay invoices")
    goals.update(db, owner=OWNER, id=check.id, done=True)
    goals.update(db, owner=OWNER, id=pick.id, done=True)
    goals.update(db, owner=OWNER, id=review.id, repeat=rule or {"frequency": "daily"})
    return review, check, plan, pick, pay


def test_a_goal_with_steps_can_repeat(db: psycopg.Connection) -> None:
    review, *_ = _repeating_review(db, {"frequency": "weekly", "weekdays": [1, 3]})
    configured = goals.goal(db, owner=OWNER, id=review.id).goal
    assert configured.repeat_rule == {"frequency": "weekly", "interval": 1, "weekdays": [1, 3]}
    assert (configured.repeat_series_id, configured.repeat_index) == (review.id, 0)


def test_each_new_time_brings_the_steps_back_unticked_in_their_structure_and_order(db: psycopg.Connection) -> None:
    review, check, plan, pick, pay = _repeating_review(db)
    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = goals.goal(db, owner=OWNER, id=_occurrence(db, review.id, 1)).goal
    steps = goals.children_of(db, owner=OWNER, id=again.id)
    assert [(s.title, s.body, s.tags, s.done_at) for s in steps] == [
        ("Check the inbox", "Every account", ("admin",), None),
        ("Plan the day", "", (), None),
        ("Pay invoices", "", (), None),
    ], "the same steps in the same order, notes and tags with them, none ticked"
    assert {s.id for s in steps}.isdisjoint({check.id, plan.id, pay.id}), "copies, not the old rows moved"
    (nested,) = goals.children_of(db, owner=OWNER, id=steps[1].id)
    assert (nested.title, nested.done_at, nested.depth) == ("Pick three goals", None, again.depth + 2), (
        "a step's own step comes back under its copy"
    )

    # The time that was finished keeps its own steps, as they were left.
    old = goals.children_of(db, owner=OWNER, id=review.id)
    assert [(s.id, s.done_at is not None) for s in old] == [(check.id, True), (plan.id, False), (pay.id, False)]
    assert [(s.id, s.done_at is not None) for s in goals.children_of(db, owner=OWNER, id=plan.id)] == [(pick.id, True)]


def test_the_steps_come_back_for_every_new_time(db: psycopg.Connection) -> None:
    review, *_ = _repeating_review(db)
    goals.update(db, owner=OWNER, id=review.id, done=True)
    second = _occurrence(db, review.id, 1)
    for step in goals.children_of(db, owner=OWNER, id=second):
        goals.update(db, owner=OWNER, id=step.id, done=True)
    goals.update(db, owner=OWNER, id=second, done=True)

    steps = goals.children_of(db, owner=OWNER, id=_occurrence(db, review.id, 2))
    assert [(s.title, s.done_at) for s in steps] == [("Check the inbox", None), ("Plan the day", None), ("Pay invoices", None)]


def test_completing_again_does_not_bring_the_steps_back_twice(db: psycopg.Connection) -> None:
    review, *_ = _repeating_review(db)
    goals.update(db, owner=OWNER, id=review.id, done=True)
    goals.update(db, owner=OWNER, id=review.id, done=False)
    goals.update(db, owner=OWNER, id=review.id, done=True)
    goals.update(db, owner=OWNER, id=review.id, done=True)

    (count,) = db.execute("SELECT count(*) FROM goals WHERE owner = %s AND title = 'Pay invoices'", (OWNER,)).fetchone()
    assert count == 2, "one step in the finished time, one in the next, however often the box is ticked"


def test_concurrent_completion_brings_the_steps_back_once(db_dsn: str) -> None:
    with psycopg.connect(db_dsn, autocommit=True) as conn:
        review, *_ = _repeating_review(conn)

    def complete() -> None:
        with psycopg.connect(db_dsn, autocommit=True) as conn:
            goals.update(conn, owner=OWNER, id=review.id, done=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: complete(), range(2)))
    with psycopg.connect(db_dsn, autocommit=True) as conn:
        again = _occurrence(conn, review.id, 1)
        steps = goals.children_of(conn, owner=OWNER, id=again)
        (count,) = conn.execute("SELECT count(*) FROM goals WHERE owner = %s", (OWNER,)).fetchone()
    assert [s.title for s in steps] == ["Check the inbox", "Plan the day", "Pay invoices"]
    assert count == 2 * 5, "the finished time and the new one: the goal, three steps and one nested step each"


def test_a_step_dated_in_the_goals_own_period_comes_back_in_the_new_one(db: psycopg.Connection) -> None:
    """A step added in an open card sits in its goal's period, where the card nests it: the next time's steps must not
    stay behind in the old period."""
    review = _scheduled(db, "Daily review")
    same = _step(db, review.id, "In today", vertical="day", anchor_date=review.anchor_date)
    _step(db, review.id, "Without a day")
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})
    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = goals.goal(db, owner=OWNER, id=_occurrence(db, review.id, 1)).goal
    steps = {s.title: s for s in goals.children_of(db, owner=OWNER, id=again.id)}
    assert (steps["In today"].vertical, steps["In today"].anchor_date, steps["In today"].period_key) == (
        again.vertical, again.anchor_date, again.period_key,
    ), "the step moved with its goal into the new period"
    assert steps["Without a day"].vertical is None, "an undated step stays undated"
    old = goals.goal(db, owner=OWNER, id=same.id).goal
    assert (old.anchor_date, old.period_key) == (date(2026, 8, 10), "2026-08-10"), "the old time's step stays put"


def test_a_step_dated_elsewhere_keeps_its_distance_from_the_goal(db: psycopg.Connection) -> None:
    review = goals.create(
        db, owner=OWNER, title="Weekly review", vertical="week", anchor_date=date(2026, 8, 12),  # a Wednesday
    ).goal
    _step(db, review.id, "Send the report", vertical="day", anchor_date=date(2026, 8, 14))  # the Friday
    _step(db, review.id, "Whole week", vertical="week", anchor_date=date(2026, 8, 16))  # the week's Sunday
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "weekly"})
    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = goals.goal(db, owner=OWNER, id=_occurrence(db, review.id, 1)).goal
    assert (again.anchor_date, again.period_key) == (date(2026, 8, 19), "2026-W34")
    steps = {s.title: s for s in goals.children_of(db, owner=OWNER, id=again.id)}
    assert (steps["Send the report"].anchor_date, steps["Send the report"].period_key) == (
        date(2026, 8, 21), "2026-08-21",
    ), "the Friday after the new Wednesday"
    assert (steps["Whole week"].vertical, steps["Whole week"].period_key) == ("week", "2026-W34")


def test_a_step_that_repeats_by_itself_comes_back_as_a_plain_step(db: psycopg.Connection) -> None:
    review = _scheduled(db, "Daily review")
    own = _step(db, review.id, "Water the plants", vertical="day", anchor_date=review.anchor_date)
    goals.update(db, owner=OWNER, id=own.id, repeat={"frequency": "weekly"})
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})
    goals.update(db, owner=OWNER, id=review.id, done=True)

    (copy,) = goals.children_of(db, owner=OWNER, id=_occurrence(db, review.id, 1))
    assert (copy.title, copy.repeat_rule, copy.repeat_series_id) == ("Water the plants", None, None), (
        "the step's own series goes on from the step itself; its copy is one more step of the new time"
    )


def test_a_dated_step_under_an_undated_one_comes_back_undated_and_completing_still_works(db: psycopg.Connection) -> None:
    """Parking a step leaves its own dated steps where they were. A dated step cannot be placed under an undated one, so
    its copy comes back undated, and the completion does not fail on it."""
    review = _scheduled(db, "Daily review")
    middle = _step(db, review.id, "Middle", vertical="day", anchor_date=review.anchor_date)
    _step(db, middle.id, "Deep", vertical="day", anchor_date=review.anchor_date)
    moves.park(db, owner=OWNER, id=middle.id)
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})

    goals.update(db, owner=OWNER, id=review.id, done=True)

    (new_middle,) = goals.children_of(db, owner=OWNER, id=_occurrence(db, review.id, 1))
    (new_deep,) = goals.children_of(db, owner=OWNER, id=new_middle.id)
    assert (new_middle.vertical, new_deep.vertical, new_deep.title) == (None, None, "Deep")


def _hidden(db: psycopg.Connection) -> set[str]:
    """Every goal a private flag covers, the flagged goal's own subtree included (`privacy.view`)."""
    return set(privacy.view(db, owner=OWNER)["hidden"])


def test_a_private_goal_comes_back_private_and_each_step_keeps_its_own_flag(db: psycopg.Connection) -> None:
    """The new time takes the finished goal's flag, each step copy its own step's, whatever the goal above it says."""
    review = _scheduled(db, "Private review")
    secret = _step(db, review.id, "A private step")
    public = _step(db, review.id, "A public step")
    _step(db, secret.id, "Public inside the private one")
    inner_private = _step(db, public.id, "Private inside the public one")
    for flagged in (review, secret, inner_private):
        goals.update(db, owner=OWNER, id=flagged.id, private=True)
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})

    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = goals.goal(db, owner=OWNER, id=_occurrence(db, review.id, 1)).goal
    assert again.private is True, "a private goal's next time is private"
    steps = goals.children_of(db, owner=OWNER, id=again.id)
    assert [(s.title, s.private) for s in steps] == [("A private step", True), ("A public step", False)]
    inside = {t.title: t.private for step in steps for t in goals.children_of(db, owner=OWNER, id=step.id)}
    assert inside == {"Public inside the private one": False, "Private inside the public one": True}
    hidden = _hidden(db)
    assert again.id in hidden and {s.id for s in steps} <= hidden, "the whole new time is hidden with privacy mode on"
    assert goals.goal(db, owner=OWNER, id=review.id).goal.private is True, "the finished time keeps its flag"


def test_a_public_goal_comes_back_public_and_a_private_step_stays_private(db: psycopg.Connection) -> None:
    review = _scheduled(db, "Public review")
    secret = _step(db, review.id, "A private step")
    _step(db, review.id, "A public step")
    goals.update(db, owner=OWNER, id=secret.id, private=True)
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})

    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = goals.goal(db, owner=OWNER, id=_occurrence(db, review.id, 1)).goal
    assert again.private is False
    steps = {s.title: s for s in goals.children_of(db, owner=OWNER, id=again.id)}
    assert {title: s.private for title, s in steps.items()} == {"A private step": True, "A public step": False}
    hidden = _hidden(db)
    assert steps["A private step"].id in hidden
    assert again.id not in hidden and steps["A public step"].id not in hidden


def test_a_private_goal_without_steps_comes_back_private(db: psycopg.Connection) -> None:
    first = _scheduled(db, "Private and alone")
    goals.update(db, owner=OWNER, id=first.id, private=True)
    goals.update(db, owner=OWNER, id=first.id, repeat={"frequency": "daily"})

    goals.update(db, owner=OWNER, id=first.id, done=True)

    assert goals.goal(db, owner=OWNER, id=_occurrence(db, first.id, 1)).goal.private is True


def test_the_new_time_and_its_steps_keep_the_documents_their_notes_link(db: psycopg.Connection) -> None:
    """Links live in the notes and `goal_doc_links` is read from them (`core/docs.py`), so the copies index their own: the
    goal's documents stay on the new time, and the document lists the new goal and step among its goals."""
    routine = docs.create(db, owner=OWNER, path="routine.md", title="Routine").doc
    notes = "[Routine](doc:routine.md)"
    review = _scheduled(db, "Daily review")
    goals.update(db, owner=OWNER, id=review.id, body=notes)
    _step(db, review.id, "Check the inbox", body=notes)
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "daily"})

    goals.update(db, owner=OWNER, id=review.id, done=True)

    again = _occurrence(db, review.id, 1)
    (step,) = goals.children_of(db, owner=OWNER, id=again)
    for goal_id in (again, step.id):
        assert [(link.doc_id, link.source) for link in docs.links_for_goal(db, owner=OWNER, goal_id=goal_id)] == [
            (routine.id, "goal")
        ]
    assert {again, step.id} <= {link.goal_id for link in docs.links_for_doc(db, owner=OWNER, doc_id=routine.id)}


def test_a_repeating_goal_cannot_move_to_life_and_ticking_it_makes_no_second_value(db: psycopg.Connection) -> None:
    """Life has no next period, so a repeat cannot be set there (`validate_target`) or reach it by a move: a goal moved there
    with its rule kept became a value whose tick made another value with the same title."""
    review = _scheduled(db, "Weekly review")
    goals.update(db, owner=OWNER, id=review.id, repeat={"frequency": "weekly"})

    with pytest.raises(ValidationError) as refused:
        moves.schedule(db, owner=OWNER, id=review.id, vertical="life", anchor_date=review.anchor_date)
    assert refused.value.detail["field"] == "repeat"
    stays = goals.goal(db, owner=OWNER, id=review.id).goal
    assert (stays.vertical, stays.repeat_rule) == ("day", {"frequency": "weekly", "interval": 1})

    goals.update(db, owner=OWNER, id=review.id, repeat=None)
    moved = moves.schedule(db, owner=OWNER, id=review.id, vertical="life", anchor_date=review.anchor_date).goal
    assert moved.vertical == "life", "with its repeat cleared it moves as any goal"
