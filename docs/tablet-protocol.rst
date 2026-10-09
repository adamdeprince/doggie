Tablet pointer protocol
==========================

.. versionadded:: 0.50.0

Pen and touch input carry far more than the mouse protocol can express:
pressure, tilt, rotation of the barrel, which end of the pen is in use,
hovering, several fingers at once. The tablet pointer protocol is an open
terminal extension that reports all of it, with room for whatever a device
measures. It belongs to no terminal: silkie (this kitty fork) implements it,
as do Inkline, Goblin Skiff and GoblinView, and this page is its
specification. The goals are those of the other extensions here: small,
unobtrusive, easy to implement, and no change to what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``tablet-pointer`` selector::

    <OSC> 777 ; tablet-pointer ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal integers that carry no leading ``+``.
Keys are case sensitive. A frame is at most 768 bytes. A frame with a
duplicate key, a value out of range, or a missing required field is rejected
as a whole, and a rejected or incomplete frame must never reach a program as
keystrokes. Spaces in the examples below are for clarity only.

Every frame has ``v``, the protocol version, and ``op``, one of ``query``,
``cap``, ``mode`` and ``event``.

Discovery
-------------

A program asks the terminal whether it supports the protocol, naming the
highest version the program speaks::

    <OSC> 777 ; tablet-pointer ; v=2 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers with a ``cap`` frame, at the requested version or the highest lower
one it supports::

    <OSC> 777 ; tablet-pointer ; v=2 : op=cap : id=42 : caps=3 : w=1200 : h=800 : cw=12 : ch=24 <ST>

``caps`` is a bit set of the report kinds the terminal can produce: pen
``1``, touch ``2``, two finger gesture ``4``. It describes the terminal, not
the hardware attached right now. ``w,h`` are the size of the cell area in
pixels (1 to 65535) and ``cw,ch`` the cell size (1 to 4096). A program
queries again after a resize. A terminal that does not support the protocol
ignores the query, so a program must time out and fall back to mouse
reporting. A query does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; tablet-pointer ; v=2 : op=mode : mode=1 <ST>

and off with ``mode=0``. The version in the request selects the dialect of
the reports that follow. While the mode is on, pen and touch input over the
window is reported with this protocol instead of as mouse events, while a
physical mouse continues to use whatever mouse reporting the program asked
for. Programs that merely want pen input to act as a mouse need not use the
protocol at all.

The mode is local to the window, is reset by ``RIS``, and changing it cancels
every active contact. Programs must turn it off when they exit, suspend or
fail, and turn it back on when resumed. Multiplexers keep it with the rest of
the terminal state, restore it on reconnect, and turn it off when detaching.
There is no user setting that overrides the program's choice.

Reports
-----------

A report is a single frame per event::

    <OSC> 777 ; tablet-pointer ; v=2 : op=event : kind=1 : phase=1 : device=3 : contact=0 : x=25600 : y=51200 : buttons=1 : mods=0 : tool=1 : valid=3 : p=32000 : tx=-1200 : ty=600 : serial=4242 <ST>

``kind``, ``phase``, ``device``, ``contact``, ``x`` and ``y`` are required.
The other fields in this table default to zero, except ``tool``, which
defaults to ``1``:

================ ==================================================================
``kind``         ``1`` tablet tool, ``2`` finger, ``3`` gesture
``phase``        ``0`` hover, ``1`` down, ``2`` move, ``3`` up, ``4`` cancel;
                 version 2 adds ``5``, the tool left proximity
``device``       Identifies the tool or touch device for as long as it is in
                 proximity, a non-negative 31 bit integer
``contact``      Identifies one contact of a device, stable for its lifetime.
                 A pen is normally contact ``0``, fingers get the system's
                 touch ids
``x``, ``y``     Position in 1/256 pixel, signed, zero based, relative to the
                 top left of the cell area, within ±1073741823
``buttons``      Held buttons: tip or left ``1``, barrel or right ``2``, second
                 barrel or middle ``4``, back ``8``, forward ``16``; version 2
                 adds third barrel ``32``
``mods``         Shift ``1``, Alt ``2``, Control ``4``, Super ``8``
``tool``         ``0`` finger or unknown, ``1`` pen, ``2`` eraser; version 2
                 adds ``3`` brush, ``4`` pencil, ``5`` airbrush, ``6`` mouse,
                 ``7`` lens
``valid``        The measurements the report carries, a bit set, see below
================ ==================================================================

A measurement is present exactly when its bit is set in ``valid``. A clear
bit means the device does not measure it, never that the value is zero, and a
terminal must not make a measurement up. The measurements, with their
``valid`` bit:

======================= ===== ====================================================
``p``                   1     Pressure, 0 to 65535
``tx``, ``ty``          2     Tilt in hundredths of a degree, −9000 to 9000,
                              positive towards the right and bottom of the screen
``twist``               4     Rotation of the tool around its axis in hundredths
                              of a degree, 0 to 35999 clockwise
``tangent``             8     Tangential pressure, the airbrush wheel, −65535 to
                              65535
``z``                   16    Height in device units, −1000000 to 1000000
``dist``                32    Distance from the tablet, 0 to 65535 (version 2)
``wheel``, ``wclicks``  64    Rotation of the wheel on a mouse or lens tool since
                              the last report, in hundredths of a degree and in
                              clicks (version 2)
======================= ===== ====================================================

Version 2 reports may also identify the hardware: ``serial`` is the serial
number of the tool, ``hwid`` its hardware id (on Wacom tablets, the tool
type), and ``vid`` and ``pid`` the USB ids of the tablet. These are unsigned
64 bit (``serial``, ``hwid``) and 32 bit (``vid``, ``pid``) integers,
present only when the system reports them.

Finger reports have ``kind=2``, ``tool=0``, ``buttons=1`` while down, one
``contact`` per finger and usually no measurements. Gesture reports
(``kind=3``) describe two fingers moving together: they require ``peer``
(the second contact), ``dx,dy`` (translation since the gesture began, in
1/256 pixel), ``scale`` (10000 is the original distance between the fingers,
1 to 1000000) and ``angle`` (rotation since the gesture began, in hundredths
of a degree clockwise, −36000 to 36000); ``contact`` is the first finger and
``x,y`` the centroid. Finger reports continue during a gesture, so a program
picks one stream for an operation. A gesture ends when either finger lifts
or is cancelled.

Lifecycle
-------------

A stroke begins with ``down`` and ends with ``up`` or ``cancel``; in between
every report of that contact is a ``move``. The stroke stays captured by the
window it began in even when the tool leaves it, so coordinates can be
negative or exceed the cell area, and they must not be clamped into another
window. ``hover`` reports follow a tool in proximity without a contact and
are not captured. In version 2, a tool leaving proximity cancels any stroke
it had open and then sends phase ``5``.

The terminal cancels contacts, with ``buttons=0`` and ``p=0``, when the mode
changes, the terminal is reset, the window is resized, focus changes
underneath a stroke or the device goes away. After a cancel the rest of that
stroke is not reported, not even its ``up``. Programs must tolerate a lost
``hover``, a repeated cancel, and a fresh ``down`` for a contact they still
have open, which replaces the earlier stroke.

A multiplexer translates ``x,y`` by the pane's origin (borders included) and
scroll offset, forwards every other field unchanged, delivers each stroke
only to the pane it began in, delivers a gesture only when both fingers are
in the same pane, and cancels contacts when panes move or resize.

Versions and extension
-------------------------

Version 1 is the protocol as first shipped. Version 2 adds the fields,
tools, buttons and phase marked above and one rule: **a program speaking
version 2 ignores fields it does not know**. New measurements are therefore
added with a new ``valid`` bit and field, and new identifiers as plain
fields, without a version change. A new ``kind``, ``phase`` or ``tool``
value, or a change in the meaning of an existing field, needs a new version.
Version 1 programs reject unknown fields, so a terminal sends them only the
version 1 fields, maps tools above ``2`` to ``1`` and does not send phase
``5``. A terminal never sends a field the negotiated version does not define.

.. _tablet_implementations:

Implementations
-------------------

* silkie, this fork of kitty: versions 1 and 2, pen and touch, on macOS,
  Wayland and X11. ``kitty --debug-input`` logs the tablet events it sees.
* Inkline, on the reMarkable 2: version 1, pen, touch and gestures. Its
  ``protocol/goblin_pointer.hpp`` is a C++ reference codec for version 1,
  usable without Qt; Goblin Skiff and GoblinView carry identical copies.
* goblin-draw, a drawing program in a single Python file shipped with
  Inkline (``tools/goblin-draw``): the program side of version 1, with the
  mouse protocol as its fallback. It is a good first thing to run in a
  terminal that claims support.

Implementation notes for silkie
----------------------------------

silkie reads tablets through the window system, so a program gets what the
system reports:

* On macOS, tablet data arrives with the mouse events of the tablet driver.
  Tilt is scaled from the driver's fraction of maximum tilt assuming 60
  degrees, as Wacom tablets report, and ``z`` is the driver's absolute Z.
* On Wayland, through the ``tablet-v2`` protocol, which reports every
  measurement above and identifies the tool and the tablet. The pointer
  cursor follows a tool only on compositors with ``cursor-shape-v1``. GNOME
  applies its own stylus button mapping first (by default the lower button
  is the middle button), sway passes the buttons through.
* On X11, through XInput 2 devices whose names include the tool type, as the
  libinput and wacom drivers name them. ``tangent`` carries the device's
  wheel axis and ``twist`` its rotary Z axis. The X server does not report a
  tool leaving proximity, so phase ``5`` arrives only when the device goes
  away. Xwayland's tablet devices are recognised too, but under GNOME no
  motion reached them in testing; use the Wayland backend there.
