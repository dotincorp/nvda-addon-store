# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated

"""Position-independent IDispatch adapter for the system COM path.

Wraps an ``IDispatch`` pointer obtained from the system-registered
TactileDisplayAPI. Method calls are resolved by name via
``IDispatch.GetIDsOfNames`` (DISPID cached internally by
``comtypes.client.dynamic``) rather than by fixed vtable slot number.

This makes the system path resilient to future vendor library releases that
insert new methods anywhere in the interface: adding a method at slot N shifts
every subsequent vtable entry, but ``GetIDsOfNames`` always resolves to the
correct method regardless of position.

Contrast with the bundled path (``createTactileDisplayApi``), which uses the
hand-declared ``ITactileDisplayAPI._methods_`` vtable and is safe there
because the add-on controls the bundled DLL version.

``comtypes.client.dynamic.Dispatch`` selects the best available back-end:

* **``lazybind.Dispatch``** (type library available): Uses the registered TLB
  to resolve parameter types, including ``[out]`` parameters. System-installed
  COM objects almost always register a TLB, so this is the expected path.

* **``_Dispatch``** (no type library): Resolves methods by ``GetIDsOfNames``
  and calls ``IDispatch.Invoke`` with Python-typed in-parameters. Methods with
  only ``[in]`` parameters work correctly. ``GetDimensions`` (the sole ``[out]``
  parameter method) requires the TLB path; a ``COMError`` is raised if called
  without TLB, which is diagnosable from the NVDA log.

Threading: same contract as ``wrapper.py`` — all calls must occur on the
LibraryWorker STA thread that created the ``IDispatch`` pointer.
"""

from __future__ import annotations

from typing import Any


class DispatchProxy:
	"""Wraps an ``IDispatch`` pointer; dispatches by method name, not vtable slot.

	Constructed by ``TactileDisplayAPI._ensureInitialized`` on the system path.
	All COM method calls go through ``comtypes.client.dynamic``, which resolves
	each name to a DISPID via ``IDispatch.GetIDsOfNames`` and caches it.
	"""

	def __init__(self, idisp: Any) -> None:
		"""Wrap *idisp* (an ``IDispatch`` COM pointer) in a dynamic proxy.

		Args:
			idisp: A ``comtypes`` ``IDispatch`` pointer, as returned by
				``comtypes.CoCreateInstance(..., interface=IDispatch)``.
		"""
		from comtypes.client import dynamic as _dynamic

		# _dyn is either a lazybind.Dispatch (TLB-aware, handles [out] params)
		# or a _Dispatch (basic, in-params only).  Both resolve methods by name.
		self._dyn: Any = _dynamic.Dispatch(idisp)

	def __getattr__(self, name: str) -> Any:
		"""Delegate attribute access to the comtypes dynamic proxy."""
		dyn = self.__dict__.get("_dyn")
		if dyn is None:
			raise AttributeError(name)
		return getattr(dyn, name)

	def release(self) -> None:
		"""Drop the COM reference held by the dynamic proxy."""
		self._dyn = None  # type: ignore[assignment]
