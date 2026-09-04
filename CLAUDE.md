# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Human contributors should start with [`CONTRIBUTING.md`](CONTRIBUTING.md), which
covers the same ground in more detail.

## Project Overview

This is an NVDA add-on for DotPad braille displays. It connects over both
Bluetooth Low Energy and USB serial, and outputs braille text, tactile graphics,
charts and tables.

### Architecture

- **Core driver**: `addon/brailleDisplayDrivers/dotPad/` — `driver.py` is the
  `BrailleDisplayDriver` implementation; `protocol.py`, `tactileBuffer.py` and
  `writePlanner.py` hold the wire format, the cell buffer and the write batching.
- **TactileDisplayAPI**: `addon/tactileDisplayAPI/` — the bundled closed-source COM
  library and everything around it (`comLoader.py`, `comInterface.py`,
  `dispatchProxy.py`, `callbackServer.py`, `libraryWorker.py`, `iniPatcher.py`).
  This is the largest subsystem; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
  for what it bundles.
- **Presentations**: `addon/presentations/` — braille, graphic, chart, table and
  screen-capture modes, plus the manager that arbitrates between them.
- **BLE connectivity**: `addon/ble/` — BLE layer built on the bundled bleak library.
- **Configuration**: `addon/configuration.py` — settings with thread-safe caching.
- **Utilities**: `addon/utils/` — braille processing, drawing, charts, data handling.
- **Global plugin**: `addon/globalPlugins/dotPad/` — settings panel and global functionality.
- **Extension points**: `addon/extension_points/` — hooks other components subscribe to.
- **NVDA compatibility**: `addon/compat/` — shims over NVDA-version differences.
- **Review tracking**: `addon/visionEnhancementProviders/ReviewTracking.py` — cursor tracking.

## Contributor setup

Once per clone, register the textconv driver for the bundled per-locale
`TactileDisplayAPI.ini` files. They are UTF-16 LE and stored as binary so their
byte alignment survives; without this, `git diff` and `git log -p` show them as
unreadable blobs:

```bash
git config diff.utf16.textconv "python tools/textconvUtf16.py"
```

## Branching

`main` is the only long-lived branch. Branch off it and open pull requests
against it; a hook refuses commits made directly to `main`. Releases are cut from
`main` by tag — see `docs/releasing.md`.

## Build System

This project uses SCons for building:

```bash
uv run scons          # build the add-on
uv run scons dev=1    # build a development version
uv run scons pot      # generate the translation pot file
```

The build system is configured in `sconstruct` and `buildVars.py`. Project metadata
comes from `pyproject.toml`.

## Documentation

`docs/userGuide.md` is the user-facing guide shipped with the add-on: the build
copies it to `addon/doc/en/userGuide.md`, renders it to `userGuide.html`
(`buildVars.addon_docFileName`, what the add-on store's Help button opens), and the
Crowdin sync turns it into `dotPad.xliff` for translation. Keep it plain Markdown —
headings, paragraphs and simple lists — because `buildVars.markdownExtensions` is
empty and the XLIFF segmenter expects the same. Everything else under `docs/` is
developer documentation and is not shipped.

## Code Quality

### Linting and Formatting
```bash
uv run ruff format            # format
uv run ruff check --fix       # lint
uv run pyright <paths>        # type check
```

Always pass explicit paths to pyright — a bare run walks the whole tree and takes
several minutes. Type checking is only meaningful when `../nvda` sits at the ref CI
pins for linting.

### Git hooks
Hooks are configured in `prek.toml` and run via [`prek`](https://prek.j178.dev):
- ruff formatting and linting
- pyright type checking
- standard Python file checks
- refuses commits to `main`
- the two runtime-only rules below

### Two rules that fail at runtime, not at lint time

- **Never `from addon.X.Y import ...` or `import addon.X.Y` in add-on source.** NVDA
  does not load add-on files under an `addon` namespace at runtime, so the import
  raises `ModuleNotFoundError` the moment the module is first imported. Use a
  relative import. Tests are exempt — the unittest harness puts the repo root on
  `sys.path`.
- **Never `import pytest` in `tests/`.** The suite is `unittest` throughout and pytest
  is not installed in CI, so a top-level `import pytest` makes the module fail to load
  and every test inside is silently skipped.

### Testing

Tests are `unittest`, not pytest. They import NVDA modules, so they run against the
NVDA checkout's venv rather than the addon's own (which has a stubbed
`appModuleHandler` that fails to import). `scripts/runTests.ps1` wires that up and is
what CI runs:

```powershell
# Run the full suite
pwsh scripts/runTests.ps1

# Run a specific test module
pwsh scripts/runTests.ps1 tests.test_packet
```

Requires an NVDA source checkout at `../nvda` with a populated `.venv`. When working
from a git worktree, symlink the NVDA checkout in beside it so `../nvda` still
resolves.

## Code Style Guidelines

- Use tabs for indentation (configured in ruff)
- Line length: 110 characters
- Type annotations required (pyright strict mode)
- Follow NVDA coding standards
- Every source file we author carries the four-line GPL header — copy one from a
  neighbouring file and set the year
- Exclude vendored libraries (`addon/_vendor/`) from linting; they are regenerated by
  `build_vendor.py` and must not be hand-edited

## Logging

Ask whether a message needs to exist before asking which level it belongs at. INFO is
NVDA's default level and so reaches every user. Never use `log.io`, and never assert
on log output in tests.

## Key Dependencies

- NVDA source code (referenced via `../nvda/source` in pyproject.toml)
- Bundled bleak library for BLE communication
- Bundled TactileDisplayAPI COM library for multi-line braille and tactile graphics
- Python 3.13 (64-bit) required
- uv for package management

## Development Notes

- BLE functionality is conditionally imported to support unit testing
- Configuration uses thread-safe caching pattern
- Driver implements NVDA's BrailleDisplayDriver interface
- Review tracking integrates with NVDA's vision enhancement system
