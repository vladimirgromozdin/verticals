"""A deleted goal can be brought back (docs/design/board-undo.md): `stash` copies the subtree aside just before
`core.goals.delete` removes it, and `restore` puts the copy back with the same ids.

**A copy, not a flag.** The alternative was a `deleted_at` column on `goals`. That puts `deleted_at IS NULL` into every
query that reads goals (the board, search, the tree walks, ideas, the undated list, spans, document links, evidence and
the MCP tools), and one forgotten filter shows a deleted goal. The copy touches no read: a deleted goal is gone for all
of them and exists only in `goal_trash` (migration 019).

**What is copied.** The goals of the subtree and every row that goes with them when they go: the tables whose foreign key
points at `goals` with `ON DELETE CASCADE`. `_CASCADED` names them, and `tests/core/test_trash.py` reads `pg_constraint`
and fails when a table with such a key is not named here, so a new table cannot be forgotten. Each row is stored as
`to_jsonb(row)` and comes back through `jsonb_populate_recordset`, so every column returns as it was, with the timestamps,
the position and the content revision. Nothing is listed column by column, and a column added later is carried as well.

**What `restore` does with a world that has moved on.** The goal comes back where it was when that is still possible.
- Its parent must still exist, must still take a goal of that scale (`core/placement.py`'s rule) and must be shallow
  enough for the subtree. If not, the goal comes back at the top level, with the paths and depths of its subtree rebuilt.
  Otherwise the paths and depths are rebuilt from the parent as it stands now, not as it stood.
- A position another goal has taken since is not shared: the restored goal goes before the one that took it.
- A document link to a document deleted in the meantime is dropped; the goal does not come back without it for that.
- A goal whose id is back already, or whose repeat slot another occurrence now holds, is refused, `ValidationError`.

Entries are kept `RETENTION_DAYS` and the owner's old ones are removed by the next `stash`, so nothing runs on a timer
(the same sweep `core/idem.py` makes for its table). IR-02: every function takes an open connection and never commits;
`owner` is keyword-only with no default.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from verticals.core import moves, placement, tree, value_colors
from verticals.core.errors import NotFound, ValidationError
from verticals.core.field_rules import require_str, validate_owner
from verticals.models import Goal

#: How long a deleted goal can be brought back. The page's history lasts as long as the page, and a session of the
#: desktop app can run for days.
RETENTION_DAYS = 30

#: Tables whose rows are copied with the goals and put back by `restore`, in the order they go back in. Each is a
#: foreign key to `goals` (or, for `comment_messages`, to `comment_threads`) with `ON DELETE CASCADE`.
CASCADED: tuple[str, ...] = (
    "goal_evidence",
    "due_acknowledgements",
    "goal_doc_links",
    "comment_threads",
    "comment_messages",
)

_SWEEP_SQL = """
    DELETE FROM goal_trash
     WHERE owner = %(owner)s
       AND deleted_at < clock_timestamp() - make_interval(days => %(days)s)
"""

# One statement builds the whole copy. `g` is the subtree (the root and every row under its path), and every other list
# is the rows that name one of its goals. `ESCAPE '\\'` is the LIKE escape `core/goals.py`'s own DELETE uses.
_STASH_SQL = """
    WITH g AS (
        SELECT * FROM goals
         WHERE owner = %(owner)s AND (id = %(id)s OR path LIKE %(pattern)s ESCAPE '\\')
    ), t AS (
        SELECT * FROM comment_threads
         WHERE owner = %(owner)s AND goal_id IN (SELECT id FROM g)
    )
    INSERT INTO goal_trash (owner, root_id, rows)
    SELECT %(owner)s, %(id)s, jsonb_build_object(
        'goals', (SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.depth, g.path), '[]'::jsonb) FROM g),
        'goal_evidence', (
            SELECT coalesce(jsonb_agg(to_jsonb(e)), '[]'::jsonb) FROM goal_evidence e
             WHERE e.owner = %(owner)s AND e.goal_id IN (SELECT id FROM g)),
        'due_acknowledgements', (
            SELECT coalesce(jsonb_agg(to_jsonb(a)), '[]'::jsonb) FROM due_acknowledgements a
             WHERE a.owner = %(owner)s AND a.goal_id IN (SELECT id FROM g)),
        'goal_doc_links', (
            SELECT coalesce(jsonb_agg(to_jsonb(l)), '[]'::jsonb) FROM goal_doc_links l
             WHERE l.owner = %(owner)s AND l.goal_id IN (SELECT id FROM g)),
        'comment_threads', (SELECT coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) FROM t),
        'comment_messages', (
            SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.created_at, m.id), '[]'::jsonb)
              FROM comment_messages m
             WHERE m.owner = %(owner)s AND m.thread_id IN (SELECT id FROM t))
    )
"""


@dataclass(frozen=True)
class Restored:
    """`restore`'s call envelope: the goal that was named, as it stands now, and how many goals came back with it
    (itself included)."""

    goal: Goal
    restored: int


def stash(conn: psycopg.Connection, *, owner: str, id: str, pattern: str) -> None:
    """Copy `id` and everything under it aside. Called by `core.goals.delete` inside its own transaction, after it has
    checked the delete may go ahead and before the rows are removed. `pattern` is the `LIKE` pattern of the root's path
    that `delete` already built (escaped), so both statements name the same rows."""
    owner = validate_owner(owner)
    id = require_str(id, "id")
    conn.execute(_SWEEP_SQL, {"owner": owner, "days": RETENTION_DAYS})
    conn.execute(_STASH_SQL, {"owner": owner, "id": id, "pattern": pattern})


def _place_under_parent(conn: psycopg.Connection, *, owner: str, rows: list[dict], root: dict) -> None:
    """Rebuild the subtree's `parent_id`, `path` and `depth` against the world as it is now (see the module note)."""
    old_path, old_depth = root["path"], root["depth"]
    height = max(r["depth"] for r in rows) - old_depth
    parent = None
    if root["parent_id"] is not None:
        found = conn.execute(
            "SELECT path, depth, vertical FROM goals WHERE owner = %(owner)s AND id = %(id)s FOR SHARE",
            {"owner": owner, "id": root["parent_id"]},
        ).fetchone()
        if found is not None:
            path, depth, vertical = found
            try:
                placement.validate_child_vertical(
                    child_vertical=root["vertical"], parent_vertical=vertical,
                    child_id=root["id"], parent_id=root["parent_id"],
                )
                if depth + 1 + height <= tree.MAX_DEPTH:
                    parent = (path, depth)
            except ValidationError:
                parent = None
    if parent is None:
        root["parent_id"] = None
        new_path, new_depth = f"/{root['id']}/", 0
    else:
        new_path, new_depth = f"{parent[0]}{root['id']}/", parent[1] + 1
    for row in rows:
        row["path"] = new_path + row["path"][len(old_path):]
        row["depth"] = new_depth + row["depth"] - old_depth


def _free_position(conn: psycopg.Connection, *, owner: str, row: dict) -> None:
    """Move `row` before the goal that has taken its position since, when one has. A sibling group is a column
    (`vertical`, `period_key`) when the goal is scheduled and the parent's list when it is not (`core/tree.py`)."""
    where = (
        "vertical = %(vertical)s::vertical_scale AND period_key = %(period_key)s"
        if row["vertical"] is not None
        else "vertical IS NULL AND parent_id IS NOT DISTINCT FROM %(parent_id)s"
    )
    params = {
        "owner": owner, "vertical": row["vertical"], "period_key": row["period_key"],
        "parent_id": row["parent_id"], "position": row["position"],
    }
    clash = conn.execute(
        f"SELECT id FROM goals WHERE owner = %(owner)s AND {where} AND position = %(position)s"
        " ORDER BY id LIMIT 1",
        params,
    ).fetchone()
    if clash is None:
        return
    before = conn.execute(
        f"SELECT id FROM goals WHERE owner = %(owner)s AND {where} AND position < %(position)s"
        " ORDER BY position DESC, id DESC LIMIT 1",
        params,
    ).fetchone()
    row["position"] = moves.allocate_position(
        conn, owner=owner, vertical=row["vertical"], period_key=row["period_key"],
        parent_id=row["parent_id"], after_id=before[0] if before else None, before_id=clash[0],
    )


def restore(conn: psycopg.Connection, *, owner: str, id: str) -> Restored:
    """Bring back the newest deletion that named `id`, with everything that went with it. `NotFound` when nothing under
    that id is in the trash (never deleted, swept, or already restored)."""
    owner = validate_owner(owner)
    id = require_str(id, "id")
    with conn.transaction():
        found = conn.execute(
            "SELECT id, rows FROM goal_trash WHERE owner = %(owner)s AND root_id = %(id)s"
            " ORDER BY deleted_at DESC, id DESC LIMIT 1 FOR UPDATE",
            {"owner": owner, "id": id},
        ).fetchone()
        if found is None:
            raise NotFound(f"nothing deleted under {id!r} to restore for owner {owner!r}", id=id, owner=owner)
        trash_id, rows = found
        goal_rows: list[dict] = rows["goals"]
        ids = [r["id"] for r in goal_rows]

        back = conn.execute(
            "SELECT id FROM goals WHERE owner = %(owner)s AND id = ANY(%(ids)s) ORDER BY id LIMIT 1",
            {"owner": owner, "ids": ids},
        ).fetchone()
        if back is not None:
            raise ValidationError(f"goal {back[0]!r} exists already; there is nothing to restore", field="id", id=back[0])

        root = next(r for r in goal_rows if r["id"] == id)
        _place_under_parent(conn, owner=owner, rows=goal_rows, root=root)
        for row in goal_rows:
            _free_position(conn, owner=owner, row=row)

        try:
            conn.execute(
                "INSERT INTO goals SELECT r.* FROM jsonb_populate_recordset(NULL::goals, %(rows)s) AS r"
                " WHERE r.owner = %(owner)s",
                {"owner": owner, "rows": Jsonb(goal_rows)},
            )
            for table in CASCADED:
                if table == "goal_doc_links":
                    # A document deleted since is not brought back for the link's sake.
                    conn.execute(
                        "INSERT INTO goal_doc_links SELECT r.* FROM jsonb_populate_recordset("
                        "NULL::goal_doc_links, %(rows)s) AS r WHERE r.owner = %(owner)s AND EXISTS ("
                        "SELECT 1 FROM docs d WHERE d.owner = r.owner AND d.id = r.doc_id)",
                        {"owner": owner, "rows": Jsonb(rows.get(table, []))},
                    )
                else:
                    conn.execute(
                        f"INSERT INTO {table} SELECT * FROM jsonb_populate_recordset(NULL::{table}, %(rows)s)",
                        {"rows": Jsonb(rows.get(table, []))},
                    )
        except psycopg.errors.UniqueViolation as exc:
            raise ValidationError(
                "a goal now holds the repeat slot of one of the goals to restore", field="id", id=id,
            ) from exc

        conn.execute(
            "DELETE FROM goal_trash WHERE owner = %(owner)s AND id = %(trash_id)s",
            {"owner": owner, "trash_id": trash_id},
        )
        value_colors.assign(conn, owner=owner, id=id)  # a life step whose parent is gone comes back as a value
        goal = conn.execute(
            f"SELECT {tree.COLUMNS} FROM goals WHERE owner = %(owner)s AND id = %(id)s",
            {"owner": owner, "id": id},
        ).fetchone()
    return Restored(goal=tree._to_goal(goal), restored=len(goal_rows))
