"""Delete a document with its task links when the caller explicitly requests it."""

import re

import psycopg

from verticals.core import docs, goals


def without_doc_links(body: str, path: str) -> str:
    pattern = re.compile(r"\[[^\]]*\]\(\s*doc:" + re.escape(path) + r"\s*\)")
    kept = []
    for line in body.split('\n'):
        stripped = pattern.sub('', line)
        if stripped != line and not stripped.strip():
            continue
        kept.append(stripped)
    return '\n'.join(kept)


def unlink_and_delete(conn: psycopg.Connection, *, owner: str, id: str) -> None:
    with conn.transaction():
        conn.execute('SELECT 1 FROM docs WHERE owner = %s AND id = %s FOR UPDATE', (owner, id))
        doc = docs.get(conn, owner=owner, id=id)
        links = docs.links_for_doc(conn, owner=owner, doc_id=id)
        for goal_id in sorted({link.goal_id for link in links if link.source == 'goal'}):
            conn.execute('SELECT 1 FROM goals WHERE owner = %s AND id = %s FOR UPDATE', (owner, goal_id))
            goal = goals.goal(conn, owner=owner, id=goal_id).goal
            goals.update(conn, owner=owner, id=goal_id, body=without_doc_links(goal.body, doc.path))
        if any(link.source == 'doc' for link in links):
            docs.save(conn, owner=owner, id=id, expected_revision=doc.revision, body='')
        docs.delete(conn, owner=owner, id=id)
