# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

"""
Drawing primitives for tactile graphics.

All functions accept a DpTactileGraphicsBuffer as first parameter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tactile.braille import CELL_WIDTH, drawBrailleCells

# Re-exported so existing consumers of utils.drawing keep working; utils.braille owns
# the implementation, so the table-resolution logic lives in exactly one place.
from .braille import translateTextToBraille as translateTextToBraille

if TYPE_CHECKING:
	from ..brailleDisplayDrivers.dotPad.tactileBuffer import DpTactileGraphicsBuffer
	from .chartAxis import ACTIVE_BAR_MARKER_STYLE, ActiveBarMarkerStyle

# Runtime imports using NVDA's addon module loading
if not TYPE_CHECKING:
	import addonHandler

	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	chartAxis_module = addon.loadModule("utils.chartAxis")
	ACTIVE_BAR_MARKER_STYLE = chartAxis_module.ACTIVE_BAR_MARKER_STYLE
	ActiveBarMarkerStyle = chartAxis_module.ActiveBarMarkerStyle

# Re-export with consistent naming
BRAILLE_CELL_WIDTH: int = CELL_WIDTH
BRAILLE_CELL_SPACING: int = 1  # Default spacing between cells


def drawLine(
	buffer: DpTactileGraphicsBuffer,
	x: int,
	y: int,
	length: int,
	vertical: bool = False,
) -> None:
	"""Draw a line on the buffer.

	:param buffer: The tactile graphics buffer to draw on.
	:param x: Starting x-coordinate.
	:param y: Starting y-coordinate.
	:param length: Length of the line in dots.
	:param vertical: If True, draw vertically. If False, draw horizontally.
	"""
	for i in range(length):
		if vertical:
			buffer.setDot(x, y + i)
		else:
			buffer.setDot(x + i, y)


def generateAZColumnLabel(colNum: int) -> str:
	"""Generate Excel-style column label (A, B, ..., Z, AA, AB, ...).

	:param colNum: 0-based column number.
	:returns: Column label string.
	"""
	charList: list[str] = []
	while True:
		div, remainder = divmod(colNum, 26)
		charList.insert(0, chr(97 + remainder))
		if div == 0:
			break
		colNum = div - 1
	return "".join(charList)


def detectDecimalSeparatorFromFormat(numberFormat: str) -> str | None:
	"""Detect the decimal separator from an Excel number format string.

	Analyzes the format pattern to determine which separator (. or ,) is the
	decimal separator vs the thousands separator.

	Rules:
	- The decimal separator is followed by 1-2 digits at the end (e.g., .00, ,0)
	- The thousands separator is followed by groups of 3 digits (e.g., ,##0, .##0)

	:param numberFormat: Excel number format (e.g., "#,##0.00" or "#.##0,00").
	:returns: The detected decimal separator ("." or ","), or None if not detected.
	"""
	if not numberFormat:
		return None

	# Skip special formats
	if "%" in numberFormat or "E" in numberFormat or "e" in numberFormat:
		return None

	# Check if format contains both separators
	hasDot = "." in numberFormat
	hasComma = "," in numberFormat

	if not hasDot and not hasComma:
		return None
	if hasDot and not hasComma:
		return "."
	if hasComma and not hasDot:
		return ","

	# Both separators present - analyze which is the decimal separator
	# The decimal separator is the LAST one, followed by 1-2 digit placeholders
	dotIndex = numberFormat.rfind(".")
	commaIndex = numberFormat.rfind(",")

	def countTrailingDigits(fromIndex: int) -> int:
		"""Count 0 and # characters after the given index."""
		count = 0
		for char in numberFormat[fromIndex + 1 :]:
			if char in ("0", "#"):
				count += 1
			else:
				break
		return count

	dotTrailing = countTrailingDigits(dotIndex)
	commaTrailing = countTrailingDigits(commaIndex)

	# The decimal separator typically has 1-2 trailing digits
	# The thousands separator typically has 3 trailing digits
	# Use the last separator that has 1-2 trailing digits as the decimal
	if dotIndex > commaIndex:
		# Dot comes last
		if dotTrailing <= 2:
			return "."
		elif commaTrailing <= 2:
			return ","
	else:
		# Comma comes last
		if commaTrailing <= 2:
			return ","
		elif dotTrailing <= 2:
			return "."

	# Fallback: the last separator is likely the decimal
	return "." if dotIndex > commaIndex else ","


def _getDecimalPlacesFromExcelFormat(numberFormat: str, decimalSeparator: str = ".") -> int | None:
	"""Extract decimal places from Excel number format string.

	:param numberFormat: Excel number format (e.g., "0.00", "#,##0.0", "0%").
	:param decimalSeparator: The decimal separator used in the format (locale-dependent).
	:returns: Number of decimal places, or None if format cannot be parsed or is a special format.
	"""
	if not numberFormat:
		return None

	# Skip special formats that don't represent raw numbers
	# (percentages multiply by 100, scientific notation, etc.)
	if "%" in numberFormat or "E" in numberFormat or "e" in numberFormat:
		return None

	# Find the decimal separator in the format
	sepIndex = numberFormat.find(decimalSeparator)
	if sepIndex == -1:
		# No decimal separator in format means 0 decimal places
		return 0

	# Count digits after the decimal separator (0 or #)
	decimalPart = numberFormat[sepIndex + 1 :]
	count = 0
	for char in decimalPart:
		if char in ("0", "#"):
			count += 1
		elif char in (";", " ", '"'):
			# Stop at section separators or string literals
			break
	return count


def generateYValueLabels(
	minY: float,
	maxY: float,
	yCount: int,
	numberFormat: str | None = None,
	formatDecimalSep: str = ".",
) -> list[str]:
	"""Generate Y-axis value labels.

	:param minY: Minimum Y value.
	:param maxY: Maximum Y value.
	:param yCount: Number of labels.
	:param numberFormat: Optional Excel number format string to respect.
	:param formatDecimalSep: Decimal separator used in numberFormat (locale-dependent).
	:returns: List of formatted label strings, right-justified.
	"""
	if yCount <= 0:
		return []
	if yCount == 1:
		return [str(minY)]

	yRange = maxY - minY
	yStep = yRange / (yCount - 1)
	yValues = [minY + (yStep * i) for i in range(yCount)]

	# Determine decimal places from Excel format or calculate from values
	decimalPlaces: int | None = None
	if numberFormat:
		decimalPlaces = _getDecimalPlacesFromExcelFormat(numberFormat, formatDecimalSep)

	if decimalPlaces is None:
		# Fallback: calculate decimal places needed from values
		decimalPlaces = max(len(format(x, "g").partition(".")[2]) for x in yValues)
		decimalPlaces = min(decimalPlaces, 1)

	formatSpec = f".{decimalPlaces}f"

	yLabels = [format(val, formatSpec) for val in yValues]
	maxLen = max(len(label) for label in yLabels)
	yLabels = [label.rjust(maxLen) for label in yLabels]
	# Use Excel's decimal separator for output consistency
	yLabels = [label.replace(".", formatDecimalSep) for label in yLabels]
	return yLabels


def drawHorizontalRuler(
	buffer: DpTactileGraphicsBuffer,
	x: int,
	y: int,
	colStartOffset: int,
	colEndOffset: int,
	spacing: int,
	activeColIndex: int | None = None,
) -> tuple[int, int]:
	"""Draw horizontal ruler with column labels (a-z) in braille.

	:param buffer: The tactile graphics buffer to draw on.
	:param x: Starting x-coordinate.
	:param y: Starting y-coordinate.
	:param colStartOffset: Starting column number (0-based).
	:param colEndOffset: Ending column number (exclusive).
	:param spacing: Spacing between column labels.
	:param activeColIndex: Index of active column to highlight (0-based, absolute).
	:returns: Tuple of (width, height) of drawn ruler.
	"""
	numCols = colEndOffset - colStartOffset
	deltaX = 0
	deltaY = 0

	# Draw horizontal line
	drawLine(buffer, x, y, (numCols * spacing) + 1, vertical=False)
	deltaX += 2
	deltaY += 2

	# Draw column labels
	for i in range(colStartOffset, colEndOffset):
		label = generateAZColumnLabel(i)
		cells = translateTextToBraille(label, brailleTable="en-us-comp8.ctb")

		# Check if this column is active
		isActive = activeColIndex is not None and i == activeColIndex

		drawBrailleCells(buffer, x + deltaX, y + deltaY, cells)

		if isActive:
			labelWidth = len(cells) * (BRAILLE_CELL_WIDTH + BRAILLE_CELL_SPACING)
			if ACTIVE_BAR_MARKER_STYLE == ActiveBarMarkerStyle.FLANKING:
				# Draw flanking lines on each side of label
				drawLine(buffer, x + deltaX - 1, y + deltaY, 3, vertical=True)
				drawLine(buffer, x + deltaX + labelWidth, y + deltaY, 3, vertical=True)
			elif ACTIVE_BAR_MARKER_STYLE == ActiveBarMarkerStyle.UNDERLINE:
				# Draw horizontal line below the label (lowercase letters are 3 dots tall)
				drawLine(buffer, x + deltaX, y + deltaY + 3, labelWidth, vertical=False)

		deltaX += spacing

	# Height depends on marker style (underline needs extra row)
	if ACTIVE_BAR_MARKER_STYLE == ActiveBarMarkerStyle.UNDERLINE:
		return deltaX, deltaY + 4  # label(3) + underline(1)
	return deltaX, deltaY + 3  # label(3) only


def drawVerticalRuler(
	buffer: DpTactileGraphicsBuffer,
	x: int,
	y: int,
	minY: float,
	maxY: float,
	yCount: int,
	spacing: int = 3,
	numberFormat: str | None = None,
	formatDecimalSep: str = ".",
) -> tuple[int, int]:
	"""Draw vertical ruler with Y-value labels in braille.

	:param buffer: The tactile graphics buffer to draw on.
	:param x: Starting x-coordinate.
	:param y: Starting y-coordinate.
	:param minY: Minimum Y value.
	:param maxY: Maximum Y value.
	:param yCount: Number of labels.
	:param spacing: Spacing between labels.
	:param numberFormat: Optional Excel number format string to respect.
	:param formatDecimalSep: Decimal separator used in numberFormat (locale-dependent).
	:returns: Tuple of (width, height) of drawn ruler.
	"""
	labels = generateYValueLabels(
		minY,
		maxY,
		yCount,
		numberFormat=numberFormat,
		formatDecimalSep=formatDecimalSep,
	)
	if not labels:
		return 0, 0

	labels.reverse()

	deltaX = 0
	rulerHeight = (len(labels) - 1) * spacing

	for i, label in enumerate(labels):
		cells = translateTextToBraille(label, brailleTable="en-us-comp8.ctb")
		deltaX = max(deltaX, len(cells) * (BRAILLE_CELL_WIDTH + BRAILLE_CELL_SPACING))
		# Position: first label at top (y), last label at bottom (y + rulerHeight)
		tickY = y + (i * spacing)
		# Center 4-dot braille label on the tick
		drawBrailleCells(buffer, x, tickY - 2, cells)
		buffer.setDot(x + deltaX, tickY)

	deltaX += 1
	drawLine(buffer, x + deltaX, y, rulerHeight + 1, vertical=True)

	return deltaX + 1, rulerHeight
