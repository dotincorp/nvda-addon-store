"""Session-scoped deduplication for warnings on repeating code paths.

Some failures are worth WARNING -- the user perceives the degraded behaviour --
but sit on a path that repeats: a library callback, a per-region draw, a render
that runs on every update. Logging each occurrence buries the rest of the log
without telling anyone anything the first line did not.

These helpers log the first occurrence of each ``(site, exception type)`` pair
and say in the message that the rest are suppressed, so a reader knows the log
is deduplicated rather than the failure transient.
"""

from logHandler import log

_loggedFailures: set[tuple[str, type[BaseException]]] = set()
"""``(site, exception type)`` pairs already reported in this NVDA session."""


def warnFailureOnce(site: str, exc: BaseException, consequence: str = "") -> None:
	"""Log ``exc`` at WARNING the first time this ``site`` sees its type.

	:param site: Identifies the call that failed; also scopes the dedup, so two
		sites failing the same way are both reported.
	:param consequence: Optional note on what the caller does instead, e.g.
		``"returning empty output"``.
	"""
	excType = type(exc)
	key = (site, excType)
	if key in _loggedFailures:
		return
	_loggedFailures.add(key)
	suffix = f"{consequence}; " if consequence else ""
	log.warning(
		"%s raised %s: %s (%sfurther %s failures here are suppressed for this session)",
		site,
		excType.__name__,
		exc,
		suffix,
		excType.__name__,
	)


def resetForTesting() -> None:
	"""Forget every reported failure. For tests that exercise a failing path twice."""
	_loggedFailures.clear()
