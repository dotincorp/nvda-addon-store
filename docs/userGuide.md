# NVDA Dot Pad Add-on Guide

## Summary

The NVDA add-on for Dot Pad is the means by which we get NVDA to optimally display braille and tactile graphics on the Dot Pad. You need to install the add-on: without it, NVDA won't be able to take advantage of the Dot Pad's multiline and tactile graphics capabilities.

Traditionally, screen readers would send a single line of text to the braille display. Panning the display would reposition the display to show parts of that line (since a display typically shows far fewer characters than a visual line on a computer screen), and then move the cursor to the next or prior line in the document and show the next display's worth of text. In the multiline braille display world, it is not enough just to send a line of text to the display and have it wrapped across the multiple lines of the display, potentially leaving the rest of the display empty. Rather, the screen reader must retrieve as many paragraphs of text as will fit on the display. It must then ensure that when panning the display, the cursor is moved such that subsequent text retrieval results in the reading experience being continuous, like reading a book, whether panning forward or backward through the text. This must happen regardless of whether braille is shown using the computer braille code, which has a one-for-one correspondence with print characters, or whether the user has elected to display contracted braille, where one symbol may represent multiple print characters. In either case, what corresponds to a line of text on a braille display will almost never correspond to the same onscreen print line. This problem is exacerbated in the multiline braille context. The add-on handles the text retrieval, formatting, translation and panning such that the user experience is optimal when reading on the Dot Pad with NVDA.

The add-on also allows letters, emoji and graphics to be rendered as tactile images on the Dot Pad in a way which makes sense to the braille reader. Tactile graphics may be enlarged, reduced and inverted for ease of comprehension. Math equations in Microsoft Word and charts in Excel are also automatically converted to an appropriate tactile image. Axes, tick marks and labels will be properly generated, and where necessary, translated and formatted.

The add-on also provides other modes to assist with learning braille. It allows the number of lines of multiline braille to be configured from double spaced (5 lines), to 8 lines of 8-dot braille, to 10 lines of 6-dot braille for an optimal reading experience. There is also a hybrid print and braille mode for those learning print or braille, such that a word is shown in braille as well as tactile print letters as the user navigates through a document.

Finally, the add-on provides an onscreen braille visualizer for teachers and trainers to see a representation of what is being sent to the Dot Pad.

## Dot Pad Overview

Dot Pad is a tactile information display capable of rendering braille text and tactile graphics simultaneously. You should orient Dot Pad with the body inclined downward toward you.

### Displays

- Braille Reading line closest to you, consisting of 20 braille cells arranged in a horizontal frame for text output.
- Graphic Display Area (Multiline): The largest area on the front, consisting of 300 8-dot braille cells densely packed for precise tactile graphics and multiline braille.

### Navigation Buttons

You will find six buttons between the two displays, arranged from left to right:

- Pan Left (Triangular shape)
- F1 Function Key (Oval shape with tactile indicator)
- F2 Function Key (Oval shape)
- F3 Function Key (Oval shape)
- F4 Function Key (Oval shape with tactile indicator)
- Pan Right (Triangular shape)

Note that the tactile markings are only present on the newer Dot Pad X hardware, not on the Dot Pad 320A.

### Ports and Switches

- Left Side (Data Connection): Features a USB-C port labeled on Dot Pad X with the braille letter "d". This port is dedicated solely to data connections with screen readers and firmware updates, and does not support charging. Connect your USB cable here to communicate with NVDA.
- Right Side (Charging Only): Features a USB-C port labeled on Dot Pad X with the braille letter "p", dedicated solely to power and charging. You can find the power switch toward you.

## Connecting Dot Pad to NVDA

You can connect Dot Pad to NVDA either wirelessly via Bluetooth Low Energy (BLE) or using a wired USB-C connection. With the NVDA Dot Pad add-on installed, follow these steps.

### Automatic Connection

During the installation of the Dot Pad add-on it asks you to enable automatic detection of the Dot Pad display. If you answered "Yes" to this and have restarted NVDA to finish the installation, the Dot Pad should be connected automatically on power on. If the Dot Pad is not automatically detected, follow these steps:

1. Turn off or disconnect any other braille displays that are connected to the computer.
2. Power on the Dot Pad. If you are using the USB-C method, ensure to use the data port on the left.
3. Press NVDA+control+a to open the braille display selection dialog.
4. Ensure "Automatic" is selected. This should be the first option in the list.
5. Press tab to go to the "Displays to detect automatically" list.
6. Ensure Dot Pad is checked in this list. If it is not, use the space bar to toggle the checkbox on.
7. Press enter or click the "OK" button to confirm.

From now on any Dot Pad connected over USB or in Bluetooth range will automatically connect. Unfortunately, it is not possible to enable automatic detection only for USB or Bluetooth. If you need to pin the Bluetooth connection to a specific display in an environment where multiple Dot Pads are present, follow the manual connection steps below.

If the automatic detection is used, the display switches automatically between USB and Bluetooth. NVDA should switch in a few seconds after plugging the USB-C cable into the left port of the Dot Pad, and the Dot Pad will vibrate to confirm the Bluetooth connection is disconnected. Conversely, after unplugging the USB cable, NVDA will start searching for devices and pick up the Dot Pad over Bluetooth in a few seconds.

### Manual Connection

1. Power on Dot Pad. If you are using the USB-C method, connect Dot Pad using the data port on the lefthand side. If you are connecting via Bluetooth, make a note of the last four digits of your Dot Pad Bluetooth name that are displayed once Dot Pad is powered on.
2. Open NVDA's braille display selection dialog by pressing NVDA+control+a.
3. Select Dot Pad from the list of available braille displays.
4. Press the tab key to move to the Port list, and select the appropriate port:
    - For Bluetooth: Select the unique Bluetooth name of your Dot Pad.
    - For USB: Select the appropriate USB port.
5. Press enter or click OK to confirm.

A physical vibration from the Dot Pad will confirm a successful connection, and braille output will begin immediately.

### Connection Notes

- Automatic Connection: NVDA can automatically connect to any recognized, active Dot Pad in the vicinity if you check the Dot Pad checkbox in the list of displays to detect automatically, under NVDA's braille settings.
- Wired Priority: If you have Dot Pad checked under NVDA's automatic search list, the system will dynamically prioritize the wired USB connection whenever the cable is plugged in.

Note that you cannot connect via Bluetooth and USB simultaneously.

## Controlling NVDA with Navigation Buttons

You can use the buttons on Dot Pad to navigate Windows and control NVDA without touching your keyboard. However, you will need to use your computer keyboard for typing and some Windows commands.

A long press means pressing and holding the mentioned buttons for 1.5 seconds or more. Note that all commands can be changed, or new commands can be assigned to button combinations, using NVDA's Input Gestures dialog. Please refer to NVDA's own user guide for information on assigning input gestures.

### Panning

- Left Pan Key (Triangular): Scroll back through the braille text in the 20-cell area.
- Right Pan Key (Triangular): Scroll forward through the braille text in the 20-cell area.
- F1 Key: Scroll back in the multiline braille area, pan the tactile graphic left, or move to the previous chart data point.
- F4 Key: Scroll forward in the multiline braille area, pan the tactile graphic right, or move to the next chart data point.
- F3 Key:
    - In braille mode: Activate or execute the currently focused navigator object, equivalent to NVDA+enter.
    - In a tactile graphic: Scroll the graphic down.

### Multi Key Commands

- Left Pan + F1 Key: Move the viewport left a few dots in graphics mode.
- Right Pan + F4 Key: Pan the graphic right a few dots in graphics mode.
- F1+F2: Move the viewport up a few dots in graphics mode.
- F3+F4: Move the viewport down a few dots in graphics mode.
- F1+F3: Convert the letter, emoji, graphic or selection to a tactile image. Long press for screen capture mode.
- F2+F4: Braille mode.
- F2+F3: When showing a tactile image, zoom in (magnify the image). When no tactile image is showing, this also converts the letter, emoji, graphic or selection to a tactile image.
- F1+F4: When showing a tactile image, zoom out (shrink the image).
- F1+F2+F3+F4: When showing a tactile image, invert it: show dots where there was whitespace, and whitespace where there were dots.

## NVDA Braille Settings

NVDA controls the braille translation engine, converting your screen's text into braille data for the Dot Pad. These advanced features and structural behaviors are managed within NVDA's braille settings.

### Dual Display Separation (System Focus vs. Navigator Object)

By default, the NVDA Dot Pad driver maps the single-line 20-cell display to follow the system focus, where your typing cursor or tab key is. Meanwhile, the multiline 300-cell display either shows multiline text from the system caret, or text from the navigator object and review cursor, depending on the Multiline Source setting in the Dot Pad settings panel. This lets you either review full multiline text, or independently look at two different screen areas simultaneously, depending on the view.

### Braille Tethering (NVDA+control+t)

This setting determines which cursor's content outputs to your braille device. When using the Dot Pad, it is recommended to set braille tethering to "System Focus". This naturally reinforces the separation of the 20-cell display for focus text and the 300-cell display for multiline context.

### Follow Cursor Toggle

By pressing NVDA+7 (toggle "Follow system focus") and NVDA+6 (toggle "Follow System Caret"), you can freeze the text on your multiline graphic display. This allows you to reference a webpage or document in the multiline area while actively typing into a text editor on the single-line display.

### Blinking Cursor

By default NVDA blinks the braille cursor. Dot Pad cells refresh slowly, and not reliably at all while you are touching them, so a blinking cursor is of little use. During the installation of the add-on it asks you whether to turn the blinking cursor off. NVDA has a single blink setting for all braille displays, so answering "Yes" turns blinking off on every display you use. Like the automatic detection question it is only asked once, and you can change it at any time with the "Blink cursor" checkbox in NVDA's braille settings.

### Microsoft Excel and PowerPoint Chart Conversion

When you navigate to a chart area in Excel or PowerPoint, using control+alt+5 or NVDA's elements list (NVDA+f7), the add-on automatically translates the chart data into a bar graph layout rendered dynamically on the 300-cell multiline graphic display.

Note that other chart types will render as a bar graph as well. This is a limitation we hope to resolve soon.

### Input Gestures Customization

If you want to change what the F1 to F4 or panning keys do, go to NVDA menu, Preferences, Input Gestures. Under the feature categories, you can select "Add" and press any button combination on the Dot Pad to remap it to a new NVDA command.

## Tactile Graphics Mode

This add-on includes Dot's Tactile Display API library to introduce seamless, real-time tactile graphics directly into the Windows environment, allowing blind users to physically feel layout shapes, diagrams and formatting structure.

### Microsoft Excel Data and Table Mode

When interacting with spreadsheets, the add-on maps distinct information across your dual displays. The 300-cell graphical display transforms spreadsheet data into a physical, tactile table layout, allowing you to feel cell barriers and vertical alignments. Simultaneously, the exact structural text content of the currently focused cell is shown in braille on the 20-cell text display.

### Tactile Letter and Shape Rendering (Hybrid Mode)

By enabling the opt-in setting "Show print and braille together (hybrid mode)" under the Dot Pad settings in NVDA Settings, fields with an active text cursor, such as documents or edit boxes, will show actual physical letter shapes as tactile print on the 300-cell area, similar to graphic mode, rather than braille characters. NVDA continues to drive normal braille on your separate 20-cell text window.

### Tactile Graphs in Microsoft Word

You can use math expressions directly inside applications to render cartesian graphs on the fly.

In Microsoft Word:

1. Press alt+= to enable the standard equation editor.
2. Type in your desired expression. NVDA will automatically output the text based on your output settings for math.

You can write the following example expressions to demonstrate math graphs in Microsoft Word:

- Linear function: y = x
- Quadratic function (parabola): y = x^2
- Square root function: y = sqrt(x)
- Cubic function: y = x^3
- Sinusoidal function (wave): y = sin(x)
- Rational function: y = 1/x

To view math graphs on the Dot Pad:

1. Use the keyboard to arrow down to the target equation in your document.
2. With your cursor resting on the equation, press F1+F3 on the Dot Pad to enter tactile viewer mode.
3. Zoom in by pressing F2+F3 on the Dot Pad.
4. Zoom out by pressing F1+F4 on the Dot Pad.
5. When finished, press F2+F4 on the Dot Pad to exit the viewer and return to standard braille output.

### Rendering Tactile Print

You can also feel a tactile representation of print characters by pressing F1+F3. Dot Pad will render the character at the cursor. You can zoom in with F2+F3, and out with F1+F4. You can invert the tactile image by pressing all four function keys together.

## Focus Tracking

Graphics mode allows the Dot Pad to automatically follow your system cursor events without requiring manually typed coordinates. If your NVDA review cursor diverges from the system focus, such as when exploring a virtual document on a web page, the add-on switches to bounding-box rendering to keep you oriented.

## Navigation Button Changes and Panning

You will notice that button functions depend on the context. The presentation pipeline changes the bindings of the physical buttons based on your cursor activity.

Braille presentation takeover: Whenever you press an arrow key to edit text, graphic mode automatically exits to avoid interfering with your workflow. Viewport pan and zoom gestures are unbound, and braille presentation takes over the display.

Button map reference, standard mode:

- Left Pan Key (Triangular): Scroll back through single-line braille text displayed in the 20-cell text area.
- Right Pan Key (Triangular): Scroll forward through single-line braille text displayed in the 20-cell text area.
- F1 Key: Scroll back in the 300-cell multiline area, or move to the previous chart data point.
- F4 Key: Scroll forward in the 300-cell multiline area, or move to the next chart data point.
- F2+F4: Return to standard braille output from the tactile viewer, or trigger the tactile object blueprint visualization mode.
- F3 Key: Serves as the hardware enter button, or executes the currently focused navigator object.
- F1+F3 or F2+F3: Enter tactile graphics mode when the cursor is placed on a letter, emoji, graphic, text selection, or on a math equation in Microsoft Word.

Button map reference, tactile graphics mode. When the review mode is explicitly set to tactile graphics, the button configuration adjusts to let you navigate and manipulate the viewport of the graphic or math equation directly from the hardware:

- F2+F3: Zoom in on the tactile graphic or math graph.
- F1+F4: Zoom out from the tactile graphic or math graph.
- F1 Key: Pan the tactile graphic view one step to the left.
- F4 Key: Pan the tactile graphic view one step to the right.
- F2 Key: Pan the tactile graphic view one step up.
- F3 Key: Pan the tactile graphic view one step down.
- Left Pan + F1 Key: Pan the tactile graphic view left by a few dots.
- Right Pan + F4 Key: Pan the tactile graphic view right by a few dots.
- F1+F2: Pan the tactile graphic view up by a few dots.
- F3+F4: Pan the tactile graphic view down by a few dots.
- Left Pan + Right Pan Keys, pressed simultaneously: Reset the tactile graphics view back to the default, centered presentation.

## Dot Pad Display Viewer

Sighted teachers, coworkers, friends or family can see what is under your fingers with the onscreen braille visualizer, which may be used when the Dot Pad is connected. See the Dot Pad Display Viewer option under the NVDA Tools menu. When this option is checked, both the single line and the main graphics area will be shown on the computer's screen when the Dot Pad is in use. This is useful for sighted demonstrations of the capabilities of the Dot Pad, training, or other collaboration scenarios.

Note that the NVDA braille viewer, also available from the Tools menu, only shows the 20-cell display. When using a Dot Pad, it is recommended to disable the NVDA braille viewer and only use the Dot Pad Display Viewer if an on-screen view of the display is required.

## Getting Help

For problems with the add-on, including bugs and feature requests, please use the [issue tracker](https://github.com/dotincorp/nvda-addon-store/issues). An NVDA log at debug level is usually essential: set the logging level in NVDA's general settings, reproduce the problem, then attach the log. Please review the log before attaching it, as logs record window titles and spoken text. Do not attach crash dumps (nvda_crash.dmp) to a public issue: they contain a raw image of NVDA's memory, which can include the contents of documents you had open. If a crash dump is needed, say so in the issue and it will be arranged privately.

For help with the Dot Pad hardware itself, please contact [Dot Inc.](https://dotincorp.com/).

## Licence

This add-on is distributed under the terms of the GNU General Public License, version 2 or later. The full text is in the file COPYING.txt, and the licences of the bundled third-party components are in THIRD_PARTY_NOTICES.md. Both files are shipped alongside this guide.
