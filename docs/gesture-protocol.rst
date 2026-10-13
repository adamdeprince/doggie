Trackpad gesture protocol
============================

.. versionadded:: 0.50.0

A trackpad delivers more than scrolling: the system recognizes a pinch, a
rotation, a swipe with several fingers, a double tap with two fingers and
fingers held still, and hands them to the application as gestures. The trackpad gesture protocol is
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
of ``query``, ``cap``, ``mode`` and ``event``. A program ignores a frame whose
``op`` it does not know.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; gesture ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; gesture ; v=1 : op=cap : id=42 : caps=15 : mode=0 <ST>

``caps`` is a bit set of the gestures the terminal can report: pinch ``1``,
rotate ``2``, swipe ``4``, smart zoom ``8``, hold ``16``. It describes what
the terminal can pass on from the window system it is connected to, not
whether a trackpad is attached. ``mode`` is the current state of the mode
described below.
A terminal that does not support the protocol ignores the query, so a
program must time out. A query does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; gesture ; v=1 : op=mode : mode=1 <ST>

``mode`` is a bit set of the kinds of gesture the program wants: ``1`` the
gestures made by moving fingers, which are the pinch, the rotation, the swipe
and the smart zoom, ``2`` holds; ``0`` turns reporting off. While a bit is
on, the gestures it names are reported with this protocol when they happen
over the window. A terminal drops the bits it does not know, so a program
that depends on a bit reads the mode back. The scroll and touch events the
same fingers produce are unaffected, a two finger pinch still scrolls if the
system scrolls during it, so a program that zooms on pinch should expect
scroll reports too and ignore them while a pinch is in progress.

The mode is local to the window, is reset by ``RIS``, and changing it
cancels every gesture in progress. Programs must turn it off when they exit,
suspend or fail, and turn it back on when resumed. Multiplexers keep it with
the rest of the terminal state, restore it on reconnect, and turn it off when
detaching. There is no user setting that overrides the program's choice.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; gesture ; v=1 : op=mode : mode=1 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

Reports
-----------

A report is a single frame per event::

    <OSC> 777 ; gesture ; v=1 : op=event : kind=1 : phase=2 : x=25600 : y=51200 : mods=0 : scale=120 : total=1340 <ST>

``kind``, ``phase``, ``x``, ``y`` and ``mods`` are always present:

================ ==================================================================
``kind``         ``1`` pinch, ``2`` rotate, ``3`` swipe, ``4`` smart zoom,
                 ``5`` hold
``phase``        ``1`` begin, ``2`` update, ``3`` end, ``4`` cancel
``x``, ``y``     Position of the pointer in 1/256 of a physical pixel, signed,
                 zero based, relative to the top left of the cell area, within
                 ±1073741823. A physical pixel is one of the framebuffer the
                 terminal draws into, not a scaled unit of the window system
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

A smart zoom and a hold carry no extra fields.

Any kind may also carry ``fingers``, the number of fingers making the
gesture. The system tells it when the gesture begins, and it is then present
in every report of that gesture. It is absent when the system does not say.

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

A hold begins when fingers come to rest on the trackpad and ends when they
lift, with no ``update`` in between. It is cancelled when the fingers start
to move instead, which usually begins a scroll or another gesture. Programs
use it to stop something in motion, a coasting scroll, say, the moment the
user touches the trackpad.

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

A program ignores a frame whose ``op`` it does not know, a report whose
``kind`` it does not know and fields it does not know, so all three are added
without a version change. A new kind is also only sent to a program that
asked for it with a mode bit of its own, as the hold is, so a program that
sends ``mode=1`` sees the four kinds that bit names and nothing else, however
much the protocol grows. A new ``phase`` value, or a change in the meaning of
an existing field, needs a new version.

Implementations
-------------------

* silkie, this fork of kitty: pinch, rotate, swipe and smart zoom on macOS;
  pinch, rotate, swipe and hold, with the number of fingers, on Wayland;
  pinch, rotate and swipe, with the number of fingers, on X11.
  ``kitty --debug-input`` logs the gestures it sees.

Implementation notes for silkie
----------------------------------

silkie passes on what the window system recognizes:

* On macOS, the magnify, rotate, swipe and smart magnify events of AppKit. A
  swipe with three fingers only reaches applications when System Settings
  has it set to swipe between pages, and a smart zoom when the trackpad's
  smart zoom is enabled. AppKit does not say how many fingers made a
  gesture, so ``fingers`` is absent.
* On Wayland, through version 3 of ``pointer-gestures-unstable-v1``, and
  ``caps`` is zero on a compositor without it. A pinch there carries both
  scale and rotation, so one compositor pinch is reported as a pinch and a
  rotation. A swipe is reported once it ends, as its dominant direction, and
  compositors keep most three finger swipes for themselves. A hold also
  stops kitty's own coasting scroll.
* On X11, through the touchpad gestures of XInput 2.4, which needs version
  21.1 or later of the X server and a driver that sends them, as the
  libinput driver does. ``caps`` is zero when the server does not have
  them. A pinch and a swipe are reported as on Wayland. X11 has no hold and
  no smart zoom.
