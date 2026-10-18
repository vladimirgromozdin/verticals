"""A value's colour, given when a goal becomes a value without one.

D231 keeps colour on value roots only (parentless goals on the value scale) and derives every other card's colour from
its root at read time. It also took the colour picker out of the app, so a value made there had no colour, and nor did
anything under it. Now a goal that becomes a value without a colour takes one: the palette colour the fewest of the
owner's values have, ties going to the palette's order. A colour that a caller gives, or that a value already has, is
kept. Two values made at the same instant may take the same colour; it is only a look, so no lock is taken for it.
"""

from __future__ import annotations

import psycopg

from verticals.core import vertical as vertical_mod
from verticals.core.field_rules import VALUE_PALETTE


def assign(conn: psycopg.Connection, *, owner: str, id: str) -> str | None:
    """Give goal `id` a colour if it is a value without one. One statement; returns the colour it gave, else `None`."""
    row = conn.execute(
        """
        UPDATE goals g
           SET color = (
                 SELECT p.color
                   FROM unnest(%(palette)s::text[]) WITH ORDINALITY AS p(color, ord)
                  ORDER BY (SELECT count(*) FROM goals v
                             WHERE v.owner = g.owner AND v.parent_id IS NULL
                               AND v.vertical = %(scale)s::vertical_scale AND v.color = p.color),
                           p.ord
                  LIMIT 1)
         WHERE g.owner = %(owner)s AND g.id = %(id)s
           AND g.parent_id IS NULL AND g.vertical = %(scale)s::vertical_scale AND g.color IS NULL
        RETURNING g.color
        """,
        {"owner": owner, "id": id, "palette": list(VALUE_PALETTE), "scale": vertical_mod.VALUE_SCALE},
    ).fetchone()
    return row[0] if row else None
