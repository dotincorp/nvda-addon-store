# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Presentation Manager for DotPad tactile display.

This module provides the PresentationManager class that orchestrates
presentation selection and lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from logHandler import log

from .base import Presentation, PresentationProvider

if TYPE_CHECKING:
	from NVDAObjects import NVDAObject

	from ..brailleDisplayDrivers.dotPad.driver import Display
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from ..extension_points.review_tracking import TriggerReason


class PresentationManager:
	"""Manages presentation selection and lifecycle.

	The PresentationManager orchestrates how content is rendered on the
	tactile display. It:
	- Maintains a chain of presentation providers
	- Selects the appropriate presentation on navigation
	- Supports forcing a specific presentation type
	- Handles presentation scrolling
	"""

	def __init__(self, display: Display):
		"""Initialize the presentation manager.

		:param display: The display to render presentations to.
		"""
		self.display = display
		self._activePresentation: Presentation | None = None
		self._forcedPresentation: Presentation | None = None

		# Ordered list of providers (first = highest priority)
		self._providers: list[PresentationProvider] = []

	def registerProvider(
		self,
		provider: PresentationProvider,
		moveToStart: bool = False,
	) -> None:
		"""Register a presentation provider.

		:param provider: The provider to register.
		:param moveToStart: If True, provider gets highest priority (checked first).
		:raises ValueError: If a provider with the same name is already registered.
		"""
		if self.getProviderByName(provider.name) is not None:
			raise ValueError(f"Provider with name '{provider.name}' already registered")

		if moveToStart:
			self._providers.insert(0, provider)
		else:
			self._providers.append(provider)

	def getProviderByName(self, name: str) -> PresentationProvider | None:
		"""Get a provider by name.

		:param name: The provider name to look up.
		:returns: The provider, or None if not found.
		"""
		return next((p for p in self._providers if p.name == name), None)

	def update(self, obj: NVDAObject, triggerReason: TriggerReason | None = None) -> None:
		"""Called on navigation. Selects appropriate presentation.

		This method should be called whenever the navigator object changes.
		It will select the most appropriate presentation based on:
		1. Any forced presentation (if still valid)
		2. The first provider that can provide, reusing active if same provider and valid
		3. A new presentation from the matching provider

		:param obj: The current navigator object.
		:param triggerReason: The triggering event (e.g. ``TriggerReason.CARET_MOVE``),
			or ``None`` when no discrete navigation event applies. Forwarded to
			``isStillValid`` so presentations can react to specific event types.
		"""
		# 1. Check forced presentation
		if self._forcedPresentation:
			if self._forcedPresentation.isStillValid(triggerReason):
				self._activePresentation = self._forcedPresentation
				return
			else:
				log.debug(f"Forced presentation {self._forcedPresentation.name} no longer valid")
				self._forcedPresentation = None

		# 2. Find first provider that can provide
		matchingProvider: PresentationProvider | None = None
		for provider in self._providers:
			if provider.canProvide(obj):
				matchingProvider = provider
				break

		if matchingProvider is None:
			if self._activePresentation is not None:
				log.debug(f"No provider matched (was: {self._activePresentation.name})")
			self._activePresentation = None
			return

		# 3. If same provider and still valid, reuse existing presentation
		if (
			self._activePresentation
			and self._activePresentation.provider is matchingProvider
			and self._activePresentation.isStillValid(triggerReason)
		):
			return

		# 4. Create new presentation from matching provider
		previousName = self._activePresentation.name if self._activePresentation else None
		presentation = matchingProvider.createPresentation(obj, self.display)
		presentation.provider = matchingProvider
		self._activePresentation = presentation
		log.debug(f"Created new presentation: {presentation.name} (was: {previousName})")

	def forcePresentation(self, providerName: str, obj: NVDAObject) -> bool:
		"""Force a presentation type.

		This method activates a specific presentation type, bypassing
		auto-detection. The forced presentation remains active until:
		- It becomes invalid (isStillValid returns False)
		- Another presentation is forced
		- clearForced is called

		:param providerName: The name of the provider to force.
		:param obj: The current navigator object.
		:returns: True if the presentation was successfully forced.
		"""
		provider = self.getProviderByName(providerName)
		if not provider:
			return False

		presentation = provider.forceForObject(obj, self.display)
		if presentation:
			presentation.provider = provider
			self._forcedPresentation = presentation
			self._activePresentation = presentation
			return True
		return False

	def clearForced(self) -> None:
		"""Clear forced presentation, return to auto-detect."""
		self._forcedPresentation = None

	def render(self) -> DpTactileGraphicsBuffer | None:
		"""Render the active presentation.

		:returns: A tactile graphics buffer, or None if no active presentation.
		"""
		if self._activePresentation:
			return self._activePresentation.render(self.display)
		return None

	def scrollForward(self) -> bool:
		"""Scroll the active presentation forward.

		:returns: True if scrolling occurred, False otherwise.
		"""
		if self._activePresentation:
			return self._activePresentation.scrollForward()
		return False

	def scrollBack(self) -> bool:
		"""Scroll the active presentation back.

		:returns: True if scrolling occurred, False otherwise.
		"""
		if self._activePresentation:
			return self._activePresentation.scrollBack()
		return False

	@property
	def activePresentation(self) -> Presentation | None:
		"""The currently active presentation."""
		return self._activePresentation

	@property
	def forcedPresentation(self) -> Presentation | None:
		"""The currently forced presentation, if any."""
		return self._forcedPresentation

	@property
	def hasActivePresentation(self) -> bool:
		"""Whether there is an active presentation."""
		return self._activePresentation is not None

	@property
	def isForcedMode(self) -> bool:
		"""Whether a presentation is currently forced."""
		return self._forcedPresentation is not None

	def terminate(self) -> None:
		"""Clean up resources held by the presentation manager.

		Terminates the active presentation and all registered providers,
		then clears all references.
		"""
		# Terminate active presentation
		if self._activePresentation is not None:
			self._activePresentation.terminate()
			self._activePresentation = None

		# Clear forced presentation
		if self._forcedPresentation is not None:
			# Don't terminate - it's the same object as _activePresentation
			self._forcedPresentation = None

		# Terminate all providers
		for provider in self._providers:
			provider.terminate()

		# Clear provider list
		self._providers.clear()
