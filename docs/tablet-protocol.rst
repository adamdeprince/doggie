Tablet pointer protocol
==========================

.. versionadded:: 0.50.0

Pens and fingers carry far more than the mouse protocol can express:
pressure, tilt, rotation of the barrel, which end of the pen is in use,
hovering, several fingers at once, the shape of each finger on the glass.
The tablet pointer protocol is an open terminal extension that reports all
of it, from graphics tablets, pen displays, touchscreens and touchpads, with
room for whatever a device measures. It belongs to no terminal: silkie (this
kitty fork) implements it and this page is its specification. The goals are
those of the other extensions here: small, unobtrusive, easy to implement,
and no change to what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``tablet-pointer`` selector::

    <OSC> 777 ; tablet-pointer ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal integers that carry no leading ``+``.
Keys are case sensitive. A frame from a program is at most 127 bytes after
the selector. A frame with a value out of range or a missing required field
is rejected as a whole, and a rejected or incomplete frame must never reach a
program as keystrokes. Spaces in the examples below are for clarity only.

Every frame has ``v``, the protocol version, which is ``1``, and ``op``, one
of ``query``, ``cap``, ``mode`` and ``event``. A frame with any other
version is ignored. A program ignores fields it does not know, so new fields
can be added without a version change; a new ``kind``, ``phase`` or ``tool``
value, or a change in the meaning of an existing field, needs a new version.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; tablet-pointer ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; tablet-pointer ; v=1 : op=cap : id=42 : caps=5 : mode=0 : w=1200 : h=800 : cw=12 : ch=24 <ST>

``caps`` is a bit set of what the terminal can report: tools ``1``, fingers
on a touchscreen ``2``, fingers on a touchpad ``4``, the shape of a finger
contact ``8``. It describes the terminal on the system it runs on, not the
hardware attached right now. ``mode`` is the current state of the mode
described below. ``w,h`` are the size of the cell area in pixels (1 to
65535) and ``cw,ch`` the cell size (1 to 4096). A program queries again
after a resize. A terminal that does not support the protocol ignores the
query, so a program must time out and fall back to mouse reporting. A query
does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; tablet-pointer ; v=1 : op=mode : mode=3 <ST>

``mode`` is a bit set of the report kinds the program wants: ``1`` tools,
``2`` fingers; ``0`` turns reporting off. While a bit is on, that kind of
input over the window is reported with this protocol instead of as mouse
events, so with ``mode=1`` a pen draws while a finger still taps and scrolls
as a mouse, and with ``mode=3`` a tap is not a click and a drag does not
select. A physical mouse, and the mouse and scroll events a touchpad produces
by itself, continue to use whatever mouse reporting the program asked for.
Programs that merely want pen input to act as a mouse need not use the
protocol at all.

The mode is local to the window, is reset by ``RIS``, and changing it
cancels every active contact. Programs must turn it off when they exit,
suspend or fail, and turn it back on when resumed. Multiplexers keep it with
the rest of the terminal state, restore it on reconnect, and turn it off
when detaching. There is no user setting that overrides the program's
choice.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; tablet-pointer ; v=1 : op=mode : mode=3 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

Reports
-----------

A report is a single frame per event::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=1 : phase=1 : device=3 : t=408211 : contact=0 : x=25600 : y=51200 : buttons=1 : mods=0 : tool=1 : valid=3 : p=32000 : tx=-1200 : ty=600 : serial=4242 <ST>

``kind``, ``phase``, ``device``, ``t``, ``contact``, ``x`` and ``y`` are
required. The other fields in this table default to zero, except ``tool``,
which defaults to ``1``:

================ ==================================================================
``kind``         ``1`` tool, ``2`` finger
``phase``        ``0`` hover, ``1`` down, ``2`` move, ``3`` up, ``4`` cancel,
                 ``5`` the tool left proximity, ``6`` frame, see below
``device``       Identifies the tool or touch device for as long as it is in
                 proximity, a non-negative 31 bit integer, ``0`` when the
                 system does not tell devices apart
``t``            The time of the event in milliseconds on a monotonic clock of
                 the terminal's choosing, or of its delivery when the system
                 does not time stamp it, useful only for differences between
                 reports
``contact``      Identifies one contact of a device, stable for its lifetime.
                 A pen is normally contact ``0``, fingers get the system's
                 touch ids, which it may reuse once a finger has lifted
``x``, ``y``     Position in 1/256 pixel, signed, zero based, relative to the
                 top left of the cell area, within ±1073741823; for a finger
                 on a touchpad (``src=1``) the position on the pad instead,
                 ``0`` to ``65535`` on each axis with the origin at its top
                 left
``buttons``      Held buttons: tip or left ``1``, barrel or right ``2``, second
                 barrel or middle ``4``, back ``8``, forward ``16``, third
                 barrel ``32``. A finger has ``1`` while it is down
``mods``         Shift ``1``, Alt ``2``, Control ``4``, Super ``8``
``tool``         ``0`` finger or unknown, ``1`` pen, ``2`` eraser, ``3`` brush,
                 ``4`` pencil, ``5`` airbrush, ``6`` mouse, ``7`` lens
``valid``        The measurements the report carries, a bit set, see below
``src``          For a finger, ``1`` when it is on a touchpad rather than on
                 the screen; absent otherwise
``w``, ``h``     For a finger on a touchpad, the size of the pad in 1/256
                 millimeter when the system knows it, so a program can turn
                 positions into distances or map the pad onto its canvas with
                 the right aspect ratio
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
``dist``                32    Distance from the tablet, 0 to 65535
``wheel``, ``wclicks``  64    Rotation of the wheel on a mouse or lens tool since
                              the last report, in hundredths of a degree and in
                              clicks
``major``, ``minor``,   128   The shape of a finger on the screen: the axes of
``angle``                     the ellipse of the contact in 1/256 pixel and its
                              orientation in hundredths of a degree, clockwise
                              from the vertical
======================= ===== ====================================================

Reports may also identify the hardware: ``serial`` is the serial number of
the tool, ``hwid`` its hardware id (on Wacom tablets, the tool type), and
``vid`` and ``pid`` the USB ids of the tablet. These are unsigned 64 bit
(``serial``, ``hwid``) and 32 bit (``vid``, ``pid``) integers, present only
when the system reports them.

Fingers
~~~~~~~~~~

Finger reports have ``kind=2``, ``tool=0``, ``buttons=1`` while down, one
``contact`` per finger, and usually no measurements beyond the shape. A
touch system delivers all the fingers that moved together before any of them
is acted on, and the terminal keeps that grouping: after the reports of one
such group it sends a frame report, which carries only ``kind=2``,
``phase=6``, ``device`` and ``t``::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=1 : device=0 : t=408211 : contact=0 : x=25600 : y=51200 : buttons=1 : mods=0 : tool=0 : valid=0 <ST>
    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=1 : device=0 : t=408211 : contact=1 : x=38400 : y=51200 : buttons=1 : mods=0 : tool=0 : valid=0 <ST>
    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=6 : device=0 : t=408211 <ST>

A program that cares about the relation between fingers, as a pinch
recognizer does, collects reports until the frame and applies them at once.
A program that paints one stroke per finger can act on each report as it
comes. Frames are sent for fingers only; a tool reports one contact at a
time.

Lifecycle
-------------

A stroke begins with ``down`` and ends with ``up`` or ``cancel``; in between
every report of that contact is a ``move``. The stroke stays captured by the
window it began in even when the tool or finger leaves it, so coordinates can
be negative or exceed the cell area, and they must not be clamped into
another window. The fingers of one sequence, from the first finger landing
to the last lifting, all go to the window under the first finger, or for a
touchpad to the window under the pointer when the first finger landed.
``hover`` reports follow a tool in proximity without a contact and are not
captured. A tool leaving proximity cancels any stroke it had open, and then,
when the system reports it, sends phase ``5``.

The terminal cancels contacts, with ``buttons=0`` and ``p=0``, when the mode
changes, the terminal is reset, the window is resized, the system takes the
fingers over for a gesture of its own, or the device goes away. After a
cancel the rest of that stroke is not reported, not even its ``up``.
Programs must tolerate a lost ``hover``, a repeated cancel, and a fresh
``down`` for a contact they still have open, which replaces the earlier
stroke.

A multiplexer translates ``x,y`` of on-screen contacts by the pane's origin
(borders included) and scroll offset, forwards every other field unchanged,
delivers each stroke and each finger sequence only to the pane it began in,
and cancels contacts when panes move or resize. A multiplexer or relay that
detaches or loses its connection while contacts are live sends ``cancel``
for each of them to the program, so a program never holds a dead contact,
and a relay that reconnects forwards nothing it did not see: the fingers
down at that moment are simply reported from their next ``down``.

Implementations
-------------------

* silkie, this fork of kitty: tools on macOS, Wayland and X11; fingers on
  the touchpad on macOS and on touchscreens, with contact shape, on Wayland.
  ``kitty --debug-input`` logs the tablet and touch events it sees.
* Inkline, Goblin Skiff and GoblinView carry a codec for an earlier draft of
  this protocol and are being brought up to this specification.

Implementation notes for silkie
----------------------------------

silkie reads tablets and touch devices through the window system, so a
program gets what the system reports:

* On macOS, tablet data arrives with the mouse events of the tablet driver.
  Tilt is scaled from the driver's fraction of maximum tilt assuming 60
  degrees, as Wacom tablets report, and ``z`` is the driver's absolute Z.
  Fingers are the indirect touches of the trackpad, as AppKit reports them
  to the content view, so a finger resting on the pad is not reported; the
  pad size is the device size AppKit gives, taken to be in points at 72 to
  the inch. Trackpad fingers are reported alongside the mouse and scroll
  events the system makes from them.
* On Wayland, tools come through the ``tablet-v2`` protocol, which reports
  every measurement above and identifies the tool and the tablet, and
  fingers through ``wl_touch``, with ``shape`` and ``orientation`` on a seat
  of version 6 or later (``caps`` claims the shape on every Wayland seat; on
  an older one the shape measurement is simply absent). The pointer cursor
  follows a tool only on compositors with ``cursor-shape-v1``. GNOME applies
  its own stylus button mapping first (by default the lower button is the
  middle button), sway passes the buttons through.
* On X11, tools come through XInput 2 devices whose names include the tool
  type, as the libinput and wacom drivers name them. ``tangent`` carries the
  device's wheel axis and ``twist`` its rotary Z axis. The X server does not
  report a tool leaving proximity, so phase ``5`` arrives only when the
  device goes away. Xwayland's tablet devices are recognised too, but under
  GNOME no motion reached them in testing; use the Wayland backend there.
  Fingers are not reported on X11.
