# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2026 Dot Incorporated

"""The NVDA braille names the add-on uses, resolved wherever the running version keeps them.

NVDA 2026.3 split ``braille`` into a package and left deprecation shims on the old module,
which log a warning with a full stack trace on every access. The add-on supports 2026.1
through 2026.3 (``buildVars.addon_minimumNVDAVersion``), so each name is taken from its
2026.3 home and falls back to the pre-split one, which is not deprecated there.

.. note::
	**Delete this module** and import from NVDA directly once
	``addon_minimumNVDAVersion`` reaches 2026.3.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	# The NVDA checkout CI pins for type checking predates the split, so the names are
	# resolvable there and nowhere else. This branch never runs.
	from braille import (
		BrailleBuffer,
		DisplayDimensions,
		Region,
		TextInfoRegion,
		getFocusRegions,
	)
else:
	try:
		# NVDA 2026.3 and later.
		from braille.buffers import BrailleBuffer
		from braille.display import DisplayDimensions
		from braille.regions.base import Region
		from braille.regions.focus import getFocusRegions
		from braille.regions.textInfo import TextInfoRegion
	except ImportError:
		# NVDA 2026.1 and 2026.2, where these still live on the braille module itself and
		# are not deprecated, so reading them there is silent too.
		from braille import (
			BrailleBuffer,
			DisplayDimensions,
			Region,
			TextInfoRegion,
			getFocusRegions,
		)

__all__ = [
	"BrailleBuffer",
	"DisplayDimensions",
	"Region",
	"TextInfoRegion",
	"getFocusRegions",
]
