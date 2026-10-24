# One swipe moves one window

A horizontal swipe between a task and a document changes the foreground window once. The gesture's trailing wheel
events keep that destination, including when the gesture reaches the first or last window. A pause of 300 ms ends the
gesture; another swipe can move again.

Vertical scrolling and horizontally overflowing content keep their own scroll instead of changing windows.

Checked in the live UI in both directions, at an edge, after a pause, and while scrolling document content.
