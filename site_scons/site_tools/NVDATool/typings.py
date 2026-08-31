# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

from typing import TypedDict, Protocol


class AddonInfo(TypedDict):
	addon_name: str
	addon_summary: str
	addon_description: str
	addon_version: str
	addon_changelog: str
	addon_author: str
	addon_url: str | None
	addon_sourceURL: str | None
	addon_docFileName: str
	addon_minimumNVDAVersion: str | None
	addon_lastTestedNVDAVersion: str | None
	addon_updateChannel: str | None
	addon_license: str | None
	addon_licenseURL: str | None


class BrailleTableAttributes(TypedDict):
	displayName: str
	contracted: bool
	output: bool
	input: bool


class SymbolDictionaryAttributes(TypedDict):
	displayName: str
	mandatory: bool


class SpeechDictionaryAttributes(TypedDict):
	displayName: str
	mandatory: bool


BrailleTables = dict[str, BrailleTableAttributes]
SymbolDictionaries = dict[str, SymbolDictionaryAttributes]
SpeechDictionaries = dict[str, SpeechDictionaryAttributes]


class Strable(Protocol):
	def __str__(self) -> str: ...
