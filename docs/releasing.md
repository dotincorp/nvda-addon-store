# Releasing

## What the add-on store allows

NVDA parses an add-on version as **two or three dot-separated integers** and
nothing else (`addonStore/models/version.py`: `int()` on each part, 2-3 parts).
There is no way to express a pre-release: `1.1.0-beta1`, `0.3.0rc1` and
`0.2.0.dev5` all fail to parse, and an unparseable version means NVDA cannot
compare the add-on against a store entry at all.

Updates are decided by a plain numeric comparison — `availableAddon
.addonVersionNumber > baseAddon.addonVersionNumber`. The channel is only a
filter over which entries are considered; it never enters the comparison.

Versions are also **unique per add-on across all channels**: the datastore holds
one `addons/dotPad/<version>.json` per version, each naming a single channel, so
a build cannot be promoted from dev to stable without a new number.

## The scheme

| What | Version | Notes |
|------|---------|-------|
| Per-commit build from `main` | `0.0.<run_number>` | Automatic, GitHub-only, never submitted to the store |
| Beta toward the next minor | `<major>.<minor>.90`, `.91`, … | Hand-cut; sorts above the current patch line and below the next minor |
| Release | `<major>.<minor>.<patch>` | Hand-cut |

Because a pre-release cannot be spelled in the number, the `.9x` band is the
convention that gets closest: `1.0.90` reads as "approaching 1.1.0" and sorts
between `1.0.x` and `1.1.0`. Before 1.0 the same applies — `0.9.90` precedes
`1.0.0`. The channel chosen at submission (`dev` / `beta` / `stable`) is what
the store actually shows users; the number only has to sort correctly.

`0.0.x` is reserved for per-commit builds so they can never outrank a release.
A date-derived version such as `2026.8.16` would outrank `1.0.0` permanently,
which is why we don't use one.

## Cutting a release

`manualRelease.yaml` (Actions → Manual release → Run workflow) takes a version
and a release type. Every release is cut from `main`, the project's only
long-lived branch:

| Release type | GitHub release | Version written to `pyproject.toml` |
|--------------|----------------|--------------------------------------|
| `dev`, `beta` | marked prerelease | no |
| `stable` | not a prerelease | yes |

It rejects a version that is not 2-3 dot-separated integers, and any
release in the reserved `0.0.x` band — the per-commit builds already occupy
it, so a hand-cut release there would clash with their numbers.

Only a **stable** release carries its version in `pyproject.toml`, which holds
the one authoritative version line. Dev and beta cuts carry their version in the
tag and the GitHub release only: writing them back would leave the branch stamped
with an already-published pre-release number, and would put a version-bump commit
on `main` for every test build. The build is unaffected either way — scons'
`version=` overrides whatever `buildVars.py` read out of `pyproject.toml`.

For a stable the workflow rewrites `pyproject.toml` and the matching root
version in `uv.lock` — the lock records the root project's own version, and the
build runs `uv sync --locked`, which refuses a lock that disagrees — then
commits only if that changed anything.

Only a **stable** release moves entries out of `[Unreleased]` into a section of
its own. Dev and beta builds leave that section untouched — it is what the
release body shows their testers, and emptying it would leave them with a
collapsed block of bare headings.

### What testers get in the release body

Dev and beta builds never get a `CHANGELOG.md` section of their own, so the
workflow composes one into the GitHub release:

- a **compare link** against the previous numbered release, for the raw diff;
- for dev and beta, the current `[Unreleased]` section, collapsed behind a
  `<details>` block — it covers everything since the last stable, so leaving it
  expanded would bury the build-to-build delta;
- GitHub's own generated list of merged PRs, appended below, which is the
  build-to-build delta and the closest thing to "what changed since the beta I
  already have".

That last one is pinned to the previous *numbered* tag via
`generateReleaseNotesPreviousTag`. Left to itself GitHub picks the most recent
tag, which is normally `latest` from the per-commit workflow — a moving
pointer, and a meaningless baseline.

The release type does **not** set the store channel — that is still chosen by
hand on the submission form. It sets GitHub's prerelease flag, decides whether
the version is written back to `pyproject.toml`, and gates the version checks.

## Submitting to the store

Nothing is automatic. The datastore's intake
(`.github/workflows/sendJsonFile.yml`) triggers on an issue being **labelled**
`autoSubmissionFromIssue`, and GitHub only applies an issue form's labels when
the form is submitted through the web UI — an issue opened via the API arrives
unlabelled, and we have no permission to label it afterwards. So each submission
is a human filling in the
[registration form](https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml).

`lastTestedNVDAVersion` gates which channel is available: if it names an API
version flagged `"experimental": true` in the datastore's
`transform/nvdaAPIVersions.json`, the submission must go to `beta` or `dev`. See
the comment on `addon_lastTestedNVDAVersion` in `buildVars.py`.

## Keeping the release metadata honest

Two places name the version and both used to rot silently:

- `pyproject.toml` `[project] version` — the number everything else derives from.
- `buildVars.addon_changelog` — the "what's new" text the **store shows users**.
  It announced "New in version 0.2" and that release's three features for as
  long as the version sat at 0.2.0, because nothing connected the two.

`addon_changelog` cannot be generated from this changelog at build time: `_` is
an identity marker (`site_scons/site_tools/NVDATool/utils.py`) and xgettext
extracts translatable strings by scanning the source, so the argument must stay
a literal or the string stops being translatable. So it is checked instead —
`tests/test_releaseMetadata.py` fails the build if the what's-new header is
*older* than the project version — staleness being the failure that actually
happens — or if `CHANGELOG.md` has lost its `[Unreleased]` section. A header
naming a newer version passes, so the text can be written before the version
moves, and a beta can name the release it previews.

One consequence of dev and beta not bumping `pyproject.toml`: `sconstruct`'s
`gettext_package_version` reads `buildVars.addon_info` directly rather than the
build-time `env["addon_info"]`, so a `.pot` generated from a pre-release tree
carries the last stable version in its `Project-Id-Version` header. Everything
that reaches users — the manifest version, the artifact filename, the docs
title — comes from the build-time version and is correct. `scons pot` is run
separately from releasing, so this has not mattered in practice.

The step-by-step procedure, for a human or an agent, is
[`.claude/commands/cut-a-release.md`](../.claude/commands/cut-a-release.md). It
drafts the what's-new text from the `[Unreleased]` entries and then stops for an
explicit approve / edit / discard: the text is translated and user-facing, so it
is not an agent's call, but a blank page is not much help either.

## A note for testers on side-loaded builds

A side-loaded add-on has no store channel, so NVDA records it as `EXTERNAL`. The
default per-add-on update preference is `Same` (`defaultUpdateChannel = 0`),
which resolves to `{EXTERNAL}` — and no store entry ever carries that channel,
so **side-loaded builds are excluded from automatic update notifications**
regardless of their version number. Testers who want store updates should either
install from the store once a version is published, or set the add-on's update
channel to `Any`. The build still appears manually under the store's
"Updatable add-ons" tab.
