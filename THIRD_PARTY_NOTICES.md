# Third-party notices

The DotPad NVDA add-on is licensed under the GNU General Public License version 2
(see [`COPYING.txt`](COPYING.txt)). It ships several components it did not author. This file
records what they are and under what terms they are redistributed.

## Vendored Python packages — `addon/_vendor/`

These are ordinary PyPI wheels, unpacked into a per-platform directory so the add-on
runs without installing anything into NVDA's own environment. Their licence texts are
kept in `addon/_vendor/<platform>/_licenses/<package>-<version>/` and are preserved
automatically by `build_vendor.py` when the tree is rebuilt. The vendored versions are
recorded in `uv.lock`; they are deliberately not repeated here, where they would go stale.

| Component | Licence |
|---|---|
| [bleak](https://github.com/hbldh/bleak) | MIT |
| [typing_extensions](https://github.com/python/typing_extensions) | PSF-2.0 |
| [PyWinRT](https://github.com/pywinrt/pywinrt) (`winrt-runtime` and the `winrt-windows-*` projection packages) | MIT — see note below |

`bleak` pulls the PyWinRT packages in as its Windows backend: `winrt-runtime` plus the
`windows-devices-bluetooth`, `windows-devices-bluetooth-advertisement`,
`windows-devices-bluetooth-genericattributeprofile`, `windows-devices-enumeration`,
`windows-devices-radios`, `windows-foundation`, `windows-foundation-collections` and
`windows-storage-streams` projections.

**PyWinRT note.** Every PyWinRT wheel declares `License: MIT` in its metadata, but the
published wheels do not include a `LICENSE` file, so there is no text to vendor. The
canonical MIT text is in the upstream repository linked above. `winrt/msvcp140.dll` is
the Microsoft Visual C++ runtime, redistributed inside the `winrt-runtime` wheel by its
publisher under Microsoft's redistributable terms.

## TactileDisplayAPI — `addon/tactileDisplayAPI/`

`TactileDisplayAPI.dll` is a **closed-source COM library, copyright Dot Incorporated /
Joseph Stephen**. It is redistributed here with Dot's permission. No public licence terms
exist for it beyond that permission, and none should be inferred.

It is bundled rather than relying on a system-wide install because the add-on has to
work for users without administrator rights.

The remaining binaries in this directory are **dependencies of TactileDisplayAPI**, not
independent choices of this add-on. They arrive as part of Dot's library drop:

| Component | Upstream | Licence |
|---|---|---|
| `TactileDisplayAPI.dll` | Dot Incorporated / Joseph Stephen | Proprietary — redistributed with permission |
| `DotPadSDK-*.dll` | Dot Incorporated / Joseph Stephen | Proprietary — redistributed with permission |
| `TTBEngine.dll` | Dot Incorporated / Joseph Stephen | Proprietary — redistributed with permission |
| `libmathcat_c.dll`, `MathCATRules/` | [MathCAT](https://github.com/NSoiffer/MathCAT) — maths-to-braille translation | MIT, per upstream |
| `Mecab.dll` | [MeCab](https://taku910.github.io/mecab/) — Japanese morphological analyser | BSD 3-clause, per upstream |
| `<locale>/TactileDisplayAPI.ini` (27 locales) | Dot Incorporated / Joseph Stephen | Proprietary — redistributed with permission |

**liblouis is not bundled.** TactileDisplayAPI expects a liblouis alongside it, but
`iniPatcher.py` rewrites the per-locale INI files at runtime to point at the copy NVDA
already ships, so no liblouis binary or table is redistributed by this add-on.

## Why a GPL add-on may ship a proprietary driver library

Two independent reasons:

- NVDA's own licence carries an exception permitting binary blobs that act as drivers
  for hardware, which is exactly what `TactileDisplayAPI.dll` is.
- The add-on reaches the library through **COM**, instantiating it as an out-of-process
  object rather than linking against it, so the two are not combined into a single work
  in the sense the GPL is concerned with.

Dot Incorporated has confirmed that the SDK and DLLs above may be shipped in this
repository.

## Upstream project history

Parts of this repository's history and its build scaffolding derive from
[nvaccess/AddonTemplate](https://github.com/nvaccess/AddonTemplate), which is likewise
GPL-2.0, and carry the original contributors' commits and authorship.
