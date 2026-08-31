---
description: Cut a dev, beta or stable release: pick the version, move the changelog entries, update the store's what's-new text, dispatch the release workflow, and submit to the add-on store.
---

# Cutting a Release

**Announce at start:** "I'm using the cut-a-release command to guide this release."

Background on why the rules are what they are: [`docs/releasing.md`](../../docs/releasing.md).
Read it if any step below looks arbitrary — the constraints come from the add-on
store, not from taste.

## Step 0: Establish the release type and version

Ask the user for the release type if they have not said. Then derive the version:

| Type | Version | GitHub |
|------|---------|--------|
| `dev` | next free `x.y.9z` | prerelease |
| `beta` | next free `x.y.9z` | prerelease |
| `stable` | `x.y.z` | not a prerelease |

Every release is cut from `main`; there is no other long-lived branch.

The store has **no pre-release syntax** — a version is 2-3 dot-separated
integers and nothing else. `1.0.0-beta1` is not expressible. The `.9x` band is
the convention: `0.9.90` precedes `1.0.0`, `1.0.90` precedes `1.1.0`.

Check what is already published before choosing, so the number is free:

```powershell
gh release list --limit 15
```

`0.0.x` is reserved for per-commit CI builds. Never cut a release there.

## Step 1: Move the CHANGELOG entries — **stable only**

**For a dev or beta release, skip this step entirely. Do not rename
`## [Unreleased]`, and do not open a new one.**

Pre-release builds get no `CHANGELOG.md` section of their own. Their entries
stay under `[Unreleased]` until the stable ships, which is what makes the whole
release worth of changes available to describe them: the workflow copies that
section into the beta's release body so testers can see what they are running.
Renaming it for a beta empties that section, and the release body degrades to a
collapsed block of bare headings that reads as "nothing changed in this build".
It would also split one release's entries across several beta headings, so the
eventual stable would document only what landed after the last beta.

For a **stable** release:

1. Rename `## [Unreleased]` to `## [<version>] - <YYYY-MM-DD>`.
2. Add a fresh `## [Unreleased]` above it, with the same subsection headings
   (`### Added`, `### Changed`, `### Fixed`, `### Known Issues`,
   `### Changes for developers`) left empty.

Keep `### Known Issues` entries that are still true in the released section
**and** copy them forward — they describe the shipped build.

## Step 2: Update the store's what's-new text

You do not touch `pyproject.toml`. For a stable the release workflow writes the
version (and the matching root version in `uv.lock`); for dev and beta the
version lives only in the tag and the GitHub release.

`buildVars.addon_changelog` is shown to users in the add-on store. It is not
the CHANGELOG: it is a short summary of what this release means for a user.

**Draft it, then hand the user the decision.** Do not ship your own wording
unreviewed, and do not make the user write it from a blank page either.

Write a draft from the `## [Unreleased]` entries moved in Step 1:

- First line must read `New in version <major>.<minor>:`, naming **the release
  this text describes** — for a beta, the release it previews, so a `1.0.90`
  beta of 1.1 reads `New in version 1.1`. A unit test rejects a header older
  than `pyproject.toml`, which is what catches a stale one left over from the
  last release.
- Five or six bullets, user-facing language, no file or symbol names.
- Lead with the change that **defines** the release, which is often not the
  largest diff. A user cares that rendering moved to the library, not that the
  library was later bumped a version.

Apply the draft to `buildVars.py`, show it in the conversation, and offer three
options explicitly:

1. **Approve** — keep it as written and continue.
2. **Edit** — it is already in `buildVars.py`; the user opens the file, corrects
   it in place, and tells you when to continue. Re-read the file before
   continuing; do not carry your draft forward from memory.
3. **Discard** — revert the draft (`git checkout buildVars.py` if nothing else
   is staged there) and use the wording the user supplies instead.

Do not proceed to Step 3 until one of the three has been chosen.

The string is a `_()` literal, so **editing it invalidates existing
translations** of it. That is the cost of any rewording, including a correction
to your own draft — worth it for accuracy, not worth it for polish.

## Step 3: Verify

```powershell
pwsh scripts/runTests.ps1
```

`tests/test_releaseMetadata.py` fails if the what's-new header is older than the
project version, or if `CHANGELOG.md` has lost its `[Unreleased]` section. All
tests must pass.

Then confirm the build stamps what you expect:

```powershell
uv run scons
```

Expect `dotPad-<version>.nvda-addon` — but note that for **dev and beta** the
version in `pyproject.toml` is *not* bumped (see Step 2), so a local build
shows the last stable version. That is correct, not a bug.

## Step 4: Cut it

Commit whatever Steps 1-2 changed — for a dev or beta that is only the
what's-new text, if it needed touching at all — and get it onto `main` first,
through a pull request.

Then Actions → **Manual release** → Run workflow from `main`, and fill in the
version and release type.

The workflow validates the type and version before it builds, so a bad version
fails without publishing anything. Only a stable carries its
version in `pyproject.toml`, written by the workflow along with the root version
in `uv.lock`; dev and beta carry the version in the tag and the GitHub release
only.

## Step 5: Submit to the add-on store (optional, manual)

Nothing about this is automatic, and it cannot be — the datastore's intake
fires on an issue **label** that only the web form applies.

1. Get the `.nvda-addon` asset's download URL from the release.
2. Open the [registration form](https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml).
3. Channel: match the release type (`dev` / `beta` / `stable`).
4. Submit, then watch the generated PR for validation failures.

Before submitting to **stable**, check that `addon_lastTestedNVDAVersion` does
not name an API version flagged `"experimental": true` in the datastore's
`transform/nvdaAPIVersions.json` — such a submission is forced onto beta or dev:

```powershell
gh api repos/nvaccess/addon-datastore/contents/transform/nvdaAPIVersions.json `
  -H "Accept: application/vnd.github.raw"
```

## Do not

- Invent a version the user has not agreed to.
- Rename `## [Unreleased]` for a dev or beta release — that section is what the
  release body shows testers, and renaming it leaves them with empty headings.
- Continue past Step 2 on your own draft without an explicit approve / edit /
  discard from the user — it is translated text shipped to users.
- Submit a `0.0.x` CI build to the store.
