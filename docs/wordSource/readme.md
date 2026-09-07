# Word source of the user guide

`NVDA Dot Pad Add-on Guide.docx` is Dot's review copy of the user guide — the
document that circulates by email between Dot and this project for comment.

**[`docs/userGuide.md`](../userGuide.md) is canonical.** It is what the build
ships, what the add-on store's Help button opens and what Crowdin translates.
Nothing here is shipped or built.

This copy is an archival snapshot, kept so the two versions can be compared
without digging through a mailbox. Don't treat it as a second place to edit:

- Changes to the guide are made in `docs/userGuide.md`, in Markdown.
- When Dot sends a revised document, replace this file wholesale and port the
  changes over. When the Markdown changes in a way Dot's reviewers need to see,
  edit this file to match and mail it on.
- Nothing checks that the two agree. `docs/keymap.md` is generated from the
  `@script` bindings and CI fails on drift; neither of these documents is, so
  key bindings in both are maintained by hand and can silently fall behind.
  When you change a binding, all three need attention.

`git diff` renders this file as text once the textconv driver is registered —
see "Contributor setup" in [`CONTRIBUTING.md`](../../CONTRIBUTING.md). The
driver reads paragraph text and styles only, so formatting, comments, tracked
changes and images do not show up in a diff.
