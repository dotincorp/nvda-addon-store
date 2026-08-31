# Minimal braille.py shape for testing extract_nvda_labels.
# Mirrors the structure of nvda/source/braille.py without the rest of NVDA.

import typing

import controlTypes  # noqa: F401  (referenced in keys as controlTypes.Role.* / controlTypes.State.*)


roleLabels: typing.Dict[controlTypes.Role, str] = {
	controlTypes.Role.BUTTON: _("btn"),
	controlTypes.Role.CHECKBOX: _("chk"),
	controlTypes.Role.RADIOBUTTON: _("rbtn"),
	controlTypes.Role.SLIDER: _("sldr"),  # Library doesn't map slider — should be preserved.
	controlTypes.Role.SEPARATOR: "⠤⠤⠤⠤⠤",  # Non-translatable; emitted verbatim.
}

positiveStateLabels = {
	controlTypes.State.SELECTED: _("sel"),
	controlTypes.State.CHECKED: "⣏⣿⣹",  # Non-translatable Unicode braille.
	controlTypes.State.PRESSED: "⢎⣿⡱",
	controlTypes.State.HALFCHECKED: "⣏⣸⣹",
	controlTypes.State.READONLY: _("ro"),
	controlTypes.State.EXPANDED: _("-"),
	controlTypes.State.COLLAPSED: _("+"),
}

negativeStateLabels = {
	controlTypes.State.CHECKED: "⣏⣀⣹",
}
