---
description: Guide a full TactileDisplayAPI library update: vtable validation, comInterface.py scaffold, INI regeneration, tests, and hardware checklist.
---

# Updating the TactileDisplayAPI Library

**Announce at start:** "I'm using the update-tactiledisplayapi-library command to guide this update."

## Prerequisites

- 64-bit Python 3.13 with `comtypes` (vtable validation reads the DLL's typelib).
- An NVDA source clone at `../nvda/source`, or `$NVDA_REPO_DIR` / `--nvda-source`
  (INI regeneration reads `braille.py` and the `.po` catalogues; the compiled
  `.mo` files are not used).
- Working directory = repo root.

## Step 0: Obtain the installer files

The vendor ships releases as either a **ZIP archive** or a **Windows EXE installer (InnoSetup)**.

**ZIP**: Unzip the archive. Copy files from the extracted directory.

**EXE (InnoSetup)**: 7-Zip cannot open InnoSetup 6.x directly. Run the installer silently:

```powershell
Start-Process -FilePath ".\TactileDisplayAPI-Setup-x64.exe" `
    -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$(Resolve-Path .)\.scratch\install`"" `
    -Wait
```

This extracts to `.scratch/install/` (gitignored). Do **not** run the installer
normally on a working machine — it registers COM objects that can shadow the
repo's bundled DLL. Note the silent run registers too: its last step is
`regsvr32 /s .scratch\install\TactileDisplayAPI.dll`. Unregister afterwards with
`regsvr32 /u /s <path>` (elevated) unless a system-wide install is wanted.

**Copy to `addon/tactileDisplayAPI/`:**
- `TactileDisplayAPI.dll`, `DotPadSDK-<version>.dll` (the vendor bumps this filename — delete the old one), companion DLLs (Mecab, TTBEngine, libmathcat_c)
- `enu/TactileDisplayAPI.ini` (new vendor reference)
- `MathCATRules/` (replace entire directory)

**Never copy:** `liblouis.dll` and `tables/` (the addon uses NVDA's — see
`iniPatcher.py`), `FsHidBraille.jlb` and `JAWSIntegration/` (JAWS),
`TactileAccess.exe` (sighted viewer), `mecabrc` (points at an `ipadic`
directory the drop does not ship), `docs/`, `JPG/`, `ASCII Graphics/`,
`sample source/`, `unins000.*`.

After copying, keep `tests/test_bundle_completeness.py::_REQUIRED_DLLS` in step
with the drop — the vendor both bumps `DotPadSDK-<version>.dll`'s filename and
occasionally drops a companion DLL entirely.

## Step 1: Check vtable sync

```powershell
uv run python tools/validateComVtable.py --check
```

| Exit code | Meaning | Next step |
|-----------|---------|-----------|
| 0 | IN SYNC — vtable unchanged | Skip to Step 3 |
| 1 | DRIFT DETECTED | Continue to Step 2 |
| 2 | Environment error | Fix per error message, then retry |

Sample output when in sync:

```
TactileDisplayAPI.dll  version: v1.0.23
comInterface.py        version: v1.0.23  (from module docstring)

ITactileDisplayAPI      — 33 methods (slots 7-39) — IN SYNC
ITactileDisplayCallbacks — 3 methods (slots 7-9)  — IN SYNC

Advisory: 2 signature deviation(s) suppressed by known-deviation allowlist.
```

Reading a drift report:

| Report line | Meaning |
|-------------|---------|
| `new (appended)` | Typelib has a method `comInterface.py` lacks, at the end. Additive — existing slots still valid. |
| `new (mid-insert — downstream shifted)` | **Critical.** Every method after the insertion point is now calling the wrong vtable slot. Nothing downstream works until `comInterface.py` is renumbered. |
| `removed` | `comInterface.py` declares a method the typelib no longer has. |
| `declared in wrapper, absent from typelib` | Normal — the typelib under-reports callbacks (`GetTranslation` is absent from it entirely). Verify against the vendor IDL. |
| `Advisory: N suppressed` | Known hand-deviations; `--verbose` lists them, `KNOWN_DEVIATIONS` in the tool holds the rationale. |

Use `--dll path\to\TactileDisplayAPI.dll` to validate a candidate DLL before replacing the bundled one.

## Step 2: Scaffold and update comInterface.py (only if exit 1)

```powershell
uv run python tools/validateComVtable.py --scaffold
```

For each scaffolded method:
1. Paste the `COMMETHOD` block into `comInterface.py` at the indicated slot position.
2. Verify parameter types against vendor release notes or IDL — scaffold types are best-guess from the typelib.
3. Decide **stub vs. implement** (see precedents in `comInterface.py` docstring; `GetTranslation` AVed on `E_NOTIMPL`, `DisplayLiteraryBraille` was safely stub-able).
4. Add a `wrapper.py` facade if the addon needs to call the method.
5. Update the version string in the `comInterface.py` module docstring.

Re-validate to confirm sync:
```powershell
uv run python tools/validateComVtable.py --check
```
Expected: exit 0.

## Step 3: Regenerate per-locale INIs

```powershell
python tools/generateLibraryInis.py
python tools/generateLibraryInis.py --dry-run
```

`--dry-run` writes nothing and exits 0 if nothing would change (e.g. a
vtable-only update with no new control-type labels), 1 if stale.

The inis are UTF-16 LE + BOM, so `git diff` is unreadable — decode both sides
before reviewing:

```powershell
git show HEAD:addon/tactileDisplayAPI/enu/TactileDisplayAPI.ini > .scratch\old.ini
uv run python -c "import difflib; rd=lambda p:(lambda b: b.decode('utf-16' if b[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8-sig'))(open(p,'rb').read()).splitlines(); print('\n'.join(difflib.unified_diff(rd('.scratch/old.ini'), rd('addon/tactileDisplayAPI/enu/TactileDisplayAPI.ini'), lineterm='')))"
```

Expect changed values in `[ControlTypes]` and `[StateFlags]`, plus whatever the
new vendor reference itself changed in the passed-through sections (keymaps,
`[Liblouis]` defaults). On a **regeneration-only** run — no vendor drop — churn
outside `[ControlTypes]` / `[StateFlags]` means a parser bug; don't commit it.

Encoding is **not** taken from the vendor reference: `resolve_output_encoding`
derives it from `LIBRARY_SUPPORTS_UNICODE_BRAILLE_IN_INI`, so the per-locale
files stay UTF-16 LE + BOM regardless of how the vendor packaged their `enu`
copy (v1.0.34 shipped it as plain UTF-8; mirroring that would have truncated
every U+2800–U+28FF label). Spot-check anyway after a drop:

```powershell
uv run python -c "import glob; print([p for p in glob.glob('addon/tactileDisplayAPI/*/TactileDisplayAPI.ini') if open(p,'rb').read(2) != b'\xff\xfe'])"
```
Expected: `[]`.

See the `tools/generateLibraryInis.py` module docstring for adding a new
language and for the Unicode-braille gate.

## Step 4: Run tests

The suite imports NVDA modules, so it runs against the NVDA checkout's venv —
the addon's own `.venv` has a stubbed `appModuleHandler` that fails to import.
`scripts/runTests.ps1` wires that up, and is what CI runs:

```powershell
pwsh scripts/runTests.ps1                    # full suite
pwsh scripts/runTests.ps1 tests.test_foo     # one module
```

`tools/validateComVtable.py`'s own tests need no NVDA and run under `uv`:

```powershell
$env:PYTHONPATH = "."; uv run python tests/test_validateComVtable.py
```

All tests must pass before committing.

## Step 5: Report hardware verification checklist

After the automated steps complete, hand off to the maintainer:

> **Hardware verification required (cannot be automated):**
> - Connect the DotPad display; confirm `SimulateDisplay` connects without AV.
> - Verify `AddFocusedControl` / `RegisterEvents` work (sensitive to callback vtable alignment).
> - If any new stub was scaffolded: confirm no AV on the first call downstream of the new slot.
> - If `[StateFlags]` / `[ControlTypes]` changed, **or the ini bytes were rewritten at all**
>   (a vendor drop rewrites all 27): focus a pressed toggle (expect `⢎⣿⡱`), a checked
>   checkbox (`⣏⣿⣹`), and a menu separator (`⠤⠤⠤⠤⠤`) — these are the values a wrong
>   wire encoding silently truncates.
> - After a vendor drop, repeat one of those checks under a non-English NVDA UI language
>   whose abbreviations are themselves Unicode braille (Russian is the clearest case).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `NVDA source not found at ../nvda/source` | NVDA clone elsewhere | Set `--nvda-source` or `$NVDA_REPO_DIR`. |
| `braille.py missing 'roleLabels'` | NVDA refactored the source | Update the AST parser in `generateLibraryInis.py`. |
| `--dry-run` exits 1 but `git diff` is empty | Broken idempotency, or line-ending mismatch | Re-run with `--verbose` to see the flagged keys. |
| A new language's INI is mostly English | That locale's `.po` is largely untranslated | Expected — the generator falls back to English per missing string. |
| Wrong abbreviation on the display after regenerating | The library read a different locale directory | The library picks its directory from the **Windows** display language (not NVDA's UI language) and needs an exact Microsoft 3-letter LCID match. |
| Access violation on first library call after a DLL drop | Vtable drift not caught | Re-run `validateComVtable.py --check`; a mid-vtable insertion breaks every downstream slot. |
