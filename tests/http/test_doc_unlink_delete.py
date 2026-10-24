"""Deleting a linked document is explicit, atomic, and leaves its tasks intact."""

import httpx


def test_delete_can_explicitly_remove_both_directions_of_task_links(client: httpx.Client) -> None:
    goal = client.post('/api/goals', json={'title': 'SYN keep this task'}).json()['id']
    doc = client.post('/api/docs', json={'path': 'syn/delete.md', 'title': 'SYN delete this document',
                      'body': f'[Task](goal:{goal})'}).json()['id']
    other = client.post('/api/docs', json={'path': 'syn/keep.md', 'title': 'SYN keep this document', 'body': 'Keep this too.'}).json()['id']
    client.patch(f'/api/goals/{goal}', json={'body': 'Keep these notes.\n\n[Document](doc:syn/delete.md)\n\nKeep these too.\n\n[Other](doc:syn/keep.md)'})
    refused = client.delete(f'/api/docs/{doc}')
    assert refused.status_code == 422
    assert client.get(f'/api/docs/{doc}').status_code == 200
    deleted = client.delete(f'/api/docs/{doc}?unlink=true')
    assert deleted.status_code == 204, deleted.text
    assert client.get(f'/api/docs/{doc}').status_code == 404
    remaining = client.get(f'/api/goals/{goal}').json()
    assert 'Keep these notes.' in remaining['body'] and 'Keep these too.' in remaining['body']
    assert 'doc:syn/delete.md' not in remaining['body']
    assert 'doc:syn/keep.md' in remaining['body']
    assert [item['id'] for item in remaining['docs']] == [other]
    assert client.get(f'/api/docs/{other}').status_code == 200
