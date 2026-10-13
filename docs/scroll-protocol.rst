Scroll protocol
==================

.. versionadded:: 0.50.0

The mouse protocol reports a scroll as presses of imaginary wheel buttons,
one per line, so a program sees a trackpad as a stuttering wheel and never
learns when a gesture begins, ends or coasts. The scroll protocol is an open
terminal extension that reports scrolling as it arrives from the system:
distances in pixels, the device that produced them, and the phase of the
gesture. It is framed like the :doc:`tablet-protocol` and shares its goals:
small, unobtrusive, easy to implement, and no change to what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``scroll`` selector::

    <OSC> 777 ; scroll ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal integers that carry no leading ``+``.
Keys are case sensitive. A frame with a duplicate key, a value out of range,
or a missing required field is rejected as a whole, and a rejected or
incomplete frame must never reach a program as keystrokes. Spaces in the
examples below are for clarity only.

Every frame has ``v``, the protocol version, which is ``1``, and ``op``, one
of ``query``, ``cap``, ``mode`` and ``event``.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; scroll ; v=1 : op=query : id=7 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply. A supporting terminal answers::

    <OSC> 777 ; scroll ; v=1 : op=cap : id=7 : caps=1 : mode=0 <ST>

``caps`` is a bit set, of which only ``1`` is defined: the terminal reports
pixel distances. ``mode`` is the current state of the mode described below.
A terminal that does not support the protocol ignores the
query, so a program must time out and fall back to mouse reporting. A query
does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; scroll ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. While the mode is on, scrolling over the window is
reported with this protocol instead of as wheel button presses, while clicks
and motion keep using whatever mouse reporting the program asked for. The
terminal does not scroll its own scrollback either; the program owns the
scroll. The mode is local to the window and reset by ``RIS``. Programs must
turn it off when they exit, suspend or fail, and turn it back on when
resumed. Multiplexers keep it with the rest of the terminal state. There is
no user setting that overrides the program's choice.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; scroll ; v=1 : op=mode : mode=1 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

Reports
-----------

One frame per scroll event::

    <OSC> 777 ; scroll ; v=1 : op=event : dx=0 : dy=250 : x=33 : y=12 : mods=1 : src=1 : phase=2 <ST>

All fields are required:

============ ====================================================================
``dx, dy``   The distance the view should move, in hundredths of a physical
             pixel, positive to the right and down, signed. A trackpad gives
             the distance the system measured; a notched wheel gives its
             lines converted with the terminal's cell size and scroll
             multiplier, so a program applies one unit either way
``x, y``     The pointer position in physical pixels, zero based, relative to
             the top left of the cell area
``mods``     Shift ``1``, Alt ``2``, Control ``4``, Super ``8``
``src``      ``0`` a notched wheel, ``1`` a precise device such as a trackpad
``phase``    ``0`` none, ``1`` a finger gesture began, ``2`` it continues,
             ``3`` it ended, ``4`` coasting began after the fingers lifted,
             ``5`` coasting continues, ``6`` coasting ended, ``7`` the gesture
             or the coasting was cancelled
============ ====================================================================

A report may carry a distance of zero, in particular with phases ``1``,
``3``, ``4`` and ``6``. A program that animates its own coasting should stop
at phase ``4``, since the terminal is already reporting the system's. A
wheel reports phase ``0`` only.

A multiplexer translates ``x,y`` by the pane's origin (borders included),
forwards every other field unchanged and delivers each report to the pane
under the pointer.

Implementation notes for silkie
----------------------------------

silkie reports what the window system gives it:

* On macOS, pixel distances and all the phases above, from the trackpad
  events of AppKit. Distances are in physical pixels, as ``x,y`` are, so on
  a Retina display they are twice what the system gives in its own units.
* On Wayland, pixel distances from ``wl_pointer`` axis events. The finger
  phases ``1`` to ``3`` come from the axis source and the axis stop, which
  the compositor sends when the fingers lift, on a seat of version 5 or
  later. The coasting phases ``4`` to ``6`` come from the terminal's own
  momentum scroller, so phase ``4`` follows phase ``3`` at once. Phase ``7``
  is sent when the coasting is interrupted, by fingers coming back down for
  example, or when the pointer leaves the window while the fingers are still
  scrolling.
* On X11, pixel distances from XInput 2 smooth scrolling where available,
  otherwise lines converted to pixels with ``src=0``, and the coasting
  phases ``4`` to ``7`` from the terminal's own momentum scroller. The X
  server does not say when the fingers lift, which the scroller guesses
  from a pause, so the finger phases ``1`` to ``3`` are not reported.
