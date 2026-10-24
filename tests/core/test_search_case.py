"""Unicode case-insensitive search, including desktop databases initialized with locale C."""
from datetime import date

import pytest

from verticals.core import goals, search


@pytest.mark.parametrize('query', ['рутина', 'РУТИНА', 'рУтИнА'])
@pytest.mark.parametrize('find', [search.search, search.search_with_parents])
def test_cyrillic_case_in_titles_and_notes(db, query, find):
    owner = 'SYN-case'
    title = goals.create(db, owner=owner, title='Рутина', vertical='life', anchor_date=date(2026, 10, 21)).goal.id
    notes = goals.create(db, owner=owner, title='SYN notes', body='Рутина', vertical='life', anchor_date=date(2026, 10, 21)).goal.id
    goals.create(db, owner=owner, title='SYN unrelated', vertical='life', anchor_date=date(2026, 10, 21))
    goals.create(db, owner='SYN-other', title='Рутина', vertical='life', anchor_date=date(2026, 10, 21))
    assert {g.id for g in find(db, owner=owner, q=query).goals} == {title, notes}


def test_unicode_search_index_matches_sequential_results(db):
    owner = 'SYN-index'
    target = goals.create(db, owner=owner, title='ЁЖИК РУТИНА', vertical='life', anchor_date=date(2026, 10, 21)).goal.id
    for query in ['ёжик', 'рутина']:
        db.execute('SET enable_seqscan = on')
        db.execute('SET enable_indexscan = off')
        db.execute('SET enable_bitmapscan = off')
        assert [g.id for g in search.search_with_parents(db, owner=owner, q=query).goals] == [target]
        db.execute('SET enable_seqscan = off')
        db.execute('SET enable_indexscan = on')
        db.execute('SET enable_bitmapscan = on')
        rows = db.execute('SELECT id FROM goals WHERE ' + search.TRIGRAM_PREDICATE,
                          {'pat': '%' + query + '%'}).fetchall()
        assert [row[0] for row in rows] == [target]
        assert [g.id for g in search.search_with_parents(db, owner=owner, q=query).goals] == [target]
    predicate = search.TRIGRAM_PREDICATE
    plan = db.execute('EXPLAIN SELECT id FROM goals WHERE ' + predicate, {'pat': '%рутина%'}).fetchall()
    assert 'goals_search' in str(plan), plan
