# NVDA Add-on for DotPad

Support for [Dot Pad](https://dotincorp.com/) tactile graphics displays in the
[NVDA screen reader](https://www.nvaccess.org/). The add-on drives the Dot Pad
over both Bluetooth Low Energy and USB. Without it, NVDA cannot take advantage
of the Dot Pad's multi-line and tactile graphics capabilities.

A traditional braille display shows a single line of text, and panning simply
moves a window over that line. A multi-line display needs more: the screen
reader must retrieve as many paragraphs as will fit, and move the cursor while
panning so that reading stays continuous, like reading a book — in either
computer braille or contracted braille, where a braille line almost never
corresponds to a print line on screen. The add-on handles that text retrieval,
formatting, translation and panning.

It also renders letters, emoji and graphics as tactile images, which can be
enlarged, reduced and inverted. Math equations in Microsoft Word and charts in
Excel are converted to tactile images automatically, with axes, tick marks and
labels generated, translated and formatted as needed.

For learning braille, the number of multi-line braille lines is configurable
from double-spaced (5 lines) through 8 lines of 8-dot braille to 10 lines of
6-dot braille, and a hybrid mode shows a word in braille alongside tactile print
letters. An on-screen braille visualizer lets teachers and trainers see what is
being sent to the Dot Pad.

## Documentation

The [user guide](docs/userGuide.md) covers everything about using the add-on:
connecting over Bluetooth and USB, the navigation buttons and their key
combinations, the NVDA braille settings that matter for a multi-line display,
tactile graphics mode, Excel and Word integration, and the Dot Pad Display
Viewer. It is shipped with the add-on and is what the add-on store's Help button
opens.

The remainder of this file covers installing and building the add-on.

## Licence

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
Dot Pad. The question is only asked once. See the
[user guide](docs/userGuide.md) for connecting the display afterwards.

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
