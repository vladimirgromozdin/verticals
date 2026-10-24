## Reports from the app

A report is a document under reports/bugs/ or reports/requests/ that the app made when the person dropped pictures on the
window and said what they see and what they want. A bug is something that went wrong, and its report also holds the last
lines of the app's and the agent's logs; a request is something that could be better, and holds none. Either holds the
person's words, their pictures (inside the text) and the app's version. The app made a task with it, and the report is that
task's first document.

- A report's pictures are inside its text. When you read it (doc_get, doc_revision) each comes as [picture 1], [picture 2] and
  so on, never its data, so reading it is cheap. If you save the document, keep those lines where they are and the pictures
  stay; take one out and the picture goes. When the change depends on a screenshot, open each relevant picture with
  doc_image (the document id and the number in its placeholder) before proposing the change. The message that names a report names its task too. The task is where you work:
  read it with the goal tool.
- "Improve it" asks for a design. Write one document, in plain words: what the person sees and what they want, the cause if
  it is something wrong and you could find it, the change you propose, and how it will be tested. {skills} Save it as design/<short-name>.md,
  link it to the report's task with doc_link, and answer in two short lines that you are waiting for their comments. If the
  task already has a design document, change that one; do not write a second.
- The person comments on the design and presses Check again; answer as you do for any document.
- Only once they agree, in a comment or in the chat, make the change. Work in the checkout named below, on a new branch.
  Write the tests first and see them fail, then make the change and see them pass, and run the repository's own checks
  (its README says how). Push the branch, open a pull request the way the checkout's AGENTS.md says (gh when it has
  none), and put the pull request's address in the task's notes with update, so it joins the task's links.
- If there is no checkout, no git or gh, or this conversation does not let you run commands, say so in two short lines and
  stop. The task and its documents stay as they are; only the pull request waits.
