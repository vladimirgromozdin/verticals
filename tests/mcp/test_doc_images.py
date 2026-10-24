"""Pictures remain cheap in text reads and can be opened as image content on demand."""

from pathlib import Path

import anyio
import psycopg

from verticals.core import docs
from tests.mcp.conftest import open_mcp_stdio

PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jVJkAAAAASUVORK5CYII='
SECOND_PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='


async def _read_images(dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        other = docs.create(conn, owner='t2', path='syn/private.md', title=None, body=f'![Private](data:image/png;base64,{PIXEL})').doc.id
    async with open_mcp_stdio(dsn, tmp_path, label='doc-images') as (session, _):
        made = await session.call_tool('doc_create', {'path': 'syn/images.md', 'body':
             f'Before\n\n![First](data:image/png;base64,{PIXEL})\n\nBetween\n\n![Second](data:image/PNG;BASE64,{SECOND_PIXEL})'})
        id = made.structured_content['doc']['id']
        text = await session.call_tool('doc_get', {'id': id})
        assert text.structured_content['doc']['body'] == 'Before\n\n[picture 1]\n\nBetween\n\n[picture 2]'
        for index in [1, 2]:
            result = await session.call_tool('doc_image', {'id': id, 'picture': index})
            assert not result.is_error, result.content
            pictures = [block for block in result.content if block.type == 'image']
            assert len(pictures) == 1
            assert pictures[0].data == [PIXEL, SECOND_PIXEL][index - 1]
            assert pictures[0].mime_type == 'image/png'
        for index in [0, -1, 3, True, '1']:
            result = await session.call_tool('doc_image', {'id': id, 'picture': index})
            assert result.is_error, f'invalid picture index was accepted: {index!r}'
            assert not any(block.type == 'image' for block in result.content)
        denied = await session.call_tool('doc_image', {'id': other, 'picture': 1})
        assert denied.is_error
        assert not any(block.type == 'image' for block in denied.content)
        unchanged = await session.call_tool('doc_get', {'id': id})
        assert unchanged.structured_content['doc']['revision'] == 1


def test_an_agent_can_see_the_picture_it_requests_without_a_text_payload_or_write(f2_dsn: str, tmp_path: Path) -> None:
    anyio.run(_read_images, f2_dsn, tmp_path)
