# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""Serialise every liblouis translation in the NVDA process.

liblouis keeps its translation buffers in process-wide statics and frees and
re-allocates some of them on every call, so two concurrent translations corrupt
the heap even when the tables are already loaded. NVDA core only ever translates
on its main thread and takes no lock; the library's ``GetTranslation`` callback
translates on the library worker thread. Patching the ``louis`` module functions
makes core's calls (``louisHelper`` looks them up at call time) and ours share
one lock.
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable

import louis

# Reentrant because liblouis calls NVDA's log callback mid-translation, and a
# handler that translates again must not deadlock on itself.
_lock = threading.RLock()

_SERIALIZED_MARKER = "_dotPadSerialized"
_PATCHED_FUNCTIONS = ("translate", "backTranslate")


def _serialized(fn: Callable[..., Any]) -> Callable[..., Any]:
	@functools.wraps(fn)
	def wrapper(*args: Any, **kwargs: Any) -> Any:
		with _lock:
			return fn(*args, **kwargs)

	setattr(wrapper, _SERIALIZED_MARKER, True)
	return wrapper


def install() -> None:
	"""Wrap ``louis.translate`` and ``louis.backTranslate`` in the shared lock.

	Idempotent, and stays in place for the life of the process: the marker lives on
	the patched function, so a reloaded copy of this module does not wrap twice.
	"""
	for name in _PATCHED_FUNCTIONS:
		fn = getattr(louis, name)
		if not getattr(fn, _SERIALIZED_MARKER, False):
			setattr(louis, name, _serialized(fn))
