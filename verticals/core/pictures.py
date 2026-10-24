"""Pictures inside a text (docs/design/bug-reports.md): a screenshot has no address to point at, so it travels in the body as
a data URL, `![alt](data:image/jpeg;base64,/9j/…)`: a report of a few pictures is hundreds of kilobytes of base64. The
person's own view draws them. Everything else that reads the text is better off without the data:

  * an **agent** reading a document or a goal through the MCP tools gets each picture as a short placeholder,
    `[picture 1]`, and every word of the text as it is (`for_agent`). When it writes the text back, a placeholder it kept
    becomes the picture it stood for (`from_agent`), so editing the words of a report never costs it its pictures; one it
    took out is a picture taken out. Placeholders count the pictures of the text being read, from 1, in the order they
    stand, and mean the pictures of the stored text the write replaces (the write is optimistically locked on that text's
    revision, so the two are the same text).
  * an **excerpt** (the page a document chip draws, the Documents desk's previews) shows no picture at all
    (`without_pictures`): cut at a fixed length, a data URL would print as base64 on the page.

The one pattern below is read by Python's `re` and by PostgreSQL's regular expressions alike (docs_desk.py cuts excerpts in
SQL, where it must not pull a whole body), so it uses nothing the two do not share.

Pure functions, no SQL: `core/` owns the rules and the transports (MCP, HTTP) apply them where they hand text over.
"""

from __future__ import annotations

import re

from verticals.core.errors import ValidationError

# A markdown image whose address is an inline raster picture (the bodies' own allowlist, web/src/lib/bodyMarkdown.ts: no SVG,
# which is a document and not a picture). The alt text is one short line and the data is base64 alone, both bounded by what
# they may hold, so a text that only looks like a picture (`![` over and over, no end) costs one pass and not one per start.
# PostgreSQL's regular expressions take a repetition count of 255 at the most.
ALT_CHARS = 250
PICTURE = r"!\[[^\]\n]{0,%d}\]\(data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=_-]*\)" % ALT_CHARS
_PICTURE_RE = re.compile(PICTURE, re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(r"\[picture (\d+)\]")
_MARK_RE = re.compile(r"data:image/", re.IGNORECASE)


def for_agent(body: str, *, numbered: bool = True) -> str:
    """The text as an agent reads it: each picture a placeholder `[picture N]`, N counting from 1 in the order they stand.
    Unnumbered, `[picture]`, for a text made of many (an outline of goals), where no one number could mean one picture; it is
    only to be read, and an agent that means to edit a goal reads that goal."""
    if not _MARK_RE.search(body):
        return body
    count = 0

    def placeholder(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"[picture {count}]" if numbered else "[picture]"

    return _PICTURE_RE.sub(placeholder, body)


def image_at(body: str, index: int) -> tuple[str, str]:
    """The requested inline picture as MIME type and base64, with the text read's numbering."""
    if type(index) is not int or index < 1:
        raise ValidationError("picture must be a positive integer", field="picture")
    for number, found in enumerate(_PICTURE_RE.finditer(body), 1):
        if number == index:
            match = re.search(r'\(data:(image/[^;]+);base64,([^)]*)\)$', found.group(0), re.IGNORECASE)
            assert match is not None
            mime, data = match.groups()
            return mime.lower(), data
    raise ValidationError(f"picture {index} does not exist in this document", field="picture")


def from_agent(body: str, stored: str) -> str:
    """The text an agent wrote back, with each placeholder it kept turned back into the picture it stood for: the Nth picture
    of `stored`, the text it replaces. A placeholder with no such picture is only text, as it is when the stored text has
    none."""
    if "[picture " not in body or not _MARK_RE.search(stored):
        return body
    pictures = [found.group(0) for found in _PICTURE_RE.finditer(stored)]

    def picture(found: re.Match[str]) -> str:
        n = int(found.group(1))
        return pictures[n - 1] if 1 <= n <= len(pictures) else found.group(0)

    return _PLACEHOLDER_RE.sub(picture, body)


def without_pictures(body: str) -> str:
    """The text with every picture left out, for an excerpt."""
    if not _MARK_RE.search(body):
        return body
    return _PICTURE_RE.sub("", body)
