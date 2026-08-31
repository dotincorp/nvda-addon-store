# Fixtures for `test_generateLibraryInis.py`

Trimmed copies of real NVDA / vendor data, hand-curated to exercise specific
parser and generator behaviours. Refresh manually if the shape of the upstream
data drifts.

- `vendor_reference.ini` — small vendor-style ini covering `[ControlTypes]`,
  `[StateFlags]`, `[Liblouis]`, `[BrailleMarking]`, a per-display keymap, a
  comment, a blank line, and a CRLF line-ending convention. Round-trip tested.
- `braille_excerpt.py` — minimal Python file shaped like NVDA's `braille.py`,
  exposing `roleLabels`, `positiveStateLabels`, `negativeStateLabels` with a
  mix of translatable and non-translatable (Unicode braille) entries.
- `locale_excerpts/nl.po` — Dutch `.po` with realistic msgstrs plus one
  untranslated and one fuzzy entry.
- `locale_excerpts/de.po` — German equivalent.
