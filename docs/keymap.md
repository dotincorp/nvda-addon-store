# Dot Pad addon — gesture reference

This document lists every gesture the Dot Pad addon binds by default,
organised by category. The keymap was unified in feature 020 with the
goal of hardware-layout-aware single-key viewport navigation, symmetric
mode toggles, and consistent short / long-press conventions.

## At a glance

The Dot Pad device exposes four function keys (`f1`/`f2`/`f3`/`f4`) plus
two pan keys (`panLeft`/`panRight`). Gestures fall into four tiers:

- **Tier 0** — NVDA's standard text-scroll on `panLeft` / `panRight`. Active
  in every mode. Fixed by NVDA's braille framework.
- **Tier 1** — driver-level: multi-line scroll, navigator activation, mode
  switches. Active in every mode (some keys can be overridden by the
  active presentation).
- **Tier 2** — `GraphicPresentation`-only: viewport pan, edge jumps, zoom.
  Active only while a tactile graphic is being rendered.
- **Firmware-reserved** — handled by device firmware before NVDA sees the
  keys.

Conventions:

- **Short-press** (under 1.5s) = primary action.
- **Long-press** (1.5s or longer) = secondary / edge-jump action.
- Mode-switch chords stay reachable from any presentation because the
  active presentation doesn't bind the long-press variants.

## Tier 0 — Universal text scroll

| Gesture | Action |
|---|---|
| `panLeft` | Scroll the 20-cell text braille display back |
| `panRight` | Scroll the 20-cell text braille display forward |

## Tier 1 — Multi-line scroll and mode switches (every mode)

| Gesture | Action |
|---|---|
| `f1` | Scroll the multi-line display back (delegates to active presentation) |
| `f4` | Scroll the multi-line display forward |
| `f3` | Activate the current navigator object (NVDA's `review_activate`) |
| `f2+f4` | Force-render the navigator object as a **tactile graphic** (show as graphic) |
| `f1+f3` | Force-render the navigator object as **braille** (show as braille) |
| `longPress(f1+f3)` | Toggle screen capture mode |
| `longPress(f2+f3)` | Force table mode (scan parent objects for a table) |

The `f1+f3` / `f2+f4` chords form a symmetric pair: one returns to braille,
the other forces graphic. Both are reachable from any presentation as
explicit escape hatches.

## Tier 2 — Graphic mode viewport pan (single keys)

These bindings apply ONLY while `GraphicPresentation` is the active
presentation (typically when focus is on a `Role.GRAPHIC` object or after
pressing `f2+f4`). Short-press = page-step in the named direction.

| Gesture | Action |
|---|---|
| `f1` | Pan viewport LEFT by one page-step |
| `f2` | Pan viewport UP by one page-step |
| `f3` | Pan viewport DOWN by one page-step |
| `f4` | Pan viewport RIGHT by one page-step |

The single-key direction mapping mirrors the hardware button layout.

## Tier 2 — Graphic mode edge jumps (long-press)

Hold the same single key for ≥1.5s to jump to the edge in the same
direction.

| Gesture | Action |
|---|---|
| `longPress(f1)` | Jump viewport to the LEFT edge (HOME) |
| `longPress(f2)` | Jump viewport to the TOP edge |
| `longPress(f3)` | Jump viewport to the BOTTOM edge |
| `longPress(f4)` | Jump viewport to the RIGHT edge (END) |

## Tier 2 — Graphic mode zoom + recenter

| Gesture | Action |
|---|---|
| `f2+f3` | Zoom IN |
| `f1+f4` | Zoom OUT |
| `panLeft+panRight` | Recenter viewport |

## Firmware-reserved

| Gesture | Reason |
|---|---|
| `longPress(panLeft+panRight)` | Device firmware announces battery status. The addon cannot bind anything to this gesture — the firmware intercepts the keys before NVDA sees them. |

You CAN assign a script to this gesture via NVDA's Input Gestures dialog
(NVDA doesn't know it's firmware-reserved), but the assigned script will
never fire because the firmware eats the keypress.

## Scripts without a default binding (user-assignable)

The following scripts are registered with NVDA but have no default
gesture. Open NVDA's Input Gestures dialog (NVDA+N → Preferences → Input
gestures) → Dot Pad category and assign any gesture you prefer.

| Script | Description |
|---|---|
| `script_refresh` | Refreshes the Dot Pad display |

Auto-refresh handles the common refresh case on both D3 hardware-based
displays and the 320A's software-based path; manual refresh is needed
rarely.

## Removed gestures (rebinding via NVDA's Input Gestures dialog)

Feature 020 dropped seven `kb:` keyboard-emulation gestures from the
default keymap to free chord space for the viewport-pan additions.

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
  scripts** (the Tier 2 viewport / zoom handlers in this document). It
  shows only Tier 0 and Tier 1 entries. To rebind a presentation-level
  gesture, edit `%APPDATA%\nvda\gestures.ini` directly. This is an upstream
  NVDA limitation that requires an NVDA-side change to fix.
- **Firmware-reserved `longPress(panLeft+panRight)`** can't be repurposed.
