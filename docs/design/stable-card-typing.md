# A stable task behind the conversation

Typing in the shared field still filters and highlights the board. A task opened in a window,
including its children, does not take those search highlights or the grey styling for context
ancestors. Its title and colour stay steady while the person writes in the conversation.

Changes to the task itself still update the window and its blurred copies. Opening the chat,
closing it and switching between a task and a document keep their existing transitions.

## Verification

The regression test drives the real UI and gateway with synthetic data. It covers parent and
child title matches, unrelated text, deletion, paste, cursor movement and a newline; window
DOM stays stable, while a title edited in the window reaches the live card and its blurred
copies when the chat reopens. A separate control keeps board search highlighting enabled.

Chromium and Playwright WebKit recordings cover a green task with a document beside it,
normal motion and a narrower window with reduced motion and the dark system preference.
The current UI retains its light surface under that preference.

A native WKWebView loaded the production bundle and captured 45 actual window screenshots
while changing the draft, including pauses, paste and deletion. The background card region
was pixel-identical in every capture. The beginning, middle and end were inspected visually.
This resolves the earlier snapshot-only anomaly: one of 131 WebKit snapshots had differed,
but that did not establish a visible screen flicker.

The combined package passed an isolated upgrade check, preserving all rows and the schema.
Acceptance in the owner's installed app awaits the macOS Documents permission requested
after the local package was signed. No claim is made that every possible compositor issue
is covered by the demonstrated typing scenario.

Synthetic evidence: [before](../screenshots/stable-card-typing/before.png),
[after](../screenshots/stable-card-typing/after.png),
[native window screenshot](../screenshots/stable-card-typing/native-screen.png).

An additional probe found that an external API rename does not refresh the already-open task
window through the board change feed. The current live-board reload fetches board rows, not
the open detail; that existing limitation is outside this highlighting change.
