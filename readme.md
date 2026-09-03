# NVDA Add-on for DotPad

Support for [Dot Pad](https://dotincorp.com/) tactile graphics displays in the
[NVDA screen reader](https://www.nvaccess.org/). The add-on drives the Dot Pad
over both Bluetooth Low Energy and USB, and renders braille text, tactile
graphics, charts and tables on the multi-line tactile area.

This package is distributed under the terms of the GNU General Public License,
version 2 or later. Please see the file [`COPYING.txt`](COPYING.txt) for further
details, and [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the licences
of the bundled third-party components.

## Requirements

NVDA 2026.1 or later, 64-bit. Earlier versions are not supported: the
TactileDisplayAPI library that drives multi-line braille, tactile graphic mode
and the on-screen viewer is 64-bit only.

## Installation

Install the `.nvda-addon` file from the
[releases page](https://github.com/dotincorp/nvda-addon-store/releases), or
through NVDA's add-on store.

NVDA does not detect Dot Pad displays automatically by default, so the add-on
asks during installation whether you want to enable automatic detection of the
Dot Pad. The question is only asked once. You can change the setting at any time
in NVDA's braille settings, under "Displays to detect automatically".

The add-on also asks whether to turn off NVDA's blinking braille cursor. Dot
Pad cells refresh slowly, and not reliably at all while you are touching them,
so a blinking cursor is of little use. NVDA has one blinking setting for all
braille displays, so answering yes turns blinking off on every display you use.
This question is likewise only asked once, and can be changed at any time in
NVDA's braille settings, under "Blink cursor".

## Gestures

The full keymap — short / long-press conventions, mode-switch chords,
graphic-mode viewport pan, edge jumps, zoom, and the firmware-reserved gestures —
is documented in [`docs/keymap.md`](docs/keymap.md).

## Building from source

Requires Python 3.13 (64-bit) and [uv](https://docs.astral.sh/uv/).

```bash
uv run scons          # build the add-on
uv run scons dev=1    # build a development version
uv run scons pot      # regenerate the translation template
```

The build produces a `.nvda-addon` file in the repository root.

## Running the tests

The tests import NVDA modules, so they run against an NVDA source checkout
rather than this project's own environment. Clone
[nvaccess/nvda](https://github.com/nvaccess/nvda) alongside this repository at
`../nvda` and populate its `.venv`, then:

```powershell
pwsh scripts/runTests.ps1                    # the full suite
pwsh scripts/runTests.ps1 tests.test_packet  # a single module
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development setup, coding
standards and branch conventions.

## Reporting problems

Please open an issue on the
[issue tracker](https://github.com/dotincorp/nvda-addon-store/issues). An NVDA
log at debug level is usually essential — set the logging level in NVDA's general
settings, reproduce the problem, then attach the log.

**Do not attach crash dumps (`nvda_crash.dmp`) to a public issue.** They contain a
raw image of NVDA's memory, which can include the contents of documents you had
open. If a crash dump is needed, say so in the issue and it will be arranged
privately. Please also review any log before attaching it: logs record window
titles and spoken text.
