# -*- coding: UTF-8 -*-
# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2026 Dot Incorporated


# Build customizations
# Change this file instead of sconstruct or manifest files, whenever possible.

import tomllib
from typing import cast

from site_scons.site_tools.NVDATool.typings import (
	AddonInfo,
	BrailleTables,
	SpeechDictionaries,
	SymbolDictionaries,
)
from site_scons.site_tools.NVDATool.utils import _

# Parse pyproject.toml file
with open("pyproject.toml", "rb") as f:
	pyproject = tomllib.load(f)

# Add-on information variables
addon_info = AddonInfo(
	# add-on Name/identifier, internal for NVDA
	addon_name=cast(str, pyproject["project"]["name"]),
	# Add-on summary, usually the user visible name of the addon.
	# Translators: Summary for this add-on
	# to be shown on installation and add-on information found in Add-ons Manager.
	addon_summary=_("Dot Pad"),
	# Add-on description
	addon_description=_(
		# Translators: Long description to be shown for this add-on
		# on add-on information from add-ons manager
		cast(str, pyproject["project"]["description"]),
	),
	# version
	addon_version=cast(str, pyproject["project"]["version"]),
	# Brief changelog for this version
	# Translators: what's new content for the add-on version to be shown in the add-on store
	addon_changelog=_("""New in version 1.0:

- Braille and graphics on the multi-line tactile area are now rendered by the bundled TactileDisplayAPI library. It follows the focused control itself and gives richer output for controls, math and images; the NVDA review cursor remains available as an alternative
- Tactile graphic mode for images, with pan, zoom, recentre and image inversion
- Table mode, including tables in virtual documents such as Google Docs
- Connecting, disconnecting and switching between Bluetooth and USB displays is faster, and no longer freezes NVDA when a display is off or out of range
- Requires NVDA 2026.1 or later"""),
	# Author(s)
	addon_author=f"{pyproject['project']['maintainers'][0]['name']} <{pyproject['project']['maintainers'][0]['email']}>",
	# URL for the add-on documentation support
	addon_url=None,
	# URL for the add-on repository where the source code can be found
	addon_sourceURL="https://github.com/dotincorp/nvda-addon-store/",
	# Documentation file name
	addon_docFileName="readme.html",
	# Minimum NVDA version supported (e.g. "2018.3.0", minor version is optional)
	addon_minimumNVDAVersion="2026.1",
	# Last NVDA version supported/tested
	# (e.g. "2018.4.0", ideally more recent than minimum version)
	#
	# Held at the newest *finalised* NVDA API version on purpose. The add-on
	# store rejects a stable-channel submission whose lastTestedNVDAVersion
	# names an API version flagged "experimental": true in the datastore's
	# transform/nvdaAPIVersions.json — such a submission has to go to beta or
	# dev. 2026.2 is still experimental (in beta at the time of writing), so
	# naming it here would block a stable release for no benefit: we do test
	# against newer NVDA, this field only advertises the newest API we promise
	# compatibility with. Raise it once 2026.2 is final.
	addon_lastTestedNVDAVersion="2026.1.1",
	# Add-on update channel (default is None, denoting stable releases,
	# and for development releases, use "dev".)
	# Do not change unless you know what you are doing!
	addon_updateChannel=None,
	# Add-on license such as GPL 2
	addon_license="GPL 2",
	# URL for the license document the ad-on is licensed under
	addon_licenseURL="https://www.gnu.org/licenses/gpl-2.0.html",
)

# Define the python files that are the sources of your add-on.
# You can either list every file (using ""/") as a path separator,
# or use glob expressions.
# For example to include all files with a ".py" extension
# from the "globalPlugins" dir of your add-on
# the list can be written as follows:
# pythonSources = ["addon/globalPlugins/*.py"]
# For more information on SCons Glob expressions please take a look at:
# https://scons.org/doc/production/HTML/scons-user/apd.html
pythonSources = [
	"addon/*.py",
	"addon/ble/*.py",
	"addon/brailleDisplayDrivers/*.py",
	"addon/brailleDisplayDrivers/dotPad/*.py",
	"addon/compat/*.py",
	"addon/compat/asyncioEventLoop/*.py",
	"addon/extension_points/*.py",
	"addon/globalPlugins/dotPad/*.py",
	"addon/presentations/*.py",
	"addon/tactileDisplayAPI/*.py",
	"addon/utils/*.py",
	"addon/visionEnhancementProviders/*.py",
]

# Vendored source files to include in the add-on
vendoredSources = [
	"addon/_vendor/**/*.py",
	"addon/_vendor/**/*.pyd",
]

# Files that contain strings for translation.
# Usually your python sources
i18nSources = pythonSources + ["buildVars.py"]

# Files that will be ignored when building the nvda-addon file
# Paths are relative to the addon directory,
# not to the root directory of your addon sources.
# Byte-compiled files are produced by running the addon in place (the dev install
# symlinks this tree into NVDA) and must never ship: they made up roughly half the
# entries in the built bundle. Patterns are matched with pathlib.Path.match, which
# matches from the right, so "*.pyc" catches them at any depth.
excludedFiles: list[str] = [
	"*.pyc",
	"*.pyo",
	"__pycache__/*",
]

# Base language for the NVDA add-on
# If your add-on is written in a language other than english, modify this variable.
# For example, set baseLanguage to "es" if your add-on is primarily written in spanish.
baseLanguage = "en"

# Markdown extensions for add-on documentation
# Most add-ons do not require additional Markdown extensions.
# If you need to add support for markup such as tables, fill out the below list.
# Extensions string must be of the form "markdown.extensions.extensionName"
# e.g. "markdown.extensions.tables" to add tables.
markdownExtensions: list[str] = []

# Custom braille translation tables
# If your add-on includes custom braille tables (most will not), fill out this dictionary.
# Each key is a dictionary named according to braille table file name,
# with keys inside recording the following attributes:
# displayName (name of the table shown to users and translatable),
# contracted (contracted (True) or uncontracted (False) braille code),
# output (shown in output table list),
# input (shown in input table list).
brailleTables: BrailleTables = {}

# Custom speech symbol dictionaries
# Symbol dictionary files reside in the locale folder, e.g. `locale\en`, and are named `symbols-<name>.dic`.
# If your add-on includes custom speech symbol dictionaries (most will not), fill out this dictionary.
# Each key is the name of the dictionary,
# with keys inside recording the following attributes:
# displayName (name of the speech dictionary shown to users and translatable),
# mandatory (True when always enabled, False when not.
symbolDictionaries: SymbolDictionaries = {}

# Custom speech dictionaries (distinct from symbol dictionaries above)
# Speech dictionary files reside in the speechDicts folder and are named `name.dic`.
# Supported by NVDA 2026.2 and later.
# If your add-on includes custom speech (pronunciation) dictionaries (most will not),
# fill out this dictionary.
# Each key is the name of the dictionary,
# with keys inside recording the following attributes:
# displayName (name of the speech dictionary shown to users and translatable),
# mandatory (True when always enabled, False when not).
speechDictionaries: SpeechDictionaries = {}
