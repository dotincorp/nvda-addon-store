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


MAX_UNANSWERABLE_VALIDITY_CHECKS = 3
"""How long a dismissal holds while its presentation cannot say whether it is valid.

Long enough to ride out an application refusing COM calls for a moment, short
enough that an object which is really gone gives the display back within a few
navigation events rather than for the session.
"""


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
		self._dismissedObject: NVDAObject | None = None
		"""The object whose presentation the user dismissed, while they stay on it."""
		self._dismissedPresentation: Presentation | None = None
		"""The presentation that was dismissed, for providers that scope by validity."""
		self._unanswerableChecks = 0
		"""Consecutive times the dismissed presentation could not say whether it is valid."""

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
		2. The active presentation, if it is still valid and its own provider is
		   the first that can provide. A provider that opts into reuse is taken
		   at its presentation's word before ``canProvide`` runs at all.
		3. A new presentation from the first provider that can provide

		:param obj: The current navigator object.
		:param triggerReason: The triggering event (e.g. ``TriggerReason.CARET_MOVE``),
			or ``None`` when no discrete navigation event applies. Forwarded to
			``isStillValid`` so presentations can react to specific event types.
		"""
		if self._forcedPresentation:
			forcedValid = self._stillValid(self._forcedPresentation, triggerReason)
			if forcedValid is not False:
				# None as well as True: an unanswerable check must not drop a
				# mode the user explicitly forced.
				self._activePresentation = self._forcedPresentation
				return
			else:
				log.debug("Forced presentation %s no longer valid", self._forcedPresentation.name)
				self._forcedPresentation = None

		# Arriving at the active presentation's own provider proves every
		# higher-priority provider has already declined this object.
		dismissed = self._isDismissed(obj, triggerReason)
		if not dismissed:
			self._dismissedObject = None
			self._dismissedPresentation = None
			self._unanswerableChecks = 0

		activePresentation = self._activePresentation
		activeProvider = activePresentation.provider if activePresentation else None
		# None until the presentation has been asked, so it is asked once.
		activeStillValid: bool | None = None
		matchingProvider: PresentationProvider | None = None
		candidates = self._providers[-1:] if dismissed else self._providers
		for provider in candidates:
			if (
				activePresentation is not None
				and provider is activeProvider
				and provider.reusesActivePresentation
			):
				# None counts as a no here: re-running detection costs a walk,
				# where holding a presentation we could not vouch for risks
				# drawing a table the navigator has already left.
				activeStillValid = self._stillValid(activePresentation, triggerReason) is True
				if activeStillValid:
					return
			if provider.canProvide(obj):
				matchingProvider = provider
				break

		if matchingProvider is None:
			if self._activePresentation is not None:
				log.debug("No provider matched (was: %s)", self._activePresentation.name)
			self._activePresentation = None
			return

		# Rebuilding is not free: a presentation's constructor can carry real
		# work, as ``LibraryBraillePresentation``'s blocking library bootstrap does.
		if activePresentation is not None and matchingProvider is activeProvider:
			if activeStillValid is None:
				activeStillValid = self._stillValid(activePresentation, triggerReason) is True
			if activeStillValid:
				return

		# 4. Create new presentation from matching provider
		previousName = self._activePresentation.name if self._activePresentation else None
		presentation = matchingProvider.createPresentation(obj, self.display)
		presentation.provider = matchingProvider
		self._activePresentation = presentation
		log.debug("Created new presentation: %s (was: %s)", presentation.name, previousName)

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

	def dismissActivePresentation(self, obj: NVDAObject) -> None:
		"""Step back from the presentation on screen for as long as ``obj`` is current.

		The way out of a visual mode. Forcing braille instead would pin it: a
		forced presentation short-circuits ``update`` while it stays valid, and
		both braille presentations always are, so nothing would auto-enter again
		in any mode until a screen-capture toggle cleared it.

		Dismissing instead lets braille win by ordinary fallback. Moving
		anywhere else lifts it, so another table or an image still enters its own
		mode, and coming back later is a fresh visit.

		"Anywhere else" cannot mean "any other NVDAObject" for a mode that spans
		many of them. A table is navigated cell by cell, and every cell is a
		different object, so an object-scoped dismissal would be undone by the
		next arrow key and table mode would come straight back — the chord would
		read as dead. So the dismissal also holds while the dismissed
		presentation reports itself still valid, but only for providers that set
		``reusesActivePresentation``. That flag already means "this
		presentation's ``isStillValid`` is a complete answer on its own"; for
		everything else validity is not a safe scope, since a presentation whose
		``isStillValid`` is unconditionally True — both braille ones, screen
		capture — would pin the dismissal for the session, which is the failure
		this replaced forcing to avoid.

		It steps back from the whole visual stack, not just the one presentation
		named: while it holds, every provider but the braille fallback is
		skipped. "Not this object" is what the user means by the chord, and
		which provider would have claimed the object next is not something they
		can see.

		:param obj: The navigator object the user is on.
		"""
		# Captured before the force is dropped, so a dismissal of a forced
		# presentation is scoped by that presentation and not by whatever
		# happened to be active underneath it.
		self._dismissedPresentation = self._activePresentation
		self._unanswerableChecks = 0
		# A force outranks the providers entirely, so it has to go too, or the
		# dismissal would change nothing.
		self._forcedPresentation = None
		self._dismissedObject = obj

	def _isDismissed(self, obj: NVDAObject, triggerReason: TriggerReason | None = None) -> bool:
		"""Whether the dismissal still covers ``obj``.

		Two ways it can, either sufficient:

		1. ``obj`` is the object the user dismissed. Compared with ``==``: NVDA
		   mints a fresh NVDAObject per event, and ``NVDAObject.__eq__`` routes
		   to ``_isEqual``, which is what identifies the same element across
		   events. Identity would forget the dismissal immediately.
		2. The dismissed presentation is still valid and came from a provider
		   that opts into ``reusesActivePresentation`` — the flag that means its
		   ``isStillValid`` is a complete answer. This is what keeps a dismissed
		   table dismissed while the user moves from cell to cell; leaving the
		   table invalidates the presentation and lifts it.
		"""
		try:
			if self._dismissedObject is not None and self._dismissedObject == obj:
				return True
		except Exception:
			# A dead COM object raises from __eq__. Fall through to the
			# presentation's own answer rather than deciding on the raise.
			log.debug("Dismissed object comparison raised", exc_info=True)

		presentation = self._dismissedPresentation
		if presentation is None:
			return False
		provider = presentation.provider
		if provider is None or not provider.reusesActivePresentation:
			return False

		valid = self._stillValid(presentation, triggerReason)
		if valid is not None:
			self._unanswerableChecks = 0
			return valid

		# Unanswerable. A transient refusal - Excel rejects COM calls whenever it
		# is busy, which includes the moment the user types in a cell - must not
		# undo a dismissal the user asked for and bring the table back mid-read.
		# But an object that is genuinely gone raises every time, and holding on
		# that forever would strand the display on braille for the session, which
		# is the pinning this replaced forcing to avoid. So hold, briefly.
		self._unanswerableChecks += 1
		if self._unanswerableChecks <= MAX_UNANSWERABLE_VALIDITY_CHECKS:
			return True
		log.debug(
			"Dismissed presentation could not answer %s times running; lifting the dismissal",
			self._unanswerableChecks,
		)
		return False

	@staticmethod
	def _stillValid(presentation: Presentation, triggerReason: TriggerReason | None) -> bool | None:
		"""``presentation.isStillValid``, with a third answer for "could not tell".

		Validity checks read live application state — ``TablePresentation``'s
		walks ``windowHandle``, an Excel worksheet name and ``navObj.table``, all
		COM reads on objects that can die between events, and Excel refuses calls
		outright while it is busy. Letting that escape aborts the whole update,
		so no provider is consulted and the previous frame stays on the pins.

		But a raise must not be read as False either, because False is a
		decision: it drops a forced presentation and lifts a dismissal, both of
		which the user asked for explicitly and neither of which a transient
		``RPC_E_CALL_REJECTED`` should undo. So a raise answers None — "ask again
		next event" — and the two paths that hold user intent keep what they
		have. Only the reuse shortcut treats None as a no, where the cost is
		re-running detection rather than losing a mode.

		:returns: True or False as the presentation answered, or None if asking
			raised.
		"""
		try:
			return presentation.isStillValid(triggerReason)
		except Exception:
			log.debug(
				"Presentation %s raised from isStillValid; keeping state and asking again",
				getattr(presentation, "name", presentation),
				exc_info=True,
			)
			return None

	def clearForced(self) -> None:
		"""Clear forced presentation, return to auto-detect.

		Also lifts a dismissal. Both pin what is on screen against the
		providers, and every caller of this means "an explicit mode request
		should win now" - turning screen capture on while still standing on a
		dismissed object would otherwise appear to do nothing.
		"""
		self._forcedPresentation = None
		self._dismissedObject = None
		self._dismissedPresentation = None
		self._unanswerableChecks = 0

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
