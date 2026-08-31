# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

"""
Presentation system for DotPad tactile display.

This package provides a unified presentation system for rendering content on the
tactile display. It supports multiple presentation types (braille, table, chart,
screen capture) with a consistent API.

The system consists of:
- Presentation: Abstract base class for rendering content to the display
- PresentationProvider: Abstract base class for detecting and creating presentations
- PresentationManager: Orchestrates presentation selection and lifecycle
- PresentationRenderer: Coordinates the presentation system

Usage:
    from addon.presentations import (
        PresentationManager,
        PresentationRenderer,
        BraillePresentation,
        BrailleProvider,
        TablePresentation,
        TableProvider,
        ChartPresentation,
        ChartProvider,
        ScreenCapturePresentation,
        ScreenCaptureProvider,
    )
"""

from .braille import BraillePresentation, BrailleProvider
from .chart import ChartPresentation, ChartProvider
from .manager import PresentationManager
from .base import Presentation, PresentationProvider
from .renderer import PresentationRenderer
from .screenCapture import ScreenCapturePresentation, ScreenCaptureProvider
from .table import TablePresentation, TableProvider

__all__ = [
	"Presentation",
	"PresentationProvider",
	"PresentationManager",
	"PresentationRenderer",
	"BraillePresentation",
	"BrailleProvider",
	"TablePresentation",
	"TableProvider",
	"ChartPresentation",
	"ChartProvider",
	"ScreenCapturePresentation",
	"ScreenCaptureProvider",
]
