# Dot Pad add-on for the NVDA screen reader
# This file is covered by the GNU General Public License version 2.
# See the file COPYING.txt for more details.
# Copyright (C) 2023-2025 Dot Incorporated

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum, unique
from queue import Empty, PriorityQueue
from typing import (
	TYPE_CHECKING,
	Any,
	NamedTuple,
	cast,
)
from weakref import ref

import addonHandler
import bdDetect
import braille
import core
import hwIo
import inputCore
import ui
from baseObject import AutoPropertyObject, ScriptableObject
from globalCommands import SCRCAT_BRAILLE
from logHandler import log
from scriptHandler import script
from tactile.braille import CELL_WIDTH, drawBrailleCells

from .tactileBuffer import DpTactileGraphicsBuffer

try:
	from ...utils.testing import IS_UNDER_UNITTEST
except ImportError:
	IS_UNDER_UNITTEST = False  # type: ignore

if TYPE_CHECKING or IS_UNDER_UNITTEST:
	from ... import configuration
	from ...ble.detection import KEY_BLE, detector
	from ...ble.hwIo import Ble, createBle
	from ...tactileDisplayAPI import iniPatcher
	from ...tactileDisplayAPI import simulatedDisplay as _simulatedDisplay
	from ...tactileDisplayAPI.callbackServer import TactileDisplayCallbacks
	from ...tactileDisplayAPI.libraryWorker import LibraryWorker
	from ...tactileDisplayAPI.wrapper import TactileDisplayAPI
	from ...utils.vendor import ensureVendorPath

	ensureVendorPath()

	import bleak
else:
	addon: addonHandler.Addon = addonHandler.getCodeAddon()

	# Bootstrap vendor path before importing bleak
	vendorUtils = addon.loadModule("utils.vendor")
	vendorUtils.ensureVendorPath()

	import bleak

	detector = addon.loadModule("ble.detection").detector
	createBle = addon.loadModule("ble.hwIo").createBle
	KEY_BLE = addon.loadModule("ble.detection").KEY_BLE
	configuration = addon.loadModule("configuration")
	# Library singleton components loaded via the same loadModule pattern so
	# unit tests can patch the addon-absolute import paths and have it stick.
	LibraryWorker = addon.loadModule("tactileDisplayAPI.libraryWorker").LibraryWorker
	TactileDisplayAPI = addon.loadModule("tactileDisplayAPI.wrapper").TactileDisplayAPI
	TactileDisplayCallbacks = addon.loadModule("tactileDisplayAPI.callbackServer").TactileDisplayCallbacks
	_simulatedDisplay = addon.loadModule("tactileDisplayAPI.simulatedDisplay")
	iniPatcher = addon.loadModule("tactileDisplayAPI.iniPatcher")

#: USB vendor and product ID
USB_ID = "VID_0403&PID_6010"

#: Baud rate for the serial connection over USB
SERIAL_BAUD_RATE = 115200

#: BLE services and characteristics
BLE_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"
BLE_READ_CHARACTERISTIC_UUID = "49535343-1E4D-4BD9-BA61-23C647249616".lower()
BLE_WRITE_CHARACTERISTIC_UUID = "49535343-8841-43F4-A8D4-ECBE34729BB3".lower()

# D3-based devices with hardware auto-refresh
D3_DEVICE_NAMES: set[str] = {"DotPad320X"}

#: ``DisplayDescriptor.refreshTime`` is expressed in 100 ms units (Dot protocol
#: specification, board information bytes 8 and 12; max 25.5 s).
REFRESH_TIME_UNIT_SECONDS: float = 0.1
#: Headroom over the device's stated refresh time. That figure is the maximum for
#: refreshing the *entire* area, and the specification notes that wireless transports
#: add delay on top of it, so a single line has generous margin here.
RENDER_TIMEOUT_FACTOR: float = 2.0
#: Used when the device reports no refresh time, e.g. a truncated board information
#: response.
DEFAULT_RENDER_TIMEOUT_SECONDS: float = 10.0
#: How often to check the link is still up while waiting for a line to render. Keeping
#: this short is what makes a disconnect noticeable quickly even though the render
#: budget itself is deliberately generous.
CONNECTION_POLL_SECONDS: float = 0.5
#: Consecutive render timeouts, with the link apparently up, before giving up on the
#: display. This is the only thing that catches a device powered off while its USB
#: serial interface stays enumerated: writes keep succeeding and nothing raises.
#:
#: Two, not more: the budget is already the device's stated *maximum* for refreshing the
#: entire area, doubled, and any packet at all from the display resets the counter. So
#: this is two full worst-case refreshes with complete silence, which a merely slow
#: display will not produce. Hardware logs showed six costing ~43s to give up.
MAX_CONSECUTIVE_RENDER_TIMEOUTS: int = 2
#: Budget per packet once termination has begun. Clearing the display on the way out is
#: best-effort, and terminate() runs on the main thread when NVDA switches displays.
TERMINATE_ACK_TIMEOUT_SECONDS: float = 1.0
#: Total budget for flushing those clear packets before terminating regardless.
TERMINATE_DRAIN_TIMEOUT_SECONDS: float = 3.0
#: Budget for the sender thread to notice it should exit. It polls every
#: CONNECTION_POLL_SECONDS, so this only expires if it is stuck in a write that will not
#: return -- which must not hold the main thread.
TERMINATE_JOIN_TIMEOUT_SECONDS: float = 2.0

# Auto refresh
AUTO_REFRESH_NUM: int = 3
AUTO_REFRESH_PRIORITY: int = 999

# Long press threshold in seconds
LONG_PRESS_THRESHOLD: float = 1.5

DP_SYNC = b"\xaa\x55"


def _setBrailleTablesOnWorker(tda: object, tableName: str) -> None:
	"""Submit ``SetBrailleTables(literary, math, computer)`` to the library
	on the worker thread, using NVDA's currently-active table for all
	three slots.

	NVDA doesn't expose separate math / computer-braille table
	preferences — we pass the literary table for math (the library renders
	math equations as braille text), and the literary table for computer
	braille too (NVDA's ``inputTable`` is for input-side transcription, not
	output, so reusing literary is the safest choice on the output side).

	Same fire-and-forget shape as ``_setRegisterEventsOnWorker``. Logs
	at debug on success / warning on failure (one-time per driver life).
	"""
	try:
		# All three slots get NVDA's literary table. See docstring.
		tda.setBrailleTables(tableName, tableName, tableName)  # type: ignore[attr-defined]
		log.debug(f"dotPad: setBrailleTables({tableName!r}) succeeded")
	except Exception:
		log.warning(
			f"dotPad: setBrailleTables({tableName!r}) failed; library will "
			"keep its default table. Multi-line braille output may not match "
			"NVDA's configured shape.",
			exc_info=True,
		)


def _setRegisterEventsOnWorker(tda: object, worker: LibraryWorker | None = None) -> None:
	"""Submit ``RegisterEvents(True)`` to the library on the worker thread.

	Module-level (vs a closure) so the library worker's submit queue captures a
	stable reference. Called via ``BrailleDisplayDriver.enableLibraryUiaEvents``
	by ``LibraryBraillePresentation`` AFTER its blocking bootstrap — never at
	driver init — so the bootstrap's blocking ``ExecuteOperation`` runs while
	events are OFF (events live during a blocking call starves the STA pump and
	heap-corrupts the library).

	On success we flag the worker as UIA-subscribed (``worker`` is the owning
	:class:`LibraryWorker`, passed by the caller) so timeout diagnostics record
	that the library's autonomous UIA work was active.
	"""
	try:
		tda.setRegisterEvents(True)  # type: ignore[attr-defined]
		if worker is not None:
			worker.noteUiaEventsEnabled()
		log.debug("dotPad: setRegisterEvents(True) succeeded")
	except Exception:
		log.warning(
			"dotPad: setRegisterEvents(True) failed; library-driven braille "
			"mode will not receive autonomous events. The user-visible "
			"effect is no output on the multi-line area in library mode. "
			"NVDA-driven mode is unaffected.",
			exc_info=True,
		)


def _disableRegisterEventsOnWorker(tda: object, worker: LibraryWorker | None = None) -> None:
	"""Submit ``RegisterEvents(False)`` to the library on the worker thread.

	Counterpart to :func:`_setRegisterEventsOnWorker`. Called when leaving
	library-driven-braille mode so that subsequent explicit blocking calls
	(graphics pan/zoom ``ExecuteOperation``, the next braille bootstrap) run
	with UIA events OFF — the only state in which a blocking call is safe.
	"""
	try:
		tda.setRegisterEvents(False)  # type: ignore[attr-defined]
		if worker is not None:
			worker.noteUiaEventsDisabled()
		log.debug("dotPad: setRegisterEvents(False) succeeded")
	except Exception:
		log.warning("dotPad: setRegisterEvents(False) failed", exc_info=True)


def _setShowBrailleOnScreenOnWorker(tda: object, enable: bool) -> None:
	"""Submit ``ShowBrailleOnScreen(enable)`` to the library on the worker thread.

	Called from ``_setupLibrarySingleton`` to re-sync the library's on-screen
	viewer to the addon's persisted ``viewerOnScreen`` config flag whenever
	a new driver attaches. Without this, a user who had the viewer enabled in
	a prior session would see the menu item checked at startup but the viewer
	would stay closed until they clicked off + on.

	Same fire-and-forget shape as ``_setRegisterEventsOnWorker``. Logs at
	debug on success / warning on failure.
	"""
	try:
		tda.showBrailleOnScreen(enable)  # type: ignore[attr-defined]
		log.debug(f"dotPad: showBrailleOnScreen({enable}) (driver-init sync) succeeded")
	except Exception:
		log.warning(
			f"dotPad: showBrailleOnScreen({enable}) (driver-init sync) failed; "
			"library viewer state may not match the menu / config. "
			"Toggling the Tools-menu item off + on will retry.",
			exc_info=True,
		)


def _setLineSpacingOnWorker(tda: object, paddingDots: int, forceSixDot: bool) -> None:
	"""Submit line-spacing calls to the library on the worker thread.

	v1.22 methods: ``SetBrailleLinePadding`` sets the inter-line dot gap;
	``ForceSixDotBraille`` forces 6-dot cells (fitting more lines) when ``True``.
	Submitted at driver init and re-applied live when the setting changes. Same
	fire-and-forget shape as the other post-setup submits.
	"""
	try:
		tda.setBrailleLinePadding(paddingDots)  # type: ignore[attr-defined]
		tda.forceSixDotBraille(forceSixDot)  # type: ignore[attr-defined]
		log.debug(f"dotPad: setBrailleLinePadding({paddingDots}) forceSixDotBraille({forceSixDot}) succeeded")
	except Exception:
		log.warning(
			f"dotPad: line-spacing calls (padding={paddingDots}, forceSixDot={forceSixDot}) failed; "
			"spacing may not match the setting.",
			exc_info=True,
		)


def _setHybridModeOnWorker(tda: object, enable: bool) -> None:
	"""Submit ``SetHybridPrintAndBrailleMode(enable)`` to the library on the worker thread.

	v1.0.21 method: when enabled, activates simultaneous print+braille rendering on the
	focused-control multi-line area. Submitted once during driver init from the persisted
	``hybridPrintAndBraille`` config flag (after ``setRegisterEvents(True)``) and re-applied
	live when the setting changes. Same fire-and-forget shape as the other post-setup
	submits to avoid blocking the main thread.
	"""
	try:
		tda.setHybridPrintAndBrailleMode(enable)  # type: ignore[attr-defined]
		log.debug(f"dotPad: setHybridPrintAndBrailleMode({enable}) succeeded")
	except Exception:
		log.warning(
			f"dotPad: setHybridPrintAndBrailleMode({enable}) failed; hybrid print+braille "
			"mode may not match the setting. Library-driven braille mode continues to work "
			"without hybrid output.",
			exc_info=True,
		)


# Packet types
@unique
class PacketType(Enum):
	REQ_FIRMWARE_VERSION = b"\x00\x00"
	REQ_DEVICE_NAME = b"\x01\x00"
	REQ_BOARD_INFORMATION = b"\x01\x10"
	REQ_DISPLAY_LINE = b"\x02\x00"
	REQ_DISPLAY_CURSOR = b"\x02\x10"

	RSP_FIRMWARE_VERSION = b"\x00\x01"
	RSP_DEVICE_NAME = b"\x01\x01"
	RSP_BOARD_INFORMATION = b"\x01\x11"
	RSP_DISPLAY_LINE = b"\x02\x01"
	RSP_DISPLAY_CURSOR = b"\x02\x11"

	NTF_DISPLAY_LINE = b"\x02\x02"
	NTF_DISPLAY_CURSOR = b"\x02\x12"
	NTF_KEYS_SCROLL = b"\x03\x02"
	NTF_KEYS_PERKINS = b"\x03\x12"
	NTF_KEYS_ROUTING = b"\x03\x22"
	NTF_KEYS_FUNCTION = b"\x03\x32"
	NTF_ERROR = b"\x99\x02"

	@property
	def code(self) -> bytes:
		return self.value

	def _nameStartsWith(self, match: str) -> bool:
		"""
		Returns True if the name of the enum member starts with the given match string.
		"""
		return self.name.startswith(match)

	@property
	def isRequest(self) -> bool:
		"""
		Returns True if this packet type is a request.

		A request packet is sent by the host to the Dot Pad.
		"""
		return self._nameStartsWith("REQ")

	@property
	def isResponse(self) -> bool:
		"""
		Returns True if this packet type is a response.

		A response packet is sent by the Dot Pad to the host in answer to a request pcaket.
		"""
		return self._nameStartsWith("RSP")

	@property
	def isNotification(self) -> bool:
		"""
		Returns True if this packet type is a notification.

		A notification packet is sent by the Dot Pad to the host
		based on an event that happened, such as a key press or when the display
		has finished updating.
		"""
		return self._nameStartsWith("NTF")

	@classmethod
	def fromCode(cls, code: bytes) -> PacketType:
		"""
		Returns the PacketType for the given code.
		"""
		for packetType in cls:
			if packetType.code == code:
				return packetType
		raise ValueError(f"Unknown packet type: {code!r}")


class Packet(bytes):
	"""
	Represents a packet of data exchanged between a Dot Pad braille display and the system.

	The `Packet` class provides a convenient way to work with these packets, including
	parsing the various fields (sync bytes, length, destination, type, sequence number,
	arguments, and checksum) and validating the packet's completeness and integrity.

	The `_setField` method is used internally to extract and parse the individual fields
	from the packet data. The `_validate` method checks if the packet is complete and
	valid based on the extracted field values.

	Since this is a subclass of `bytes`, it should be used as a regular (immutable) bytes instance.
	The attributes are calculated on construction and should be regaarded as read-only.
	The attributes reflect the data in the packet, but as long as `isValid`
	is not `True` they may not be fully reliable. Setting the attributes will *not*
	update the packet data itself.
	To easely construct packets, use the `makePacket` classmethod.
	"""

	sync: bytes = b""
	"First two bytes of the packet, should contain the sync bytes \xaa\x55"
	packetType: PacketType | None = None
	"The type of packet, one of the `PacketType` enums. None if type can't be determined"
	length: int = 0
	"""The length field of the packet, indicating the length including checksum,
    but excluding the first packet bytes including the length field itself"""
	destination: int = 0
	"""The destination field of the packet, indicating the line ID"""
	seq: int = 0
	"""The sequence field of the packet, bit 7 can be set to 0 (graphic mode)
    or 1 (text mode), other bits are reserved for future use"""
	args: bytes = b""
	"The argument field of the packet, containing the payload data"
	checksum: int = 0
	"The checksum field of the packet, calculated over all preceding fields"
	isComplete: bool = False
	"Whether all required fields have been extracted from the packet"
	bytesExpected: int = 0
	"The number of bytes expected to make this packet complete"
	isValid: bool = False
	"Whether the checksum is correct, indicating the packet is valid"

	def _setField(
		self,
		fieldName: str,
		startIndex: int,
		endIndex: int | None = None,
		func: Callable[[Any], Any] | None = None,
	) -> None:
		"""
		Sets the given field to a substring of the packet,
		`func` is called with the value before setting the attribute to do type
		casting or conversion.
		Fails silently if the packet is too short or if `func` raises a
		ValueError, indicating the value can't be converted to the specified type.
		"""
		val: int | bytes
		try:
			if endIndex is not None:
				val = self[startIndex:endIndex]
			else:
				val = self[startIndex]
		except IndexError:
			return
		if callable(func):
			try:
				val = func(val)
			except ValueError:
				return
		setattr(self, fieldName, val)

	def _validate(self) -> None:
		"""Check if a packet is complete and valid.

		A packet is considered complete if:
		- Sync, length, destination, type, seq, args
		  and checksum fields are present
		- Synchronization bytes match \xaa\x55
		- Its length field matches the actual length of the packet

		A packet is considered valid if:
		- Its checksum matches the calculated checksum

		This method does not return anything, but controls the `is_complete`, `is_valid`
		and `bytes_expected` attributes.
		"""
		if len(self) < 2:
			# We need at least 2 bytes to get the sync header
			self.bytesExpected = 2 - len(self)
			return
		if not self.sync == DP_SYNC:
			# The sync bytes are missing, so the packet is incomplete
			return
		if len(self) == 2:
			# We only have the sync bytes and neet at least 2 more bytes to get the length
			self.bytesExpected = 2
			return
		if self.length == 0:
			# A zero length packet is impossible, since we at least need a checksum
			return
		# We have the length field, so we can check if the packet is complete
		if not self.length == (len(self) - 4):
			# The length field does not match the actual length of the packet
			# minus the sync header and length field
			self.bytesExpected = self.length - (len(self) - 4)
			return
		else:
			# The length field matches the actual length of the packet
			# minus the sync header and length field
			self.isComplete = True
			# We have all required fields, so we can check if the packet is valid
			if self.checksum == Packet.calculateChecksum(self[4:-1]):
				# The checksum matches the calculated checksum
				self.isValid = True

	@staticmethod
	def calculateChecksum(data: bytes) -> int:
		"""
		Calculate checksum for packet data
		XOR each byte in data with 0xA5 and return result as an integer

		:param data: The data to calculate the checksum for
		:return: The checksum
		"""
		checksum = 0xA5
		for i in data:
			checksum ^= i

		return checksum

	def __new__(cls, val: bytes = b"") -> Packet:
		self = super().__new__(cls, val)
		self._setField("sync", 0, 2)
		self._setField("length", 2, 4, int.from_bytes)
		self._setField("destination", 4)
		self._setField("packetType", 5, 7, PacketType.fromCode)
		self._setField("seq", 7)
		self._setField("args", 8, -1)
		self._setField("checksum", -1)
		self._validate()
		return self

	@classmethod
	def makePacket(
		cls,
		packetType: PacketType,
		args: bytes = b"",
		destination: int = 0,
		seq: int = 0,
	):
		destinationByte: bytes = int.to_bytes(destination, 1, "big")
		seqByte: bytes = int.to_bytes(seq, 1, "big")
		length = int.to_bytes(
			len(destinationByte + packetType.code + seqByte + args) + 1,
			2,
			"big",
			signed=False,
		)
		checksum = int.to_bytes(
			cls.calculateChecksum(destinationByte + packetType.code + seqByte + args),
			1,
			"big",
		)
		packet = Packet(DP_SYNC + length + destinationByte + packetType.code + seqByte + args + checksum)
		if not packet.isValid:
			raise ValueError(f"Refusing to construct an invalid packet: {packet!r}")
		return packet


@dataclass(order=True)
class PrioritizedPacket:
	"""
	A prioritized packet, which includes the packet itself and a priority value.
	The timestamp is also included, which represents the time the packet was created.
	"""

	packet: Packet = field(compare=False)
	timestamp: float = field(default_factory=time.time, compare=False)
	"Timestamp of when the packet was created, defaults to the current time at creation"
	priority: int = field(default=0, compare=True)
	"Priority value, lower values are higher priority"


@unique
class FeatureFlag(Enum):
	HAS_GRAPHIC_DISPLAY = b"\x80"
	HAS_TEXT_DISPLAY = b"\x40"
	HAS_PERKINS_KEYS = b"\x20"
	HAS_ROUTING_KEYS = b"\x10"
	HAS_NAVIGATION_KEYS = b"\x08"
	HAS_PANNING_KEYS = b"\x04"
	HAS_FUNCTION_KEYS = b"\x02"


# Dots per cell
DP_DPC_6 = 0
DP_DPC_8 = 1


@unique
class KeyGroup(IntEnum):
	PERKINS = PacketType.NTF_KEYS_PERKINS.code[1]
	ROUTING = PacketType.NTF_KEYS_ROUTING.code[1]
	SCROLL = PacketType.NTF_KEYS_SCROLL.code[1]
	FUNCTION = PacketType.NTF_KEYS_FUNCTION.code[1]


@unique
class PerkinsKey(IntEnum):
	dot7 = 0
	dot3 = 1
	dot2 = 2
	dot1 = 3
	dot4 = 4
	dot5 = 5
	dot6 = 6
	dot8 = 7
	space = 8
	shiftLeft = 9
	controlLeft = 10
	shiftRight = 11
	controlRight = 12
	panLeft = 13
	panRight = 14
	navCenter = 16
	navUp = 17
	navRight = 18
	navDown = 19
	navLeft = 20


# Error/response codes
@unique
class ResponseCode(Enum):
	"""Response codes for DotPad protocol

	ACK indicates the packet was received and handled successfully.
	NAK indicates the packet was received but not handled successfully.
	WAIT indicates the device needs more time before receiving the next packet.
	CHECKSUM indicates the packet checksum did not match the expected value.
	"""

	ACK = 0, "Acknowledged"
	NAK = 1, "Not acknowledged"
	WAIT = 2, "Wait before sending next packet"
	CHECKSUM = 3, "Checksum mismatch"

	def __init__(self, code: int, reason: str) -> None:
		self.code = code
		self.reason = reason

	@property
	def isAck(self) -> bool:
		"""
		Returns True if this response code is a positive response (ACK).
		"""
		return self.code == ResponseCode.ACK.code

	@property
	def isNak(self) -> bool:
		"""
		Returns True if this response code is a negative response (NAK).
		"""
		return not self.isAck

	@classmethod
	def fromCode(cls, code: int) -> ResponseCode:
		"""
		Returns the ResponseCode for the given code.
		"""
		for responseCode in cls:
			if responseCode.code == code:
				return responseCode
		raise ValueError("Unknown response code: %d" % code)


class DisplayDescriptor(NamedTuple):
	rowCount: int
	columnCount: int
	dividedLine: bool
	refreshTime: int

	@classmethod
	def fromBytes(
		cls,
		rowCount: int,
		columnCount: int,
		dividedLine: int | bool,
		refreshTime: int,
	) -> DisplayDescriptor:
		"""
		Pass in a bytes object containing the display descriptor as args (e.g. using `*`)

		Converts the `divided_line` parameter from an integer to a boolean value.
		If `divided_line` is 1, it is converted to `True`, otherwise it is converted to `False`.
		"""
		dividedLine = dividedLine == 1
		return cls(
			rowCount=rowCount,
			columnCount=columnCount,
			dividedLine=dividedLine,
			refreshTime=refreshTime,
		)


class BoardInformation(NamedTuple):
	features: int
	dotsPerCell: int
	distanceBetweenPins: int
	functionKeyCount: int
	text: DisplayDescriptor
	graphic: DisplayDescriptor


class RowEntry:
	_cells: list[int]
	start: int
	end: int

	def __init__(self, cells: list[int], cellsLock: threading.Lock, start: int, end: int):
		self._cells = cells
		self._cellsLock = cellsLock
		self.start = start
		self.end = end

	def __getitem__(self, key: int | slice) -> int | list[int]:
		if isinstance(key, slice):
			start, stop, step = key.indices(self.__len__())
			return [self._cells[i] for i in range(self.start + start, self.start + stop, step)]
		else:
			if key < 0:
				key += self.__len__()
			if key < 0 or key >= self.__len__():
				raise IndexError("Cell index out of range for this row")
		return self._cells[int(self.start + key)]

	def __setitem__(self, key: int | slice, value: int | list[int]):
		if isinstance(key, slice):
			start, stop, _step = key.indices(self.__len__())
		else:
			start = stop = key
		if start < 0 or stop > self.__len__():
			raise IndexError(f"Cell index {key} out of range for this row")
		with self._cellsLock:
			self._cells[int(self.start + start) : int(self.start + stop)] = value  # type: ignore

	def __len__(self):
		return self.end - self.start

	def __repr__(self):
		return repr(self._cells[self.start : self.end])

	def __iter__(self):
		return iter(self._cells[self.start : self.end])

	def __eq__(self, other: object) -> bool:
		return self._cells[self.start : self.end] == other


class ExternalRowEntry(RowEntry):
	destination: int
	_display: ref[Display]
	awaitingAck: bool
	lastWritten: float | None
	lastRefreshed: float | None
	numTries: int
	refreshCount: int
	lastRefreshAttempt: float | None
	everWritten: bool
	"Whether this row has ever been written to the device (not just initialized)"

	def __init__(
		self,
		display: Display,
		cells: list[int],
		cellsLock: threading.Lock,
		start: int,
		end: int,
		destination: int,
	):
		super().__init__(cells, cellsLock, start, end)
		self.destination = destination
		self._display = ref(display)
		self.awaitingAck = False
		self.lastWritten = None
		self.lastRefreshed = None
		self.numTries = 0
		self.refreshCount = 0
		self.lastRefreshAttempt = None
		self.everWritten = False


class Display(AutoPropertyObject):
	"""Handle writing braille or graphics for a specific display

	A display is a collection of cells that share the same characteristics.
	A braille device can offer multiple displays, for example a single line
	text display and a multi line display that can display either text or
	graphics.
	"""

	#: Type information for awaitingAck (see _get_awaiting_ack)
	awaitingAck: bool
	#: Number of rows
	physicalNumRows: int
	#: Number of columns (cells in a row)
	physicalNumCols: int

	#: Destination on the hardware where this display starts
	startDestination: int

	# Cell dimentions
	#: Cell height, in number of pins
	cellHeight: int
	#: Cell width, in number of pins
	cellWidth: int

	# Braille properties

	#: Horizontal cell spacing in number of pins.
	#: So 1 will leave one empty row of pins between braille characters
	horizontalCellSpacing: int
	#: Vertical cell spacing in number of pins.
	#: So 1 will leave 1 empty row of pins between braille characters
	verticalCellSpacing: int
	#: Number of columns if the display is used for braille output
	numCols: int
	#: Number of rows if the display is used for braille output
	numRows: int
	#: Number of cells in the display if used for braille output
	numCells: int

	# Graphic properties

	#: Wether or not this display supports graphical output
	supportsGraphic: bool

	#: The driver for the hardware of this display
	_driver: BrailleDisplayDriver

	#: The content of the display's cells, with cell spacing applied
	#: This is suitable to be sent to the display through the driver
	externalCells: list[int]

	#: Holds references to the external rows, which provide slicing into external_cells
	externalRows: list[ExternalRowEntry]
	_writingQueuedRows: bool
	autoRefresh: bool

	def __init__(
		self,
		driver: BrailleDisplayDriver,
		numRows: int,
		numCols: int,
		startDestination: int = 0,
		supportsGraphic: bool = False,
		cellHeight: int = 4,
		cellWidth: int = 2,
		horizontalCellSpacing: int = 0,
		verticalCellSpacing: int = 0,
		autoRefresh: bool = False,
	):
		self._driver = driver
		self.physicalNumRows = numRows
		self.physicalNumCols = numCols
		self.startDestination = startDestination
		self.supportsGraphic = supportsGraphic
		self.cellHeight = cellHeight
		self.cellWidth = cellWidth
		self.horizontalCellSpacing = horizontalCellSpacing
		self.verticalCellSpacing = verticalCellSpacing
		self._writingQueuedRows = False
		self.autoRefresh = autoRefresh
		numInternalRows = int((((numRows * cellHeight) - 4) / (4 + verticalCellSpacing)) + 1)
		numInternalCols = int((((numCols * cellWidth) - 2) / (2 + horizontalCellSpacing)) + 1)
		self.externalCells = int(numRows * numCols) * [0]
		log.debug(
			f"Display initialized with {numRows} rows and {numCols} columns, "
			f"{numInternalRows} internal rows and {numInternalCols} columns",
		)
		self.externalRows = externalRows = []
		self._cellsLock = threading.Lock()
		for i in range(numRows):
			row: ExternalRowEntry = ExternalRowEntry(
				self,
				self.externalCells,
				self._cellsLock,
				i * numCols,
				(i + 1) * numCols,
				int(startDestination + i),
			)
			externalRows.append(row)
		self.clear()

	def terminate(self) -> None:
		self.clear()

	def clear(self) -> None:
		"""Clears the display by writing zeros to all rows.

		Note: This does NOT set everWritten=True, so the first display() call
		after clear() will write all rows to establish proper content.
		"""
		for row in self.externalRows:
			emptyRow: list[int] = [0] * len(row)
			row[0 : len(row)] = emptyRow
			timestamp = self.writeExternalCells(
				emptyRow,
				destination=row.destination,
				forceNoAutoRefresh=True,
			)
			row.lastWritten = timestamp
			row.everWritten = False

	def clearForTermination(self) -> None:
		"""Clear display during termination, bypassing the write block.

		This method is used during driver shutdown to ensure the display is
		cleared before closing the connection. It bypasses the normal write
		blocking to guarantee the clear packets are queued.
		"""
		for row in self.externalRows:
			emptyRow: list[int] = [0] * len(row)
			row[0 : len(row)] = emptyRow
			packet: Packet = Packet.makePacket(
				packetType=PacketType.REQ_DISPLAY_LINE,
				destination=row.destination,
				args=bytes([0] + emptyRow),
			)
			self._driver._queuePacket(packet, numRefreshes=0, _forTermination=True)  # type: ignore

	def refresh(self):
		"""Refreshes the display by rewriting current content to all rows.

		Note: We do NOT update row.lastWritten here because refresh re-sends
		existing content rather than writing new content. Updating lastWritten
		would cause a race condition where the packet sender skips refresh
		packets (it checks if row.lastWritten > packet.timestamp).
		"""
		for row in self.externalRows:
			self.writeExternalCells(list(row), destination=row.destination, forceNoAutoRefresh=True)

	def writeExternalCells(
		self,
		cells: list[int],
		destination: int,
		forceNoAutoRefresh: bool = False,
	) -> float:
		"""Write cells to the display at the given destination.

		:returns: The timestamp when the packet was queued.
		"""
		packet: Packet = Packet.makePacket(
			packetType=PacketType.REQ_DISPLAY_LINE,
			destination=destination,
			args=bytes([0] + cells),
		)
		numRefreshes = 0 if forceNoAutoRefresh else (AUTO_REFRESH_NUM if self.autoRefresh else 0)
		return self._driver._sendPacket(packet, numRefreshes)  # type: ignore

	def writeExternalRow(self, row: ExternalRowEntry):
		"""Queue a row to be written to the display.

		Sets row.lastWritten to the exact timestamp of the queued packet.
		This allows the sender to correctly detect stale packets (packets
		queued before newer content was written) without race conditions.
		"""
		timestamp = self.writeExternalCells(list(row), destination=row.destination)
		row.lastWritten = timestamp

	def _writeQueuedExternalRows(self):
		hwIo.bgThread.queueAsApc(self._writeQueuedExternalRowsBgthreadExecutor)

	def _writeQueuedExternalRowsBgthreadExecutor(self, _param: int = 0):
		if self._writingQueuedRows or not self._driver._queuedPackets.empty():  # type: ignore
			log.debug("Already writing queued packets, ignoring")
			return
		self._writingQueuedRows = True
		self._driver._ackLock.acquire()  # type: ignore
		for row in self.externalRows:
			if row.awaitingAck and row.lastWritten and (time.time() - row.lastWritten) > 0.04:
				if not row.numTries < 3:
					log.warning(f"Giving up on row {row.destination} after {row.numTries} tries")
					row.awaitingAck = False
					row.numTries = 0
					continue
				# Retry
				log.debugWarning(f"Retrying row {row.destination}")
				self.writeExternalRow(row)
		self._driver._ackLock.release()  # type: ignore
		self._writingQueuedRows = False

	def dotCoordinatesToCell(self, x: int, y: int) -> tuple[int, int, int]:
		"""Convert dot coordinates to row, cell in row and dot in cell indexes"""
		max_x: int = self.physicalNumCols * self.cellWidth
		max_y: int = self.physicalNumRows * self.cellHeight
		if x > max_x:
			raise ValueError(f"x out of range: {x} > {max_x}")
		if y > max_y:
			raise ValueError(f"y out of range: {y} > {max_y}")
		rowNumber: int = y // self.cellHeight
		cellNumber: int = x // self.cellWidth
		dotRow: int = y % self.cellHeight
		dotCol: int = x % self.cellWidth
		dotNumber: int = 0
		if dotCol == 0:
			# Dot in the left half of the cell
			dotNumber = dotRow if dotRow < 3 else 6
		else:
			# Dot in the right half of the cell
			dotNumber = (dotRow + (self.cellHeight - 1)) if dotRow < 3 else 7

		return rowNumber, cellNumber, dotNumber

	def display(self, tgBuf: DpTactileGraphicsBuffer, forceRefresh: bool = False):
		"""Display graphics on this display

		Displays the provided tactile graphics buffer on the display. Use this method for graphics or low level cacess to the pins.
		Use `displayBraille` if you want to display braille cells with the correct cell spacing applied.
		"""
		for rowNumber in range(tgBuf.vCellCount):
			row: ExternalRowEntry = self.externalRows[rowNumber]
			bufferRowCells = list(tgBuf.getRowCells(rowNumber))
			rowsEqual = row == bufferRowCells
			# Force write if row has never been written (even if data appears equal to initialized zeros)
			needsWrite = not rowsEqual or forceRefresh or not row.everWritten
			if not needsWrite:
				continue
			row[0 : len(row)] = bufferRowCells
			row.awaitingAck = False
			row.numTries = 0
			row.everWritten = True
			self.writeExternalRow(row)

	def getBrailleCellPosition(self, cellIndex: int) -> tuple[int, int]:
		"""Convert braille cell index to x,y coordinates on tactile buffer.

		Takes a linear cell index (row-major order) and calculates the
		corresponding x,y position in dots on the tactile buffer, accounting
		for cell dimensions and spacing.

		:param cellIndex: Linear cell index (0-based, row-major order).
		:returns: (x, y) coordinates in dots on the tactile buffer.
		"""
		row = cellIndex // self.numCols
		col = cellIndex % self.numCols
		x = col * (CELL_WIDTH + self.horizontalCellSpacing)
		y = row * (self.cellHeight + self.verticalCellSpacing)
		return x, y

	def drawBrailleCells(self, buffer: DpTactileGraphicsBuffer, cells: list[int]) -> None:
		"""Draw braille cells into buffer with proper row splitting and spacing.

		Splits the cells array into rows based on display dimensions and draws
		each row at the appropriate vertical position with correct spacing.

		:param buffer: The tactile graphics buffer to draw into.
		:param cells: Flat list of braille cells (row-major order).
		"""
		# Pad cells if needed
		if len(cells) < self.numCells:
			cells = list(cells) + [0] * (self.numCells - len(cells))

		# Draw each row at proper position
		for y in range(self.numRows):
			cellOffset = y * self.numCols
			lineCells = cells[cellOffset : cellOffset + self.numCols]
			yPos = y * (self.cellHeight + self.verticalCellSpacing)
			drawBrailleCells(
				buffer,
				0,
				yPos,
				lineCells,
				hCellPadding=self.horizontalCellSpacing,
			)

	def displayBraille(self, cells: list[int], forceRefresh: bool = False):
		"""Display braille cells on this display"""
		if len(cells) < self.numCells:
			cells.extend([0] * (self.numCells - len(cells)))
		tgBuf = DpTactileGraphicsBuffer(
			hCellCount=self.physicalNumCols,
			vCellCount=self.physicalNumRows,
		)

		# Use helper method - single source of truth for cell layout
		self.drawBrailleCells(tgBuf, cells)

		self.display(tgBuf, forceRefresh)

	def _get_numRows(self) -> int:
		return int((((self.physicalNumRows * self.cellHeight) - 4) / (4 + self.verticalCellSpacing)) + 1)

	def _get_numCols(self) -> int:
		return int((((self.physicalNumCols * self.cellWidth) - 2) / (2 + self.horizontalCellSpacing)) + 1)

	def _get_numCells(self) -> int:
		return self.numRows * self.numCols

	def _get_awaitingAck(self) -> bool:
		return any([r.awaitingAck for r in self.externalRows])

	def _set_awaitingAck(self, value: bool):
		if value:
			raise ValueError(
				f"Cannot set awaiting ACK to {value}, please set this property on individual rows",
			)


class BrailleDisplayDriver(braille.BrailleDisplayDriver, ScriptableObject):
	name = "dotPad"
	description = _("DotPad")
	supportsAutomaticDetection = True
	isThreadSafe = True
	receivesAckPackets = True
	_boardInformation: BoardInformation | None
	_firmwareVersion: str
	_deviceName: str
	_keysPressed: set[tuple[KeyGroup, int]]
	_keyGroupsReleased: dict[KeyGroup, bool]
	textDisplay: Display | None
	graphicDisplay: Display | None
	primaryDisplay: Display | None
	_queuedPackets: PriorityQueue[PrioritizedPacket]
	_queuedPacketsSenderThread: threading.Thread
	"Thread that sends queued packets to the display"
	_isTerminating: threading.Event
	"Signals the packet sender thread to exit"
	_blockNewWrites: threading.Event
	"Blocks new display content from being queued during termination to ensure clean shutdown"
	_readyToSend: threading.Event
	_displayGone: bool
	_isBleConnection: bool
	_consecutiveRenderTimeouts: int
	_terminationStarted: threading.Event
	_lastSentPacket: Packet | None
	_lastSentPacketNumTries: int
	_ackLock: threading.Lock
	_maxRefreshes: dict[int, int]
	"Track maximum number of refreshes allowed per destination"
	_lastSentWasRefresh: bool
	"Whether the last sent packet was an auto-refresh packet"
	supportsHardwareBasedAutoRefresh: bool

	@classmethod
	def check(cls):
		return any(cls._getAutoPorts()) or any(cls.getManualPorts())

	@classmethod
	def registerAutomaticDetection(cls, driverRegistrar: bdDetect.DriverRegistrar):
		driverRegistrar.addUsbDevices(
			bdDetect.KEY_SERIAL,
			{
				USB_ID,  # FTDI device used by DotPad displays
			},
		)
		detector.addMatcher(cls.name, cls.isBleDotPad)
		detector.register(driverRegistrar)

	@classmethod
	def isBleDotPad(cls, peripheral: bleak.BLEDevice) -> bool:
		isDotPad: bool = peripheral.name is not None and peripheral.name.startswith("DotPad")
		return isDotPad

	@classmethod
	def _getTryPorts(cls, port: str | bdDetect.DeviceMatch) -> Iterator[bdDetect.DeviceMatch]:
		if isinstance(port, str) and port.startswith(KEY_BLE):
			device_name: str = "_".join(port.split("_")[1:])
			for _driverName, match in detector.matches(limitToDevices=[cls.name]):
				if match.id == device_name:
					yield match
		yield from super()._getTryPorts(port)

	@classmethod
	def _getAutoPorts(cls, usb: bool = True, bluetooth: bool = True) -> Iterable[bdDetect.DeviceMatch]:
		yield from super()._getAutoPorts(usb, bluetooth)
		for _driverName, match in detector.matches(usb, bluetooth, limitToDevices=[cls.name]):
			yield match

	@classmethod
	def getManualPorts(cls) -> Iterator[tuple[str, str]]:
		"""List manual ports that can be used to connect to a DotPad display.
		The list of ports is filtered by DotPads USB ID,
		there are no non-USB serial models.
		"""
		return braille.getSerialPorts(lambda port: port.get("usbID") == USB_ID)  # type: ignore

	@classmethod
	def getPossiblePorts(cls) -> OrderedDict[str, str]:
		ports = super().getPossiblePorts()
		blePorts: OrderedDict[str, str] = OrderedDict()
		for _driverName, match in detector.matches(limitToDevices=[cls.name]):
			blePorts[f"{match.type}_{match.id}"] = _("Bluetooth: %s") % match.id
		if len(blePorts) > 0 and braille.AUTOMATIC_PORT[0] not in ports.keys():
			ports.update((braille.AUTOMATIC_PORT,))
		ports.update(blePorts)
		return ports

	def __init__(self, port: str | bdDetect.DeviceMatch = "auto"):
		super().__init__()
		self._boardInformation = None
		self.textDisplay = None
		self.graphicDisplay = None
		self.primaryDisplay = None
		# Set before the reader threads start: a render triggered during __init__ must
		# be able to tell "the library has not finished starting" from "the library is
		# unavailable", and only the latter is worth telling the user about.
		self._librarySetupPending = True
		self._initSendState()
		self._queuedPackets = PriorityQueue()
		self._ackLock = threading.Lock()
		self._renderer = None
		self._isTerminating = threading.Event()
		self._blockNewWrites = threading.Event()
		# TactileDisplayAPI library singleton. Constructed below after device
		# detection completes (so we know the device dimensions to pass to
		# SimulateDisplay). Released in terminate().
		self._libraryWorker: LibraryWorker | None = None
		self._tda: TactileDisplayAPI | None = None
		self._callbackServer: TactileDisplayCallbacks | None = None
		self._libraryReady: bool = False
		self._maxRefreshes = {}
		self._queuedPacketsSenderThread = threading.Thread(target=self._queuedPacketsSender, daemon=True)
		self._queuedPacketsSenderThread.start()
		for portType, portId, portName, portInfo in self._getTryPorts(port):
			self.port = portName
			# Each candidate gets a clean slate: a port that fails to answer must not
			# suppress the probe packet for the ones after it.
			self._displayGone = False
			self._consecutiveRenderTimeouts = 0
			log.debug(f"Trying port {portType}, {portId}")
			# NVDA types DeviceMatch.type as Literal["hid", "serial", "custom"], which
			# does not know about the "BLE" type our own detector registers, so pyright
			# reads this comparison as always-False. The write side of the same mismatch
			# is suppressed in ble/detection.py where the DeviceMatch is constructed.
			self._isBleConnection = portType == KEY_BLE  # pyright: ignore[reportUnnecessaryComparison]
			if self._isBleConnection:
				try:
					# The constructor already blocks until connected and services are
					# discovered, on both the local and the hwIo.ble implementation.
					self._dev = createBle(
						portInfo["peripheral"],  # type: ignore
						BLE_SERVICE_UUID,
						BLE_WRITE_CHARACTERISTIC_UUID,
						BLE_SERVICE_UUID,
						BLE_READ_CHARACTERISTIC_UUID,
						onReceive=self._onReceive,
					)
				except RuntimeError:
					log.debugWarning("", exc_info=True)
					continue
			else:
				try:
					self._dev = hwIo.Serial(portName, baudrate=SERIAL_BAUD_RATE, onReceive=self._onReceive)
				except OSError:
					log.debugWarning("", exc_info=True)
					continue
			self._sendPacket(Packet.makePacket(PacketType.REQ_BOARD_INFORMATION))
			for _i in range(3):
				self._dev.waitForRead(self.timeout)
				if self._boardInformation:
					break
				else:
					self._readyToSend.set()
			if self._boardInformation:
				log.info(f"Found device connected via {portType} ({portName})")
				break
			self._dev.close()
		else:
			raise RuntimeError("No DotPad display found")
		self._keysPressed = set()
		self._keyGroupsReleased = {}
		self._firstKeyPressTime: float | None = None
		for group in KeyGroup:
			self._keyGroupsReleased[group] = True
		self._sendPacket(Packet.makePacket(PacketType.REQ_FIRMWARE_VERSION))
		self._sendPacket(Packet.makePacket(PacketType.REQ_DEVICE_NAME))

		# Construct the TactileDisplayAPI library singleton. After this
		# returns, _libraryReady reflects whether the singleton is usable
		# for graphic-mode rendering. Failures (no graphic display, worker
		# startup error, SimulateDisplay error) are logged but do not raise
		# — the driver is still useful for braille text in those cases.
		try:
			self._setupLibrarySingleton()
		finally:
			# Cleared even when setup fails: that is a genuine fallback and should be
			# announced.
			self._librarySetupPending = False

	def _setupLibrarySingleton(self) -> None:
		"""Construct the TactileDisplayAPI library singleton for this driver.

		Called at the end of ``__init__`` after device detection completes.
		Idempotent — calling again when ``_libraryReady`` is already True
		is a no-op. On any failure, leaves the fields cleared and logs.

		Dimensions are read directly off ``self.graphicDisplay`` /
		``self.textDisplay`` rather than via
		``_simulatedDisplay.computeSimulateDisplayArgs()`` because the
		latter reads ``braille.handler.display`` which is not yet bound
		to ``self`` while ``__init__`` is still running. NVDA attaches
		the driver to ``braille.handler.display`` AFTER ``__init__``
		returns — too late for our SimulateDisplay registration.
		"""
		if self._libraryReady:
			return
		if self.graphicDisplay is None:
			log.debug("dotPad: no graphic display attached; skipping library construction")
			return
		worker = None
		try:
			# Compute SimulateDisplay arguments directly from this driver's
			# Display instances. The library expects dot counts (not cell
			# counts) for the tactile area and raw cell counts (no spacing)
			# for the braille text area.
			graphic = self.graphicDisplay
			tactileDotsX = int(graphic.physicalNumCols) * int(graphic.cellWidth)
			tactileDotsY = int(graphic.physicalNumRows) * int(graphic.cellHeight)
			# Declare the library as GRAPHICS-ONLY: totalBrailleCellCount=0,
			# lineCount=0 (the vendor's documented "graphics-only device" opt-out;
			# see wrapper.simulateDisplay). We drive the physical braille text strip
			# ourselves through NVDA's normal braille pipeline and discard the
			# library's braille-text channel (renderBrailleBytes is log-and-drop), so
			# declaring a text area only stands up the library's text-translation
			# pipeline for output we never use.
			totalBrailleCellCount = 0
			lineCount = 0
			displayName = str(getattr(self, "_deviceName", "") or "DotPad")
			args = (displayName, tactileDotsX, tactileDotsY, totalBrailleCellCount, lineCount)
			log.debug(f"dotPad: setting up library singleton with args={args}")

			# Rewrite per-locale TactileDisplayAPI.ini files to point at
			# NVDA's bundled liblouis before the library reads its INI during
			# COM construction. Synchronous, idempotent, silent-fallback on
			# read-only installs, no-op on a dev install from a git working
			# copy. The returned per-locale outcome dict is discarded; all
			# logging is internal.
			iniPatcher.patchTactileDisplayAPIIni()

			worker = LibraryWorker()
			worker.start(startTimeoutS=5.0)

			def setupOnWorker():
				tda = TactileDisplayAPI()
				tda._ensureInitialized()  # pyright: ignore[reportPrivateUsage]
				callbacks = TactileDisplayCallbacks(
					renderTactile=_simulatedDisplay.renderTactileBytes,
					renderBraille=_simulatedDisplay.renderBrailleBytes,
				)
				tda.simulateDisplay(*args, callbacks)
				return tda, callbacks

			tda, callbacks = worker.submit(setupOnWorker).result(timeout=10.0)
			self._libraryWorker = worker
			self._tda = tda
			self._callbackServer = callbacks
			self._libraryReady = True
			# The library-unavailable fallback announces at most once per
			# driver lifetime; reset the flag at successful init so a
			# previous driver's announcement state can't carry over.
			self._libraryFallbackAnnounced = False

			# Match the library's braille table to NVDA's currently-active
			# output table. Best-effort — silently skipped
			# when NVDA's table isn't present in NVDA's louis/tables
			# directory. Same fire-and-forget shape as setRegisterEvents
			# below — no main-thread block.
			tableName = _simulatedDisplay.getNVDABrailleTableIfAvailable()
			if tableName is not None:
				worker.submit(_setBrailleTablesOnWorker, tda, tableName)

			# NOTE: RegisterEvents(True) is deliberately NOT enabled here.
			# The library's autonomous UIA subscription is turned on only by
			# LibraryBraillePresentation, AFTER its blocking bootstrap completes
			# (see enableLibraryUiaEvents / disableLibraryUiaEvents). Enabling it
			# at init meant UIA events were live during the bootstrap's blocking
			# ExecuteOperation, which starves the STA pump and heap-corrupts the
			# library (STATUS_HEAP_CORRUPTION crash). Events stay off except
			# during library-driven-braille steady state.

			# Apply the persisted hybrid print+braille setting (default off). Same
			# fire-and-forget shape; the library renders print + braille together on
			# the focused-control area only when this is enabled.
			worker.submit(
				_setHybridModeOnWorker,
				tda,
				configuration.getHybridPrintAndBraille(fromCache=True),
			)

			# Apply the persisted line-spacing setting. Sets inter-line dot gap
			# and six-dot-braille mode on the library's multi-line area.
			_spacingOption = configuration.getMultilineBrailleSpacing(fromCache=True)
			_spacingPadding, _spacingForceSixDot = configuration.LINE_SPACING_PAYLOADS[_spacingOption]
			worker.submit(
				_setLineSpacingOnWorker,
				tda,
				_spacingPadding,
				_spacingForceSixDot,
			)

			# Re-sync the library's on-screen viewer to the persisted
			# ``viewerOnScreen`` config flag. Without this, a user who left
			# the viewer enabled in a prior session (or before a driver swap)
			# would see a checked Tools-menu item but no viewer window until
			# they re-toggle. Fire-and-forget — same shape as the other
			# post-setup submits to avoid blocking the main thread.
			worker.submit(
				_setShowBrailleOnScreenOnWorker,
				tda,
				configuration.getViewerOnScreen(fromCache=True),
			)
			log.debug("dotPad: library singleton ready (SimulateDisplay registered)")
			log.info(f"dotPad: TactileDisplayAPI library {tda.libraryDescription}")
		except Exception:
			log.exception("dotPad: library singleton setup failed; graphic mode disabled")
			# Best-effort: stop the worker if we managed to start it.
			if worker is not None:
				try:
					worker.stop()
				except Exception:
					log.exception("dotPad: worker.stop after setup failure raised; continuing")
			self._libraryWorker = None
			self._tda = None
			self._callbackServer = None
			self._libraryReady = False

	def _teardownLibrarySingleton(self) -> None:
		"""Release the TactileDisplayAPI library singleton.

		Drains in-flight callbacks, stops the worker, drops references.
		Called from ``terminate()`` before the rest of the shutdown
		sequence. Idempotent.
		"""
		if self._callbackServer is not None:
			try:
				self._callbackServer.setShuttingDown()
			except Exception:
				log.exception("dotPad: callbackServer.setShuttingDown raised; continuing")
		if self._libraryWorker is not None:
			try:
				self._libraryWorker.stop()
			except Exception:
				log.exception("dotPad: libraryWorker.stop raised; continuing")
		self._libraryWorker = None
		self._tda = None
		self._callbackServer = None
		self._libraryReady = False

	def enableLibraryUiaEvents(self) -> None:
		"""Turn the library's autonomous UIA subscription ON (RegisterEvents(True)).

		Called by ``LibraryBraillePresentation`` AFTER its blocking bootstrap so
		the bootstrap runs events-off. Fire-and-forget on the worker (FIFO after
		the bootstrap ops). No-op if the library isn't ready.
		"""
		worker = self._libraryWorker
		tda = self._tda
		if worker is None or tda is None or not self._libraryReady:
			return
		worker.submit(_setRegisterEventsOnWorker, tda, worker)

	def disableLibraryUiaEvents(self) -> None:
		"""Turn the library's autonomous UIA subscription OFF (RegisterEvents(False)).

		Called when leaving library-driven-braille mode so later explicit
		blocking calls (graphics pan/zoom, the next bootstrap) run events-off —
		the only state in which a blocking ``ExecuteOperation`` is safe.
		No-op if the library isn't ready.
		"""
		worker = self._libraryWorker
		tda = self._tda
		if worker is None or tda is None or not self._libraryReady:
			return
		worker.submit(_disableRegisterEventsOnWorker, tda, worker)

	def terminate(self):
		# Signalled before anything else so the packet sender stops waiting out full
		# render budgets: this method runs on the main thread when NVDA switches
		# displays, and NVDA's watchdog reports a freeze after 25 seconds.
		self._terminationStarted.set()
		# Release the TactileDisplayAPI library singleton. Drains any
		# in-flight callback, stops the worker, drops COM pointer references.
		self._teardownLibrarySingleton()

		# Step 1: Block any new content from being queued
		self._blockNewWrites.set()

		# Step 2: Unregister event handlers (stops content generation)
		if self._renderer:
			self._renderer.terminate()
			self._renderer = None

		# Step 3: Drain existing queue (discard pending content - we're clearing anyway)
		while not self._queuedPackets.empty():
			try:
				self._queuedPackets.get_nowait()
				self._queuedPackets.task_done()
			except Empty:
				break

		# Step 4: Clear displays (bypasses the write block).
		#
		# Skipped over BLE: the display clears itself when it notices the link has gone,
		# and the disconnect scheduled in close() is about to cause exactly that. Doing
		# it ourselves means one packet per external row, each waited on up to
		# TERMINATE_ACK_TIMEOUT_SECONDS -- the bulk of the pause when switching displays,
		# on NVDA's main thread. It is kept for serial, where the device cannot tell the
		# host has closed the port while the cable is still in, so nothing else clears
		# it. Note this relies on firmware behaviour the protocol specification does not
		# describe; if a display is ever found holding stale content after disconnect,
		# this is why.
		if self._isBleConnection:
			log.debug("dotPad: BLE, leaving the clear to the display's own disconnect handling")
		else:
			self._clearDisplaysForTermination()

		# Step 5: Wait for the clear packets to be sent, but never unconditionally.
		# Queue.join() has no timeout, and the sender may be waiting on a display that
		# has stopped responding -- which froze NVDA's main thread for the whole
		# escalation budget.
		if not self._waitForQueueDrain(TERMINATE_DRAIN_TIMEOUT_SECONDS):
			log.debugWarning(
				f"dotPad: clear packets not flushed within {TERMINATE_DRAIN_TIMEOUT_SECONDS}s; "
				"terminating anyway",
			)

		# Step 6: Signal sender thread to exit and wait -- bounded, like step 5. The
		# sender normally notices _isTerminating within CONNECTION_POLL_SECONDS, but it
		# can also be inside self._dev.write(), which has no timeout of its own: on BLE
		# that is a hand-off to the asyncio loop, and a peripheral that has gone away can
		# stall it. Joining unconditionally would freeze the main thread there -- the
		# very freeze step 5 was bounded to avoid. The thread is a daemon and stops
		# touching the display once _isTerminating is set, so proceeding is safe.
		self._isTerminating.set()
		self._queuedPacketsSenderThread.join(TERMINATE_JOIN_TIMEOUT_SECONDS)
		if self._queuedPacketsSenderThread.is_alive():
			log.debugWarning(
				f"dotPad: packet sender did not exit within {TERMINATE_JOIN_TIMEOUT_SECONDS}s; "
				"terminating anyway",
			)

		# Step 7: Clean up display references
		if self.textDisplay:
			self.textDisplay = None
		if self.graphicDisplay:
			self.graphicDisplay = None
		try:
			super().terminate()
		finally:
			self._dev.close()

	def _queuedPacketsSender(self):
		while not self._isTerminating.is_set():
			try:
				prioritizedPacket = self._queuedPackets.get(timeout=0.1)
			except Empty:
				# Handle queued external rows
				if self.textDisplay and self.textDisplay.awaitingAck:
					self.textDisplay._writeQueuedExternalRows()  # type: ignore
				if self.graphicDisplay and self.graphicDisplay.awaitingAck:
					self.graphicDisplay._writeQueuedExternalRows()  # type: ignore

				# Check for idle refresh opportunities when queue is empty
				self._checkIdleRefresh()
				continue

			try:
				self._sendQueuedPacket(prioritizedPacket)
			except Exception:
				# The sender thread must never die: terminate() joins the packet queue
				# before signalling this thread, so an unconsumed queue is a hang. This
				# is a backstop for unexpected faults only -- it deliberately does not
				# release the display, since a one-off bookkeeping error is no evidence
				# the transport has gone. Write failures are handled where they happen.
				log.exception("dotPad: unexpected error while sending a packet; continuing")
			finally:
				self._queuedPackets.task_done()

	def _sendQueuedPacket(self, prioritizedPacket: PrioritizedPacket) -> None:
		"""Send one queued packet. The caller owns ``task_done()`` for it."""
		packet = prioritizedPacket.packet

		if self._displayGone:
			# Nothing to send to; drain so terminate() is never blocked by the queue.
			return

		if packet.packetType == PacketType.REQ_DISPLAY_LINE:
			try:
				row = self.getExternalRow(packet.destination)
			except ValueError:
				row = None
			if row:
				display = self.getDisplayForExternalRow(packet.destination)
				isRefresh = prioritizedPacket.priority >= AUTO_REFRESH_PRIORITY
				timestamp = prioritizedPacket.timestamp

				# Prepare the conditions
				hasBeenRefreshedSince = row.lastRefreshed and row.lastRefreshed > timestamp
				hasBeenWrittenSince = row.lastWritten and row.lastWritten > timestamp

				# Check if the packet should be skipped
				if (isRefresh and display.autoRefresh and hasBeenRefreshedSince) or hasBeenWrittenSince:
					# Drop this packet and send the next packet
					return

				# Update lastRefreshed and increment refresh count if applicable
				if isRefresh:
					row.lastRefreshed = timestamp
					row.refreshCount += 1
				else:
					# Reset refresh count and attempt time when new content is written
					row.refreshCount = 0
					row.lastRefreshAttempt = None

		# Track whether this is a refresh packet for timing updates on ACK
		if packet.packetType == PacketType.REQ_DISPLAY_LINE:
			try:
				self._lastSentWasRefresh = prioritizedPacket.priority >= AUTO_REFRESH_PRIORITY
			except (ValueError, AttributeError):
				self._lastSentWasRefresh = False
		else:
			self._lastSentWasRefresh = False

		# Wait until the previous packet has been acknowledged.
		if not self._waitForSendSlot():
			if self._isTerminating.is_set() or self._terminationStarted.is_set():
				# On the way out the wait uses TERMINATE_ACK_TIMEOUT_SECONDS, which is
				# shorter than a single normal full-area render. Expiring there says
				# nothing about the display, so do not latch _displayGone: that would
				# discard every remaining clear packet -- typically the graphic one,
				# behind the text one -- on perfectly healthy hardware. The drain is
				# already bounded by TERMINATE_DRAIN_TIMEOUT_SECONDS.
				return
			# The display is gone. Keep this thread alive and draining rather than
			# exiting: terminate() joins the packet queue *before* signalling this
			# thread, so leaving packets unconsumed would just move the hang.
			self._displayGone = True
			return

		# Send the packet. Any failure here means the display is unreachable: a
		# serial cable pulled out raises OSError, and BLE raises once the peripheral
		# is gone. Without this the exception escaped the sender thread entirely,
		# killing it and stranding the queue that terminate() joins.
		# Cleared before the write, not after: the reader thread can deliver
		# NTF_DISPLAY_LINE while the write is still in flight (on BLE the write is a
		# cross-thread hand-off), and clearing afterwards would discard that.
		self._readyToSend.clear()
		try:
			self._dev.write(packet)
		except Exception:
			log.exception("dotPad: writing to the display failed; releasing it")
			self._readyToSend.set()
			self._reportDisplayUnavailable()
			self._displayGone = True
			return
		self._lastSentPacket = packet
		self._lastSentPacketNumTries = 0

	def _initSendState(self) -> None:
		"""Initialise everything the packet-sender thread reads.

		Kept together, and called before that thread is started, because the thread
		touches all of it immediately: a field missed here surfaces as an
		``AttributeError`` inside the sender rather than at construction. Unit tests
		build their driver through this same method so a fixture cannot drift from
		what ``__init__`` actually sets.
		"""
		self._readyToSend = threading.Event()
		self._readyToSend.set()
		self._displayGone = False
		self._consecutiveRenderTimeouts = 0
		# Set for real once a port is chosen; defaulted here because the sender thread
		# reads it through _isDeviceConnected() and starts before the port loop.
		self._isBleConnection = False
		self._terminationStarted = threading.Event()
		self._lastSentPacket = None
		self._lastSentPacketNumTries = 0
		self._lastSentWasRefresh = False

	def _clearDisplaysForTermination(self) -> None:
		"""Queue clear packets for whichever displays exist."""
		try:
			if self.textDisplay:
				self.textDisplay.clearForTermination()
		except AttributeError:
			pass
		try:
			if self.graphicDisplay:
				self.graphicDisplay.clearForTermination()
		except AttributeError:
			pass

	def _waitForQueueDrain(self, timeout: float) -> bool:
		"""``Queue.join()`` with a deadline. Returns ``False`` if it expired.

		Mirrors what ``join()`` does internally -- wait on ``all_tasks_done`` until
		``unfinished_tasks`` reaches zero -- but bounded, because the stdlib offers no
		timeout and blocking here freezes NVDA.
		"""
		deadline = time.monotonic() + timeout
		with self._queuedPackets.all_tasks_done:
			while self._queuedPackets.unfinished_tasks:
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					return False
				self._queuedPackets.all_tasks_done.wait(remaining)
		return True

	def _getRenderTimeout(self) -> float:
		"""How long a line may take to physically render before something is wrong.

		Derived from the device's own reported refresh time rather than
		:attr:`timeout`, which is the protocol acknowledgement budget NVDA core uses.
		The two are very different: the send gate opens on ``NTF_DISPLAY_LINE``, which
		the display sends once the pins have actually moved, not on ``RSP_DISPLAY_LINE``.
		"""
		info = self._boardInformation
		if info is None:
			return DEFAULT_RENDER_TIMEOUT_SECONDS
		refreshTime = max(info.text.refreshTime, info.graphic.refreshTime)
		if not refreshTime:
			return DEFAULT_RENDER_TIMEOUT_SECONDS
		return refreshTime * REFRESH_TIME_UNIT_SECONDS * RENDER_TIMEOUT_FACTOR

	def _waitForSendSlot(self) -> bool:
		"""Block until the display reports the previous line has rendered.

		Returns ``False`` when the caller should stop sending -- the driver is
		terminating, or the display has been given up on.

		Two independent budgets, because they answer different questions. The link is
		checked every :data:`CONNECTION_POLL_SECONDS`, so a disconnect is noticed
		quickly; the render budget from :meth:`_getRenderTimeout` is much longer,
		because tactile actuation genuinely takes seconds and treating that as a fault
		would resend lines the display had already accepted.

		If the render budget expires while the link still looks up, the packet is
		retried; after :data:`MAX_CONSECUTIVE_RENDER_TIMEOUTS` of those the display is
		given up on regardless. That last step is what catches a device switched off
		while its USB serial interface stays enumerated -- writes keep succeeding, so
		nothing else ever reports a fault.
		"""
		terminating = self._terminationStarted.is_set()
		renderTimeout = TERMINATE_ACK_TIMEOUT_SECONDS if terminating else self._getRenderTimeout()
		deadline = time.monotonic() + renderTimeout
		while not self._isTerminating.is_set():
			if self._readyToSend.wait(min(CONNECTION_POLL_SECONDS, renderTimeout)):
				return True
			if terminating and time.monotonic() >= deadline:
				# On the way out the clear packet is best-effort; do not wait, retry or
				# report the display unavailable while NVDA is switching displays.
				return False
			if not self._isDeviceConnected():
				log.warning("dotPad: no response and the display is disconnected; releasing it")
				self._reportDisplayUnavailable()
				return False
			if time.monotonic() < deadline:
				continue
			self._consecutiveRenderTimeouts += 1
			if self._consecutiveRenderTimeouts >= MAX_CONSECUTIVE_RENDER_TIMEOUTS:
				log.warning(
					f"dotPad: no response after {self._consecutiveRenderTimeouts} render timeouts; "
					"releasing the display",
				)
				self._reportDisplayUnavailable()
				return False
			log.debugWarning(
				f"dotPad: line did not render within {renderTimeout:.1f}s, retrying last packet",
			)
			self._resendLastPacket()
			deadline = time.monotonic() + renderTimeout
		return False

	def _isDeviceConnected(self) -> bool:
		"""Whether the transport still reports a live connection.

		Only BLE can answer this. ``hwIo.Serial`` has no equivalent -- a powered-off
		device keeps its USB interface enumerated -- so serial is assumed connected and
		recovery falls back to the resend/give-up path in ``_waitForSendSlot``.
		"""
		if not self._isBleConnection:
			return True
		try:
			# _isBleConnection is the narrowing pyright cannot see: only the BLE
			# transport is ever assigned when it is True.
			return bool(cast("Ble", self._dev).isConnected())
		except Exception:
			log.debugWarning("dotPad: could not query connection state", exc_info=True)
			return False

	def _reportDisplayUnavailable(self) -> None:
		"""Ask NVDA to drop this display, from the main thread.

		``handleDisplayUnavailable()`` terminates the driver, and termination joins the
		packet-sender thread -- so calling it directly from that thread would deadlock.

		Nothing is reported once termination has begun: NVDA is already tearing this
		driver down, so there is nothing left to release. Checked here rather than in
		the callback because NVDA re-initialises the *same* driver object when the
		display it reconnects to is of the same class (``braille._switchDisplay``), so
		by the time the callback runs ``handler.display is self`` can be true again --
		of a display that has just come back. Checked here rather than at the call
		sites because a wait that began before ``terminate()`` still polls the link
		while the queue drains, and that poll is a call site too.
		"""
		if braille.handler is None:
			return
		if self._terminationStarted.is_set():
			log.debug("dotPad: display unavailable while terminating; nothing to release")
			return

		def releaseIfStillCurrent() -> None:
			# By the time this runs NVDA may have moved on -- __init__ can raise and
			# fall back to the user's previous display, or they may have switched
			# manually. Tearing that one down would leave them with no braille at all.
			handler = braille.handler
			if handler is not None and handler.display is self:
				handler.handleDisplayUnavailable()

		core.callLater(0, releaseIfStillCurrent)

	def _onReceive(self, data: bytes):
		packet: Packet = Packet(data)
		while packet.bytesExpected > 0:
			packet = Packet(packet + self._dev.read(packet.bytesExpected))
		if not packet.isComplete:
			log.debugWarning(f"Incomplete packet received: {packet!r}, ignoring")
			return
		if not packet.isValid:
			log.debugWarning(f"Invalid packet received: {packet!r}, ignoring")
			return
		self._handleResponse(packet)

	def _handleResponse(self, packet: Packet):
		# Anything arriving from the display means it is still responding.
		self._consecutiveRenderTimeouts = 0
		if packet.packetType == PacketType.RSP_BOARD_INFORMATION:
			try:
				textDisplayDescriptor = DisplayDescriptor.fromBytes(*packet.args[4:8])
			except IndexError:
				textDisplayDescriptor = DisplayDescriptor(0, 0, False, 0)
			try:
				graphicDisplayDescriptor = DisplayDescriptor.fromBytes(*packet.args[8:12])
			except IndexError:
				graphicDisplayDescriptor = DisplayDescriptor(0, 0, False, 0)
			self._boardInformation = info = BoardInformation(
				features=packet.args[0],
				dotsPerCell=packet.args[1],
				distanceBetweenPins=packet.args[2],
				functionKeyCount=packet.args[3],
				text=textDisplayDescriptor,
				graphic=graphicDisplayDescriptor,
			)
			log.debug(f"Board information: {info}")
			self._boardInformation = info
			if textDisplayDescriptor.columnCount > 0:
				if self.supportsHardwareBasedAutoRefresh:
					textAutoRefresh = False
				else:
					textAutoRefresh = bool(configuration.getAutoRefresh() & configuration.AutoRefresh.TEXT)
				self.textDisplay = self._createDisplay(
					textDisplayDescriptor,
					autoRefresh=textAutoRefresh,
				)
				self.primaryDisplay = self.textDisplay
				self.numCols = self.textDisplay.numCols
				self.numRows = self.textDisplay.numRows
			if graphicDisplayDescriptor.columnCount > 0:
				if self.supportsHardwareBasedAutoRefresh:
					graphicAutoRefresh = False
				else:
					graphicAutoRefresh = bool(
						configuration.getAutoRefresh() & configuration.AutoRefresh.GRAPHIC,
					)
				_lineSpacingOption = configuration.getMultilineBrailleSpacing(fromCache=True)
				_paddingDots, _ = configuration.LINE_SPACING_PAYLOADS[_lineSpacingOption]
				self.graphicDisplay = self._createDisplay(
					graphicDisplayDescriptor,
					supportsGraphic=True,
					startDestination=1,
					horizontalCellSpacing=1,
					verticalCellSpacing=_paddingDots,
					autoRefresh=graphicAutoRefresh,
				)

				# Late import to avoid circular dependency
				if TYPE_CHECKING or IS_UNDER_UNITTEST:
					from ...presentations import PresentationRenderer
				else:
					PresentationRenderer = addon.loadModule("presentations.renderer").PresentationRenderer

				self._renderer = PresentationRenderer(self.graphicDisplay)
		elif packet.packetType == PacketType.RSP_FIRMWARE_VERSION:
			self._firmwareVersion = packet.args.decode("ascii")
			log.debug(f"Firmware version: {self._firmwareVersion}")
		elif packet.packetType == PacketType.RSP_DEVICE_NAME:
			self._deviceName = packet.args.decode("ascii")
			log.debug(f"Device name: {self._deviceName}")
			if self.supportsHardwareBasedAutoRefresh:
				log.debug(f"D3 hardware detected ({self._deviceName}), software auto-refresh disabled")
		elif packet.packetType == PacketType.NTF_DISPLAY_LINE:
			# TODO: This is an ACK for a command, but not handle it using NVDA's
			# ACK handling, since this triggers the writing of any queued braille cells
			# We might implement our own ACK handling for this in the future
			# Update lastRefreshAttempt on completion for refresh packets
			# This ensures the refresh interval is measured from ACK time, not queue time
			if self._lastSentWasRefresh:
				try:
					row = self.getExternalRow(packet.destination)
					row.lastRefreshAttempt = time.time()
				except ValueError:
					pass
			self._readyToSend.set()
		elif packet.packetType == PacketType.RSP_DISPLAY_LINE:
			try:
				responseCode = ResponseCode.fromCode(packet.args[0])
			except ValueError:
				log.debugWarning(
					f"Unknown response code while handling ACK/NAK response: {packet.args[0]}, assuming NAK",
				)
				responseCode = ResponseCode.NAK
			if responseCode.isAck:
				self._handleAck(destination=packet.destination)
			elif responseCode.isNak:
				log.debugWarning(f"Received NAK response: {responseCode}")
				# A line was unable to display, rely on _sendQueuedPackets
				# from the Display class to resend it if needed
				# Send the next packet in the queue if any
			# Return early to prevent new packets from being sent since we are waiting on a NTF_DISPLAY_LINE
			return
		elif packet.packetType and packet.packetType.code[0] == PacketType.NTF_KEYS_SCROLL.code[0]:
			self._handleKeyPress(packet.packetType.code[1], packet.args)
		elif packet.packetType == PacketType.NTF_ERROR:
			log.warning(f"Received error: {packet.args!r}")
		else:
			log.debugWarning(f"Received unhandled command: {packet.packetType!r} {packet.args!r}")
		self._readyToSend.set()

	def _handleAck(self, destination: int):  # type: ignore
		minDestination: int = 0
		maxDestination: int = 0
		hasTextDisplay = False
		hasGraphicDisplay = False
		display: Display | None = None
		if self.textDisplay:
			hasTextDisplay = True
			display = self.textDisplay
		if self.graphicDisplay:
			hasGraphicDisplay = True
			display = self.graphicDisplay

		if hasTextDisplay:
			minDestination = cast(Display, self.textDisplay).startDestination
			if not hasGraphicDisplay:
				maxDestination = (
					cast(Display, self.textDisplay).startDestination
					+ cast(Display, self.textDisplay).physicalNumRows
				)
		if hasGraphicDisplay:
			if not hasTextDisplay:
				minDestination = cast(Display, self.graphicDisplay).startDestination
			maxDestination = (
				cast(Display, self.graphicDisplay).startDestination
				+ cast(Display, self.graphicDisplay).physicalNumRows
			)

		acceptedDestinations: Sequence[int] = range(minDestination, maxDestination)
		if destination not in acceptedDestinations:
			log.debugWarning(
				f"Received ACK for unknown destination: {destination}, valid range is {minDestination}-{maxDestination}",
			)
			return
		offset: int = destination - getattr(display, "startDestination", 0)
		with self._ackLock:
			# The row might not be awaiting an ACK, this means it has changed
			# Ignore the ACK in this case, so the row gets rewritten
			if display and display.externalRows[offset].awaitingAck:
				display.externalRows[offset].awaitingAck = False
				display.externalRows[offset].numTries = 0
			if display and self._renderer and display == self._renderer.display and not display.awaitingAck:
				self._renderer._writeCellsInBackground()  # type: ignore
		if self.primaryDisplay and not self.primaryDisplay.awaitingAck:
			# All rows of the primary display have received an ACK
			# Notify NVDA core that we are ready for new braille cells
			super()._handleAck()

	def _createDisplay(self, descriptor: DisplayDescriptor, **kwargs: int | str | bool) -> Display:
		"""Create a display from a display descriptor"""
		cellHeight: int = 4
		cellWidth: int = 2
		if self._boardInformation and self._boardInformation.dotsPerCell == DP_DPC_6:
			cellHeight = 3

		return Display(
			self,
			descriptor.rowCount,
			descriptor.columnCount,
			cellHeight=cellHeight,
			cellWidth=cellWidth,
			**kwargs,  # type: ignore
		)

	def _handleKeyPress(self, group_num: int, args: bytes):
		"""
		Handle a key press notification from the display.

		The key press data is encoded as a bit string, with each bit
		representing a key in the group. The bit string is split across
		multiple bytes, with each byte containing the bits for 8 keys.

		The bit string is reversed so that keys are ordered from LSB to MSB.
		This maps the keys to the same order as the DP_KEY_* constants
		and thus follows BRLTTY's key numbering scheme for this display.

		After processing the key press, if all keys have been released
		across all groups, an input gesture is generated and sent to NVDA.

		:param group_num: The key group of which keys were pressed.
		:param args: The key presses.
		"""
		try:
			group: KeyGroup = KeyGroup(group_num)
		except ValueError:
			log.debugWarning(f"Unknown key group: {group_num}")
			return

		keysPressedBitString: bytes = b""
		for byte in args:
			bitString: bytes = format(byte, "08b").encode()
			reversedBitString: bytes = bitString[::-1]
			keysPressedBitString = reversedBitString + keysPressedBitString
		keysPressed: int = int(keysPressedBitString, 2)
		if keysPressed:
			# Track first key press time if this is the start of a new gesture
			if not self._keysPressed:
				self._firstKeyPressTime = time.time()
			for i in range(len(args) * 8):
				bit: int = (keysPressed >> i) & 1
				if bit:
					self._keysPressed.add((group, i))
		else:
			# All keys in this group have been released
			self._keyGroupsReleased[group] = True
			if self._keysPressed and all(self._keyGroupsReleased.values()):
				# All key groups are released, generate an input gesture
				# Determine if this is a long press
				isLongPress = False
				if self._firstKeyPressTime is not None:
					elapsedTime = time.time() - self._firstKeyPressTime
					isLongPress = elapsedTime >= LONG_PRESS_THRESHOLD
				try:
					inputCore.manager.executeGesture(InputGesture(self._keysPressed, isLongPress))  # type: ignore
				except inputCore.NoInputGestureAction:
					pass
				self._keysPressed.clear()
				self._firstKeyPressTime = None

	def _sendPacket(
		self,
		packet: Packet,
		num_refreshes: int = 0,
	) -> float:
		"""Queue a packet to be sent to the display.

		:returns: The timestamp when the packet was queued.
		"""
		return self._queuePacket(packet, num_refreshes)

	def _queuePacket(
		self,
		packet: Packet,
		numRefreshes: int = 0,
		_forTermination: bool = False,
	) -> float:
		"""Queue a packet with the given refresh count.

		:param packet: The packet to queue.
		:param numRefreshes: Number of auto-refreshes to perform after this packet.
		:param _forTermination: If True, bypass the write block (used during shutdown).
		:returns: The timestamp when the packet was queued, or 0.0 if blocked.
		"""
		# Block new writes during termination, but allow termination clears through
		if self._blockNewWrites.is_set() and not _forTermination:
			return 0.0
		prioritizedPacket = PrioritizedPacket(packet, priority=packet.destination)
		self._queuedPackets.put(prioritizedPacket)
		if packet.packetType == PacketType.REQ_DISPLAY_LINE:
			# Set max refreshes for new output
			self._maxRefreshes[packet.destination] = numRefreshes
		return prioritizedPacket.timestamp

	def getDisplayForExternalRow(self, destination: int) -> Display:
		"""
		Get the display for the given external row.
		"""
		if self.textDisplay:
			for row in self.textDisplay.externalRows:
				if row.destination == destination:
					return self.textDisplay
		if self.graphicDisplay:
			for row in self.graphicDisplay.externalRows:
				if row.destination == destination:
					return self.graphicDisplay
		raise ValueError(f"No display found for destination: {destination}")

	def getExternalRow(self, destination: int) -> ExternalRowEntry:
		"""
		Get the external row entry for the given destination.
		"""
		display = self.getDisplayForExternalRow(destination)
		rows = display.externalRows
		for row in rows:
			if row.destination == destination:
				return row
		raise ValueError(f"No external row found for destination: {destination}")

	def _resendLastPacket(self):
		packet = self._lastSentPacket
		if packet:
			if not self._lastSentPacketNumTries < 3:
				# Give up on the packet
				log.debugWarning(
					f"Giving up on packet: {packet}, number of tries: {self._lastSentPacketNumTries}",
				)
				self._lastSentPacket = None
				self._lastSentPacketNumTries = 0
				self._readyToSend.set()
				return
			log.debug(f"Resending last packet: {packet}")
			self._queuePacket(packet)
			self._lastSentPacketNumTries += 1

	def _checkIdleRefresh(self):
		"""Check for idle destinations and trigger refresh if needed."""
		try:
			# Get the current idle timeout from configuration
			idleTimeout = configuration.getAutoRefreshIdleTimeout()
			currentTime = time.time()

			# Check each display for rows that need refreshing
			for display in [self.textDisplay, self.graphicDisplay]:
				if not display or not display.autoRefresh:
					continue

				for row in display.externalRows:
					destination = row.destination

					# Check if this destination has idle timeout and max refresh settings
					if destination not in self._maxRefreshes:
						continue

					maxRefreshes = self._maxRefreshes[destination]
					if maxRefreshes == 0:
						# No auto-refresh requested for this destination
						continue

					# Check if enough time has passed since last write
					if not row.lastWritten or currentTime - row.lastWritten < idleTimeout:
						continue

					# Use the actual refresh count tracked in the row
					if row.refreshCount >= maxRefreshes:
						# Already sent maximum number of refreshes, stop refreshing
						continue

					# Check refresh interval (time between refreshes)
					refreshInterval = configuration.getAutoRefreshInterval()
					if row.lastRefreshAttempt and currentTime - row.lastRefreshAttempt < refreshInterval:
						# Too soon for next refresh
						continue

					# Send only ONE refresh packet per cycle to respect interval timing
					try:
						# Recreate the display line packet for refresh
						cells = row._cells[row.start : row.end]  # type: ignore
						refreshPacket = Packet.makePacket(
							packetType=PacketType.REQ_DISPLAY_LINE,
							destination=destination,
							args=bytes([0] + cells),
						)

						# Queue only one refresh packet
						# Set lastRefreshAttempt now to prevent re-queuing before ACK
						# It will be updated to actual completion time on ACK in _handleResponse
						row.lastRefreshAttempt = currentTime
						if not self._isTerminating.is_set():
							self._queuedPackets.put(
								PrioritizedPacket(
									refreshPacket,
									priority=AUTO_REFRESH_PRIORITY + destination,
								),
							)
					except (ValueError, AttributeError):
						# Row access error, skip this row
						continue
		except Exception:
			# Continue operation even if there's an error in idle refresh checking
			pass

	def _get_numCells(self) -> int:
		"""Obtain the number of braille cells on this display.
		@note: 0 indicates that braille should be disabled.
		@note: For multi line displays, this is the total number of cells
		       (e.g. numRows * numCols)
		@return: The number of cells.
		"""
		return self.numRows * self.numCols

	def _get_numCols(self):
		return 0

	def _get_numRows(self):
		return 1

	def _get_timeout(self) -> float:
		"""Make timeout dynamic based on number of rows of the primary braille display.
		The timeout is used for ACK handling in NVDA core.
		"""
		initial_timeout: float = 0.1
		multiplier = self.numRows * 1.5
		return initial_timeout * multiplier

	def _get__awaitingAck(self) -> bool:
		result: bool = False
		with self._ackLock:
			if self.primaryDisplay:
				result = self.primaryDisplay.awaitingAck
		return result

	def _set__awaitingAck(self, value: bool):
		if value:
			return
		if self.primaryDisplay:
			self.primaryDisplay.awaitingAck = value

	def _get_supportsHardwareBasedAutoRefresh(self) -> bool:
		"""Check if connected device has hardware-based auto-refresh.

		D3-based devices (e.g., DotPad 320X) handle auto-refresh in hardware,
		so software-based auto-refresh should be disabled.

		:returns: True if device supports hardware auto-refresh, False otherwise.
		"""
		if not hasattr(self, "_deviceName") or not self._deviceName:
			return False
		return self._deviceName in D3_DEVICE_NAMES

	def display(self, cells: list[int]):
		if not self.primaryDisplay:
			return
		self.primaryDisplay.displayBraille(cells)

	def getScript(self, gesture: inputCore.InputGesture):  # pyright: ignore[reportUnknownParameterType]
		"""Delegate gesture lookup to the active presentation first.

		NVDA's gesture dispatcher yields ``braille.handler.display`` via
		``scriptHandler._yieldObjectsForFindScript`` and calls ``getScript``
		on it. Without this override the driver would be the only object
		consulted for braille gestures — presentations have no other way to
		participate. The override asks the active presentation first; if it
		returns a script the presentation wins, otherwise we fall through to
		``ScriptableObject.getScript`` to resolve the driver's own bindings.

		Return type matches ``ScriptableObject.getScript`` exactly — NVDA's
		base class itself is untyped at the return site, so we propagate
		that shape with a ``# pyright: ignore`` rather than invent a more
		specific signature that wouldn't match the base.
		"""
		renderer = self._renderer
		if renderer is not None:
			activePresentation = renderer.presentationManager.activePresentation
			if activePresentation is not None:
				script = activePresentation.getScript(gesture)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
				if script is not None:
					return script  # pyright: ignore[reportUnknownVariableType]
		return super().getScript(gesture)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

	@script(
		description=_(
			# Translators: description of the refresh
			# command for the multiline/graphical display.
			# No default gesture — the user can assign one via NVDA's Input
			# Gestures dialog.
			"Refreshes the Dot Pad display",
		),
		category=SCRCAT_BRAILLE,
	)
	def script_refresh(self, _gesture: inputCore.InputGesture):
		if self.textDisplay:
			self.textDisplay.refresh()
		if self.graphicDisplay:
			self.graphicDisplay.refresh()

	@script(
		description=_(
			# Translators: description of the scroll backwards
			# command for the multiline/graphical display
			"Scrolls the multiline display backwards",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1",
	)
	def script_multilineBack(self, _gesture: inputCore.InputGesture):
		if not self._renderer:
			return
		# TODO: Replace logic when we support multiple views properly
		self._renderer.scrollBack()

	@script(
		description=_(
			# Translators: description of the scroll forward command
			# for the multiline/graphical display
			"Scrolls the multiline display forward",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f4",
	)
	def script_multilineForward(self, _gesture: inputCore.InputGesture):
		if not self._renderer:
			return
		# TODO: Replace logic when we support multiple views properly
		self._renderer.scrollForward()

	@script(
		description=_(
			# Translators: description of the toggle screen capture mode command
			# for the DotPad braille display
			"Toggles between normal braille output and screen capture mode",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f1+f3)",
	)
	def script_toggleScreenCapture(self, _gesture: inputCore.InputGesture):
		if self._renderer:
			isActive = self._renderer.toggleScreenCaptureMode()
			if isActive:
				# Translators: Message announced when screen capture mode is enabled
				ui.message(_("Screen capture mode"))
			else:
				# Translators: Message announced when screen capture mode is disabled
				ui.message(_("Normal mode"))

	@script(
		description=_(
			# Translators: description of the force table mode command
			# for the DotPad braille display
			"Forces table mode by scanning parent objects for a table",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):longPress(f2+f3)",
	)
	def script_forceTableMode(self, _gesture: inputCore.InputGesture):
		import api

		if not self._renderer:
			return

		# Check if already in table mode - do nothing if so
		presentationManager = self._renderer.presentationManager
		activePresentation = presentationManager.activePresentation
		if activePresentation and activePresentation.name == "table":
			return

		# Get navigator object and try to force table mode
		navObj = api.getNavigatorObject()
		success = presentationManager.forcePresentation("table", navObj)

		if success:
			# Trigger render to display the new presentation immediately
			self._renderer.onReviewMove()
			# Translators: Message announced when table mode is activated
			ui.message(_("Table mode"))
		else:
			# Translators: Message announced when no table is found in parent objects
			ui.message(_("No table found"))

	@script(
		description=_(
			# Translators: description of the graphic display command
			# for the DotPad braille display
			"Displays the review object as tactile graphics via TactileDisplayAPI",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f2+f4",
	)
	def script_graphicDisplay(self, _gesture: inputCore.InputGesture):
		"""Force tactile-graphics rendering of the current navigator object.

		Asks the renderer's PresentationManager to force the "graphic"
		presentation on the navigator object. The next coreCycle's
		``GraphicPresentation.render()`` submits drawScreenRegion + show on
		the driver's worker. Works for non-Role.GRAPHIC objects too (via
		``GraphicProvider.forceForObject``).
		"""
		import api

		navObj = api.getNavigatorObject()
		if self._renderer is None:
			return
		self._renderer.presentationManager.forcePresentation("graphic", navObj)
		self._renderer._needsRender = True  # pyright: ignore[reportPrivateUsage]

	@script(
		description=_(
			# Translators: description of the braille display command
			# for the DotPad braille display — symmetric to the tactile-graphic
			# force chord; "show as braille" on the navigator object.
			"Displays the review object as braille via the active braille presentation",
		),
		category=SCRCAT_BRAILLE,
		gesture="br(dotPad):f1+f3",
	)
	def script_brailleDisplay(self, _gesture: inputCore.InputGesture):
		"""Force braille rendering of the current navigator object.

		The symmetric mirror of ``script_graphicDisplay``. Asks the renderer's
		PresentationManager to force the "braille" presentation on the
		navigator object. ``BrailleProvider._doCreatePresentation`` reads the
		``[dotPad] brailleSource`` config and selects ``BraillePresentation``
		(NVDA-cursor-driven) or ``LibraryBraillePresentation`` (library-driven)
		accordingly — this script doesn't read the config itself.
		"""
		import api

		navObj = api.getNavigatorObject()
		if self._renderer is None:
			return
		self._renderer.presentationManager.forcePresentation("braille", navObj)
		self._renderer._needsRender = True  # pyright: ignore[reportPrivateUsage]

	gestureMap = inputCore.GlobalGestureMap(
		{
			"globalCommands.GlobalCommands": {
				"braille_scrollBack": "br(dotPad):panLeft",
				"braille_scrollForward": "br(dotPad):panRight",
				"review_activate": "br(dotPad):f3",
			},
		},
	)


class InputGesture(braille.BrailleDisplayGesture):
	source = BrailleDisplayDriver.name

	def __init__(self, keys: list[tuple[int, int]], isLongPress: bool = False):
		super().__init__()
		self.keys = keys
		self.isLongPress = isLongPress
		self.keyNames = names = []
		for group, key in keys:
			# TODO: Handle routing and panning groups
			if group == KeyGroup.FUNCTION:
				names.append(f"f{key + 1}")
			elif group == KeyGroup.PERKINS:
				# TODO: handle braille input
				try:
					names.append(PerkinsKey(key).name)
				except ValueError:
					log.debugWarning(f"Unknown Perkins key: {key}")
		baseId = "+".join(names)
		self.id = self._formatLongPressId(baseId) if isLongPress else baseId

	def _formatLongPressId(self, baseId: str) -> str:
		"""Format a long press gesture ID. Centralized for easy modification."""
		return f"longPress({baseId})"
