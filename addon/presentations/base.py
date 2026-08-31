# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Base classes for DotPad tactile display presentations.

This module defines the core abstractions for presentations:
- Presentation: Abstract base class for rendering content to the display
- PresentationProvider: Abstract base class for detecting and creating presentations
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from baseObject import ScriptableObject

if TYPE_CHECKING:
	from NVDAObjects import NVDAObject

	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..extension_points.review_tracking import TriggerReason


class Presentation(ScriptableObject, ABC):
	"""Abstract base class for rendering content to the tactile display.

	A presentation encapsulates a specific way of rendering content,
	such as braille text, tables, charts, or screen captures.

	Inherits from ``ScriptableObject`` so concrete subclasses can declare
	``@script(gesture=...)`` handlers; the driver's overridden ``getScript``
	delegates to the active presentation first. The multiple inheritance
	``(ScriptableObject, ABC)`` resolves cleanly because
	``ScriptableObject``'s metaclass (``ScriptableType``) is a subclass of
	``ABCMeta`` — Python auto-picks the most-derived metaclass.

	Subclasses must implement:
	- name: str - unique identifier for this presentation type
	- render(display) - render current state to tactile buffer
	- scrollForward() - scroll the presentation forward
	- scrollBack() - scroll the presentation back

	Subclasses **MUST** call ``super().__init__()`` from their own
	``__init__`` (when defined) so ``ScriptableObject.__init__`` runs and
	populates ``self._gestureMap`` with class-decorated bindings. Without
	that call, ``@script`` handlers on the subclass are unreachable.

	Subclasses may optionally override:
	- handleCoreCycle() -> bool - process per-cycle updates, return True if render needed
	- isStillValid() - default returns True (follows navigation)
	- terminate() - clean up resources when presentation is no longer needed
	"""

	@property
	def provider(self) -> "PresentationProvider | None":
		"""The provider that created this presentation, if set."""
		return getattr(self, "_provider", None)

	@provider.setter
	def provider(self, value: "PresentationProvider | None") -> None:
		self._provider = value

	@property
	@abstractmethod
	def name(self) -> str:
		"""Unique identifier for this presentation type."""
		...

	@abstractmethod
	def render(self, display: Display) -> "DpTactileGraphicsBuffer | None":
		"""Render current state to tactile buffer.

		:param display: The display to render to.
		:returns: A tactile graphics buffer containing the rendered content,
			or ``None`` if the presentation manages the display directly
			(used by ``GraphicPresentation`` which writes the tactile area
			via TactileDisplayAPI's SimulateDisplay path; the renderer's
			``update()`` treats ``None`` as "skip this cycle's write").
		"""
		...

	@abstractmethod
	def scrollForward(self) -> bool:
		"""Scroll the presentation forward.

		:returns: True if scrolling occurred, False if at end.
		"""
		...

	@abstractmethod
	def scrollBack(self) -> bool:
		"""Scroll the presentation back.

		:returns: True if scrolling occurred, False if at beginning.
		"""
		...

	def isStillValid(self, triggerReason: TriggerReason | None = None) -> bool:
		"""Check if this presentation is still valid for current navigator position.

		This is used to determine if a forced presentation should remain active
		when navigation occurs.

		Default implementation returns True (presentation follows navigation).
		Override this for presentations that are tied to specific objects.

		:param triggerReason: The event that triggered the validity check (e.g.
			``TriggerReason.CARET_MOVE``), or ``None`` when no discrete navigation
			event applies (programmatic refresh, manual toggle, initial paint).
			Subclasses may use this to invalidate themselves on specific event types.
		:returns: True if the presentation is still valid, False otherwise.
		"""
		return True

	def terminate(self) -> None:
		"""Clean up resources held by this presentation.

		Called when the presentation is no longer needed, such as when the
		driver is being terminated. Implementations should release any
		references to NVDA objects, buffers, or other resources.

		Default implementation does nothing.
		"""
		pass

	def handleCoreCycle(self) -> bool:
		"""Handle core cycle event - process per-cycle updates.

		Called once per NVDA core cycle. Implementations can use this to
		detect changes and update internal state.

		Default implementation returns False (no render needed).

		:returns: True if presentation changed and needs re-rendering.
		"""
		return False


class PresentationProvider(ABC):
	"""Abstract base class for detecting and creating presentations.

	A provider is responsible for:
	1. Checking if it can provide a presentation for an object (canProvide)
	2. Creating presentation instances for matching objects (_doCreatePresentation)
	3. Optionally forcing a presentation (e.g., scanning parents for tables)

	Subclasses must implement:
	- name: str - unique identifier for this provider
	- canProvide(obj) - check if provider can handle the object (fast, no instantiation)
	- _doCreatePresentation(obj, display) - create the presentation

	Subclasses may optionally override:
	- forceForObject() - default returns None (forcing not supported)
	- terminate() - clean up resources when provider is no longer needed
	"""

	@property
	@abstractmethod
	def name(self) -> str:
		"""Unique identifier for this provider."""
		...

	@abstractmethod
	def canProvide(self, obj: NVDAObject) -> bool:
		"""Check if this provider can provide a presentation for the object.

		This method should be fast and avoid instantiating presentations.
		It is called during provider selection to find the best match.

		:param obj: The NVDA object to check.
		:returns: True if this provider can provide a presentation.
		"""
		...

	def createPresentation(self, obj: NVDAObject, display: Display) -> Presentation:
		"""Create a presentation for the object.

		This method includes a guard that checks canProvide() first.
		If canProvide() returns False, raises RuntimeError.

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: A Presentation instance.
		:raises RuntimeError: If canProvide() returns False.
		"""
		if not self.canProvide(obj):
			raise RuntimeError(f"{self.name} provider cannot provide for this object")
		return self._doCreatePresentation(obj, display)

	@abstractmethod
	def _doCreatePresentation(self, obj: NVDAObject, display: Display) -> Presentation:
		"""Implementation of presentation creation.

		This method is called by createPresentation() after canProvide() check passes.
		Subclasses should implement the actual presentation instantiation here.

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: A Presentation instance.
		"""
		...

	def forceForObject(
		self,
		obj: NVDAObject,
		display: Display,
	) -> Presentation | None:
		"""Try to force a presentation for the given object.

		This method is called when manually activating a presentation type.
		Providers may implement additional logic here, such as scanning
		parent objects to find applicable content.

		Default implementation returns None (forcing not supported).

		:param obj: The NVDA object to create a presentation for.
		:param display: The display to render to.
		:returns: A presentation instance, or None if not possible.
		"""
		return None

	def terminate(self) -> None:
		"""Clean up resources held by this provider.

		Called when the provider is no longer needed, such as when the
		driver is being terminated. Implementations should release any
		cached presentations or other resources.

		Default implementation does nothing.
		"""
		pass
