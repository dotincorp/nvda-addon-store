# Dot Pad addon — gesture reference

This document lists every gesture the Dot Pad addon binds by default,
organised by category. The keymap was unified in feature 020 with the
goal of hardware-layout-aware single-key viewport navigation, symmetric
mode toggles, and consistent short / long-press conventions.

<!--
MAINTAINERS: the tables between the BEGIN/END GENERATED markers below are
produced by `python tools/generateKeymap.py` from the `@script` bindings in
the source. Run it after adding, removing or retargeting any binding. The
`keymap-docs` prek hook and CI run it with `--dry-run` and fail on drift.

Everything outside the markers is hand-written prose — edit it freely, but
leave the markers in place. See the script's module docstring for how tiers
are derived and what it cannot see.
-->


## At a glance

The Dot Pad device exposes four function keys (`f1`/`f2`/`f3`/`f4`) plus
two pan keys (`panLeft`/`panRight`). Gestures fall into four tiers:

- **Tier 0** — NVDA's own global scripts, mapped by the driver's
  `gestureMap`. These resolve last, so any tier above can override them.
- **Tier 1** — driver-level: multi-line scroll, mode switches. Active in
  every mode (some keys can be overridden by the active presentation).
- **Tier 2** — presentation-level. Active only while that presentation is
  rendering, and they win over tiers 0 and 1.
- **Firmware-reserved** — handled by device firmware before NVDA sees the
  keys.

Conventions:

- **Short-press** (under 1.5s) = primary action.
- **Long-press** (1.5s or longer) = secondary / edge-jump action.
- Mode-switch chords stay reachable from any presentation because the
  active presentation doesn't bind the long-press variants.

## Tier 0 — NVDA global scripts (driver `gestureMap`)

<!-- BEGIN GENERATED: tier0 -->

| Gesture | Action |
|---|---|
| `f3` | Activate the current navigator object |
| `panLeft` | Scroll the 20-cell text braille display back |
| `panRight` | Scroll the 20-cell text braille display forward |

<!-- END GENERATED: tier0 -->

## Tier 1 — Driver scripts (every mode)

<!-- BEGIN GENERATED: tier1 -->

| Gesture | Action |
|---|---|
| `f1` | Scrolls the multiline display backwards |
| `f4` | Scrolls the multiline display forward |
| `f1+f3` | Displays the review object as braille via the active braille presentation |
| `f2+f4` | Displays the review object as tactile graphics via TactileDisplayAPI |
| `longPress(f1+f3)` | Toggles between normal braille output and screen capture mode |
| `longPress(f2+f3)` | Forces table mode by scanning parent objects for a table |

<!-- END GENERATED: tier1 -->

The `f1+f3` / `f2+f4` chords form a symmetric pair: one returns to braille,
the other forces graphic. Both are reachable from any presentation as
explicit escape hatches.

## Tier 2 — Presentation scripts

These bindings apply ONLY while the named presentation is the active one.
For `GraphicPresentation` that is typically when focus is on a
`Role.GRAPHIC` object, or after pressing `f2+f4`. The single-key direction
mapping mirrors the hardware button layout; holding the same key for
≥1.5s jumps to the edge in that direction.

<!-- BEGIN GENERATED: tier2 -->

### `GraphicPresentation`

Defined in `addon/presentations/graphic.py`. Active only while this presentation is rendering.

| Gesture | Action |
|---|---|
| `f1` | Pan the tactile graphic viewport left by one page-step |
| `f2` | Pan the tactile graphic viewport up by one page-step |
| `f3` | Pan the tactile graphic viewport down by one page-step |
| `f4` | Pan the tactile graphic viewport right by one page-step |
| `f1+f4` | Zoom the tactile graphic out |
| `f2+f3` | Zoom the tactile graphic in |
| `panLeft+panRight` | Recenter the tactile graphic viewport |
| `f1+f2+f3+f4` | Invert the tactile graphic image (swap raised and blank dots) |
| `longPress(f1)` | Jump the tactile graphic viewport to the left edge |
| `longPress(f2)` | Jump the tactile graphic viewport to the top edge |
| `longPress(f3)` | Jump the tactile graphic viewport to the bottom edge |
| `longPress(f4)` | Jump the tactile graphic viewport to the right edge |

<!-- END GENERATED: tier2 -->

## Firmware-reserved

| Gesture | Reason |
|---|---|
| `longPress(panLeft+panRight)` | Device firmware announces battery status. If a function is mapped to this gesture, it will be executed but the firmware will keep reporting battery level as well. |


## Scripts without a default binding (user-assignable)

The following scripts are registered with NVDA but have no default
gesture. Open NVDA's Input Gestures dialog (NVDA+N → Preferences → Input
gestures) → Dot Pad category and assign any gesture you prefer.

<!-- BEGIN GENERATED: unbound -->

| Script | Description |
|---|---|
| `script_refresh` | Refreshes the Dot Pad display |

<!-- END GENERATED: unbound -->

Auto-refresh handles the common refresh case on both D3 hardware-based
displays and the 320A's software-based path; manual refresh is needed
rarely.

## Removed gestures (rebinding via NVDA's Input Gestures dialog)

Earlier versions of this add-on had seven `kb:` keyboard-emulation gestures in the
default keymap. Those have been removed to free chord space for the viewport-pan additions.

| Old gesture | Old action | Rebinding path in NVDA's Input Gestures dialog |
|---|---|---|
| `f2` | backspace key | System → keyboard → backspace |
| `f1+f2` | control+home | System → keyboard → control+home |
| `f3+f4` | control+end | System → keyboard → control+end |
| `f1+panLeft` | up arrow | System → keyboard → upArrow |
| `f4+panRight` | down arrow | System → keyboard → downArrow |
| `f2+panLeft` | alt+leftArrow (prev word) | System → keyboard → alt+leftArrow |
| `f2+panRight` | alt+rightArrow (next word) | System → keyboard → alt+rightArrow |

NVDA's per-script gesture customization persists across addon updates, so
once you've rebound them they stay rebound.

A gesture listed here can still be in use by a single presentation —
`f2` was dropped as a driver-level backspace and is now
`GraphicPresentation`'s pan-up. What it no longer does is work in every
mode.

<!--
MAINTAINERS: `tools/generateKeymap.py` fails if a gesture in this table is
bound again at Tier 0 or Tier 1, so restoring one means moving its row out
of here. The check is deliberately scoped to those two tiers — a
presentation reusing the identifier (as GraphicPresentation does with `f2`)
is the reuse per-presentation resolution exists to allow, not a conflict.
-->


## Resolution order (technical)

When the device fires a gesture, NVDA resolves it in this order:

1. **Active presentation's `getScript`** — if `GraphicPresentation` (or any
   future presentation that defines `@script` handlers) returns a non-None
   handler for the gesture, that handler runs.
2. **Driver's `@script` handlers** — if the presentation didn't claim the
   gesture, the driver's own scripts handle it.
3. **Driver's `gestureMap`** — if neither step returned a handler, NVDA's
   own scripts mapped via `gestureMap` run (e.g., `braille_scrollBack` for
   `panLeft`).

Short and long-press are distinct gesture IDs: `f1` and `longPress(f1)`
resolve independently in steps 1–3.

## Known limitations

- **NVDA's Input Gestures dialog doesn't enumerate presentation-level
  scripts** (the Tier 2 handlers in this document). It shows only Tier 0
  and Tier 1 entries. To rebind a presentation-level gesture, edit
  `%APPDATA%\nvda\gestures.ini` directly. This is an upstream NVDA
  limitation that requires an NVDA-side change to fix. The tables above
  list what is *bound*, not what is *reachable through the dialog*.
- **Firmware-reserved `longPress(panLeft+panRight)`** can't be repurposed.
