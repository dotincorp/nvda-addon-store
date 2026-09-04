# Logging

## Who reads what

NVDA's log levels are not ordered the way stdlib intuition suggests
(`source/logHandler.py`):

```
DEBUG_UNREDACTED 5 < DEBUG 10 < IO 12 < DEBUGWARNING 15 < INFO 20 < WARNING 30 < ERROR 40 < OFF 100
```

Two consequences drive everything below.

**INFO is NVDA's default level.** Anything logged at INFO or above lands in the
log of every user who ever installs the add-on. Our global plugin loads whether
or not a Dot Pad is attached, so "every user" includes people who own no Dot Pad
and never will.

**The levels are not nested as you would guess.** A user on the IO level sees IO,
DEBUGWARNING and INFO but *not* DEBUG. DEBUG is the firehose, and `io` is *more*
visible than `debug`, not less.

NVDA documents no policy on which level to use — there is nothing in the coding
standards, the contributing guide, the add-on guide or the developer guide.
Level choice in NVDA core is convention-by-example. This file is ours.

## Ask "delete?" before asking "which level?"

A log call is a permanent cost: context for whoever reads the code, noise in
review, and one more line that drifts out of date as the code around it changes.
Before adding one, or when you find one:

1. **Does this message still need to exist?** Tracing that proved a code path
   worked while you were writing it is not diagnostics. Once the path is known
   good, the message is scaffolding. "Menu item clicked", "call submitted",
   "returned successfully" — delete them, at *any* level, debug included. Debug
   is not free: it is the level a user turns on when something is wrong, so
   every non-event dilutes what they came to find.

   Where a call has a paired warning on failure, silence already means success.

2. **Would it tell us something we cannot get more easily another way?** Logging
   configuration values is not actionable — anyone debugging can inspect
   `config.conf` in the NVDA Python console and see the live truth instead of
   trusting a stale line in a log.

3. **Only then, choose a level.**

What is worth keeping is what varies between machines and cannot be
reconstructed afterwards: which backend or DLL was selected, firmware and device
identity, display geometry, and failures.

## The levels

- **`log.info`** — rare, user-meaningful, actionable facts worth having in a log
  a user sends us: the display we connected to, the library version that
  answered, a fallback that changes what they perceive. A handful of lines per
  session at most. If it can fire repeatedly during ordinary use, it is not
  INFO.
- **`log.debug`** — diagnostics that survived question 1. Gate high-volume
  hardware traffic (see below).
- **`log.debugWarning`** — unexpected, but recovered, and not something the user
  can act on. NVDA itself uses this to downgrade expected exceptions. Retries,
  protocol packets we do not implement, payloads we clamp to fit.
- **`log.warning`** — degraded behaviour the user may actually perceive: output
  genuinely lost, a device-reported error, a wedged worker.
- **`log.error` / `log.exception`** — a failure that broke something. Use
  `exception` whenever you are inside an `except` block (never
  `error(..., exc_info=True)`; ruff's G201 catches that),
  and always give the message real content — a bare traceback with an empty
  message tells the reader nothing about which of several attempts failed.

### `log.exception` cannot take lazy arguments

NVDA's `Logger.exception` is `exception(msg, exc_info=True, **kwargs)` and calls
`self._log(level, msg, (), ...)` with an empty args tuple. Its second positional
parameter is `exc_info`, not a format argument, and any `%s` left in the message
renders literally. So `log.exception` keeps its f-string, with a `# noqa: G004`
and a comment saying why.

Every other level takes `%`-args normally.

### Repeating warnings

A failure can deserve WARNING and still sit on a path that repeats — a library
callback, a per-region draw, something that runs on every update. Use
`utils.logOnce.warnFailureOnce`, which logs the first occurrence per
`(site, exception type)` and says in the message that the rest are suppressed,
so a reader knows the log is deduplicated rather than the failure transient.

### Don't use `log.io`

NVDA core uses `log.io` for real **speech and braille output** — the content
being spoken or brailled — not for raw wire data. Raw data belongs at `debug`,
gated behind the hardware I/O debug category the user enables in Advanced
settings. `hwIo.base._isDebug()` is exactly `config.conf["debugLog"]["hwIo"]`:

```python
if _isDebug():
    log.debug(f"Write: {data!r}")
```

`addon/ble/hwIo.py` already does this, mirroring NVDA's own `hwIo.base`. Serial
transport comes from NVDA core and carries its own logging, so the BLE stack is
the only place we own this. Since IO (12) sits *above* DEBUG (10), moving packet
dumps to `io` would make them more visible, not less.

## Don't assert on log output in tests

Logging is NVDA's infrastructure, not our behaviour. A test that asserts a log
call happened, at a level, with certain text is testing Python's `logging` module
and NVDA's `Logger` — and it pins every message as a public contract, so tidying
one log line turns into a test change.

Assert the return value, the resulting state, or that the call did not raise.
Every log assertion this project used to have sat beside a behavioural assertion
that covered the same case better.

`tests/__init__.py` sets the NVDA logger to `OFF`, so log output is invisible to
tests by default. That is deliberate. If reaching for `assertLogs` or patching
`log` feels necessary, the thing worth asserting is probably somewhere else.
