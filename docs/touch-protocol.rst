Touch protocol
==================

.. versionadded:: 0.50.0

A touchscreen reports every finger on it, and a trackpad every finger on the
pad. The mouse protocol sees only one pointer, and the :doc:`gesture-protocol`
only what the system has recognized, so a program that wants to paint with
fingers, reject a palm, or recognize gestures of its own has nothing to work
with. The touch protocol is an open terminal extension that reports the
contacts themselves, each with an id, to the program running in the terminal.
Like the other extensions here it is small, unobtrusive, easy to implement and
changes nothing about what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``touch`` selector::

    <OSC> 777 ; touch ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal integers that carry no leading ``+``.
Keys are case sensitive. A frame with a duplicate key, a value out of range,
or a missing required field is rejected as a whole, and a rejected or
incomplete frame must never reach a program as keystrokes. Spaces in the
examples below are for clarity only.

Every frame has ``v``, the protocol version, currently ``1``, and ``op``, one
of ``query``, ``cap``, ``mode`` and ``event``.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; touch ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; touch ; v=1 : op=cap : id=42 : caps=5 <ST>

``caps`` is a bit set of what the terminal can report: contacts on a
touchscreen ``1``, contacts on a trackpad ``2``, the shape of a contact
``4``. It describes what the terminal can pass on from the system it runs on,
not whether such a device is attached. A terminal that does not support the
protocol ignores the query, so a program must time out. A query does not
change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; touch ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. While the mode is on, the fingers on the window are
reported with this protocol and not turned into mouse events: a tap is not a
click and a drag does not scroll or select. The mouse and scroll events of a
trackpad are unaffected, since the system produces those itself, and so are
the gestures of the :doc:`gesture-protocol`, so a program that uses both
should expect a pinch to arrive as two contacts and as a gesture.

The mode is local to the window and is reset by ``RIS``. Turning it off, or a
reset, ends every contact without a report, so a program must forget the
contacts it holds when it turns the mode off. Programs must turn it off when
they exit, suspend or fail, and turn it back on when resumed. Multiplexers
keep it with the rest of the terminal state, restore it on reconnect, and
turn it off when detaching. There is no user setting that overrides the
program's choice.

Reports
-----------

Each change of a contact is a frame of its own::

    <OSC> 777 ; touch ; v=1 : op=event : type=move : t=408211 : id=3 : x=25600 : y=51200 : mods=0 : src=screen <ST>

================ ==================================================================
``type``         ``down`` when the finger lands, ``move`` when it moves, ``up``
                 when it lifts, ``cancel`` when the system takes the finger
                 over, for a gesture of its own, and ``frame``, see below
``t``            The time of the event in milliseconds on a monotonic clock of
                 the terminal's choosing, useful only for differences between
                 reports
``id``           The contact: a small non-negative integer unique among the
                 fingers that are down at the same time, which the terminal
                 can reuse once the finger has lifted
``x``, ``y``     For ``src=screen`` the position in 1/256 pixel, signed, zero
                 based, relative to the top left of the cell area, within
                 ±1073741823. For ``src=pad`` the position on the device, from
                 ``0`` to ``65535`` on each axis, with the origin at the top
                 left of the pad
``mods``         Shift ``1``, Alt ``2``, Control ``4``, Super ``8``
``src``          ``screen`` for a touchscreen, where the finger is on the
                 window, ``pad`` for a trackpad, where it is not
================ ==================================================================

A ``screen`` contact may add its shape, when the system knows it:

======================= ====================================================
``major``, ``minor``    The axes of the ellipse of the contact, in 1/256
                        pixel
``angle``               The orientation of the ellipse in hundredths of a
                        degree, clockwise from the vertical
======================= ====================================================

A ``pad`` contact may add ``w`` and ``h``, the size of the pad in 1/256
millimeter, so a program can turn positions into distances, or map the pad
onto its canvas with the right aspect ratio.

A ``frame`` report carries only ``t`` and ends a group of reports that
happened at the same time, the way a touch system delivers all the fingers
that moved together before any of them is acted on::

    <OSC> 777 ; touch ; v=1 : op=event : type=down : t=408211 : id=0 : x=25600 : y=51200 : mods=0 : src=screen <ST>
    <OSC> 777 ; touch ; v=1 : op=event : type=down : t=408211 : id=1 : x=38400 : y=51200 : mods=0 : src=screen <ST>
    <OSC> 777 ; touch ; v=1 : op=event : type=frame : t=408211 <ST>

A program that cares about the relation between fingers, as a pinch
recognizer does, collects reports until the ``frame`` and applies them at
once. A program that paints one stroke per finger can act on each report as
it comes.

Lifecycle
-------------

A contact begins with ``down``, is followed by any number of ``move``
reports and ends with ``up`` or ``cancel``. A finger that lands and lifts
without moving still produces both ``down`` and ``up``. After ``cancel`` the
contact is over and the program must discard what it did, as it would for a
gesture the system claimed. The reports of a finger go to the window under
it when it landed, or for a trackpad to the window under the pointer when
the first finger landed, and the later reports of all the fingers of that
sequence go to the same window even when they move out of it, so
coordinates can be negative or exceed the cell area. A new sequence starts
once every finger has lifted.

A multiplexer translates ``x,y`` of ``screen`` contacts by the pane's origin
(borders included), forwards every other field unchanged, and delivers each
sequence only to the pane it began in. A multiplexer or relay that detaches
or loses its connection while contacts are live sends ``cancel`` for each of
them to the program, so a program never holds a dead contact, and a relay
that reconnects forwards nothing it did not see, the fingers down at that
moment are simply reported from their next ``down``.

Versions and extension
-------------------------

A program speaking version 1 ignores fields it does not know, so new fields
are added without a version change. A new ``type`` or ``src`` value, or a
change in the meaning of an existing field, needs a new version. A terminal
never sends a field the negotiated version does not define.

Implementations
--------------------

* silkie, this fork of kitty: touchscreens with contact shape on Wayland,
  the trackpad on macOS, nothing on X11. ``kitty --debug-input`` logs the
  touches it sees.

Implementation notes for silkie
----------------------------------

* On Wayland the contacts come from ``wl_touch``, with ``shape`` and
  ``orientation`` on a seat of version 6 or later. ``caps`` claims the shape
  whenever kitty runs on Wayland, even on an older seat, in which case the
  shape fields are simply absent.
* On macOS the contacts are the indirect touches of the trackpad, as AppKit
  reports them to the content view, so a finger resting on the pad is not
  reported. The pad size comes from the device size AppKit gives, taken to be
  in points at 72 to the inch.
* On X11 nothing is reported, XInput 2 touch events are not selected.
