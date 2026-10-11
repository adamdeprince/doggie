Trackpad gesture protocol
============================

.. versionadded:: 0.50.0

A trackpad delivers more than scrolling: the system recognizes a pinch, a
rotation, a swipe with several fingers and a double tap with two fingers, and
hands them to the application as gestures. The trackpad gesture protocol is
an open terminal extension that reports them to the program running in the
terminal. Like the other extensions here it is small, unobtrusive, easy to
implement and changes nothing about what the TTY is.

It is independent of the :doc:`tablet-protocol`, which reports the fingers
themselves and leaves recognizing a gesture to the program. Both can be on at
the same time, a program takes whichever suits it.

Framing
-------------

Frames are ``OSC 777`` with the ``gesture`` selector::

    <OSC> 777 ; gesture ; <fields> <ST>

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

    <OSC> 777 ; gesture ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; gesture ; v=1 : op=cap : id=42 : caps=15 <ST>

``caps`` is a bit set of the gestures the terminal can report: pinch ``1``,
rotate ``2``, swipe ``4``, smart zoom ``8``. It describes what the terminal
can pass on from the system it runs on, not whether a trackpad is attached.
A terminal that does not support the protocol ignores the query, so a
program must time out. A query does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; gesture ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. While the mode is on, gestures over the window are
reported with this protocol. The scroll and touch events the same fingers
produce are unaffected, a two finger pinch still scrolls if the system
scrolls during it, so a program that zooms on pinch should expect scroll
reports too and ignore them while a pinch is in progress.

The mode is local to the window, is reset by ``RIS``, and changing it
cancels every gesture in progress. Programs must turn it off when they exit,
suspend or fail, and turn it back on when resumed. Multiplexers keep it with
the rest of the terminal state, restore it on reconnect, and turn it off when
detaching. There is no user setting that overrides the program's choice.

Reports
-----------

A report is a single frame per event::

    <OSC> 777 ; gesture ; v=1 : op=event : kind=1 : phase=2 : x=25600 : y=51200 : mods=0 : scale=120 : total=1340 <ST>

``kind``, ``phase``, ``x``, ``y`` and ``mods`` are always present:

================ ==================================================================
``kind``         ``1`` pinch, ``2`` rotate, ``3`` swipe, ``4`` smart zoom
``phase``        ``1`` begin, ``2`` update, ``3`` end, ``4`` cancel
``x``, ``y``     Position of the pointer in 1/256 pixel, signed, zero based,
                 relative to the top left of the cell area, within ±1073741823
``mods``         Shift ``1``, Alt ``2``, Control ``4``, Super ``8``
================ ==================================================================

The fields a kind adds:

======================= ====================================================
pinch ``scale``         The change in magnification since the previous
                        report of the gesture, in thousandths: ``100`` is
                        ten percent larger, ``-100`` ten percent smaller
pinch ``total``         The magnification since the gesture began, in
                        thousandths, ``1000`` when unchanged
rotate ``angle``        The rotation since the previous report, in
                        hundredths of a degree, clockwise positive
rotate ``total``        The rotation since the gesture began, in hundredths
                        of a degree
swipe ``dx``, ``dy``    The direction the fingers moved, ``-1``, ``0`` or
                        ``1`` on each axis, positive to the right and down.
                        Exactly one of the two is non-zero
======================= ====================================================

A smart zoom carries no extra fields.

Lifecycle
-------------

A gesture begins with ``begin``, is followed by any number of ``update``
reports and ends with ``end`` or ``cancel``. A ``begin`` carries a ``scale``
of ``0``, an ``angle`` of ``0``, and a ``total`` of ``1000`` or ``0``. A swipe
and a smart zoom are instantaneous: they are reported as a ``begin``
immediately followed by an ``end``, both with the same fields. A pinch and a
rotation are independent gestures that usually run at the same time, since
two fingers that pinch also turn a little, so a program interested in one
must tolerate reports of the other.

A gesture is captured by the window it began in, and its later reports go
to that window even when the pointer moves out of it, so coordinates can be
negative or exceed the cell area. The terminal cancels gestures in progress
when the mode changes or the terminal is reset. After a cancel the rest of
that gesture is not reported, not even its ``end``. Programs must tolerate a
repeated cancel and a fresh ``begin`` for a kind they still have open, which
replaces the earlier gesture.

A multiplexer translates ``x,y`` by the pane's origin (borders included),
forwards every other field unchanged, delivers each gesture only to the pane
it began in, and cancels gestures when panes move or resize.

Versions and extension
-------------------------

A program speaking version 1 ignores fields it does not know, so new fields
are added without a version change. A new ``kind`` or ``phase`` value, or a
change in the meaning of an existing field, needs a new version. A terminal
never sends a field the negotiated version does not define.

Implementations
-------------------

* silkie, this fork of kitty: all four kinds on macOS, pinch, rotate and
  swipe on Wayland, nothing on X11. ``kitty --debug-input`` logs the
  gestures it sees.

Implementation notes for silkie
----------------------------------

silkie passes on what the window system recognizes:

* On macOS, the magnify, rotate, swipe and smart magnify events of AppKit. A
  swipe with three fingers only reaches applications when System Settings
  has it set to swipe between pages, and a smart zoom when the trackpad's
  smart zoom is enabled.
* On Wayland, through ``pointer-gestures-unstable-v1``. A pinch there
  carries both scale and rotation, so one compositor pinch is reported as a
  pinch and a rotation. A swipe is reported once it ends, as its dominant
  direction, and compositors keep most three finger swipes for themselves.
  ``caps`` claims these three whenever kitty runs on Wayland, even on a
  compositor without the protocol.
