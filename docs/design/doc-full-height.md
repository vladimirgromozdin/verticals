# A document stands full height

Today a document opens as a 720 × 738 card with 32 px above it and 153 px below.

## Behaviour

- A document's window runs the window's full height, half a pixel from the top and the bottom edges (one device pixel on a Retina screen), 720 px wide, its 24 px corners kept.
- The field stands over its foot on a white fade.
- Other open windows keep their 200 px at the sides, stepped back as today (`WindowStack.tsx`).

## Done when

The document's head offers Delete. A small confirmation names the document, says that its text and history will be
deleted, and tells how many tasks link it. Cancel leaves it intact. Confirm deletes the document and its links in one
transaction; those tasks and their other notes stay. The direct document view uses the same control.

API and MCP callers still get a refusal for a linked document by default. `unlink=true` explicitly opts into removing
its task links with it.

A UI test measures the window: 0.5 px from the top and the bottom, 720 px wide, corners kept, neighbours at the sides. Before and after pictures.
