# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2025-2026 Dot Incorporated

from tactile import TactileGraphicsBuffer


class DpTactileGraphicsBuffer(TactileGraphicsBuffer):
	cellWidth = 2
	cellHeight = 4

	def __init__(self, hCellCount: int, vCellCount: int):
		self.hCellCount = hCellCount
		self.vCellCount = vCellCount
		self._cellBuffer = bytearray(hCellCount * vCellCount)
		hPixelCount = hCellCount * self.cellWidth
		vPixelCount = vCellCount * self.cellHeight
		super().__init__(hPixelCount, vPixelCount)

	def setDot(self, x: int, y: int):
		"""
		Set a specific dot in the tactile graphics buffer.

		Args:
			x (int): The horizontal pixel coordinate.
			y (int): The vertical pixel coordinate.

		Calculates the corresponding cell and bit position, and sets the dot
		if the coordinates are within the buffer's dimensions.
		"""
		if not (0 <= x < self.width) or not (0 <= y < self.height):
			return
		vCellIndex = int(y / self.cellHeight)
		hCellIndex = int(x / self.cellWidth)
		cellIndex = (vCellIndex * self.hCellCount) + hCellIndex
		bit = (y % self.cellHeight) + ((x % self.cellWidth) * self.cellHeight)
		self._cellBuffer[cellIndex] |= 2**bit

	def getRowCells(self, row: int):
		startIndex = row * self.hCellCount
		return self._cellBuffer[startIndex : startIndex + self.hCellCount]
