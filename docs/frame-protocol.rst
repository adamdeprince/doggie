Frame presentation protocol
==============================

.. versionadded:: 0.50.0

Synchronized updates (private mode 2026) let a program hand the terminal a
whole frame at once, so that it is shown without tearing. What the program
cannot learn is when that frame reached the screen, so programs that animate,
draw strokes as they are made, or play video pace themselves with timers and
either waste work on frames the display never shows or lag behind it. The
frame presentation protocol is the other half: a report after each frame the
terminal presents that contains output from the program. It is an open
terminal extension in the manner of the :doc:`tablet-protocol`: small,
unobtrusive, easy to implement, and no change to what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``frame`` selector::

    <OSC> 777 ; frame ; v=1 : op=query : id=42 <ST>

They follow the rules every OSC 777 extension shares, which
:doc:`extension-framing` gives: the syntax of the fields, which frames are
rejected, the units and the clock. ``v``, the protocol version, is ``1``, and
``op`` is one of ``query``, ``cap``, ``mode`` and ``event``.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; frame ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal answers::

    <OSC> 777 ; frame ; v=1 : op=cap : id=42 : caps=1 : mode=0 : period=8333 <ST>

``caps`` is a bit set of what the terminal can report, currently always
``1`` for presentation events. ``mode`` is the current state of the mode
described below. ``period`` is the refresh period of the display
the window is on, in microseconds, or ``0`` when the terminal does not know
it. It changes when the window moves to another display, so a program that
cares queries again from time to time, or simply uses the value carried by
every event. A terminal that does not support the protocol ignores the query,
so a program must time out and fall back to timers.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; frame ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. Turning the mode on resets the sequence counter. The
mode is local to the window and is reset by ``RIS``. Programs must turn it
off when they exit, suspend or fail, and turn it back on when resumed.
Multiplexers keep it with the rest of the terminal state and turn it off when
detaching. A terminal may let its user refuse the mode, for every program or
for some. A refused mode reads back as off and no frame is reported, so a
program reads the mode back rather than assume it was granted.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; frame ; v=1 : op=mode : mode=1 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

Reports
-----------

While the mode is on, the terminal sends one report each time it presents a
frame to the display that contains output the program wrote since the previous
report::

    <OSC> 777 ; frame ; v=1 : op=event : seq=17 : t=408211 : tu=73 : period=8333 <ST>

``seq`` counts reports since the mode was turned on. ``t`` is the time the
frame was handed to the display system, in milliseconds on the clock the
terminal uses for every extension, see :doc:`extension-framing`, so that it
can be set against the ``t`` of the input a program drew the frame for.
``tu`` is the microseconds past ``t``, ``0`` to ``999``, present when the
terminal measures the time that finely. This is not the time the frame was
shown, which is the next refresh of the display or later; a later version of
the protocol may add that. ``period`` is the refresh period in microseconds
as in the ``cap`` reply.

Every report stands for a frame, so none is ever merged with another or
dropped, by the terminal or by a relay, see :doc:`extension-framing`.

A frame is reported once, however much output it contains, and a program that
writes nothing receives nothing, so an idle program is never woken. The
command that turns the mode on is itself output, so the first report follows
the next presented frame and tells the program the period without a query. Output
that does not change what is on screen may still be followed by a report,
since the terminal counts output, not visible change. When the window is
hidden or on an inactive tab no frames are presented and no reports are sent,
so a program must never block indefinitely waiting for one: wait with a
timeout, a few refresh periods long, and carry on.

Pacing with synchronized updates
-------------------------------------

The intended use is a render loop that submits a frame inside ``CSI ? 2026 h``
and ``CSI ? 2026 l``, then waits for the report before starting the next one.
With reports arriving once per presented frame, the program draws exactly as
fast as the display shows and no faster, and the difference between the ``t``
of consecutive reports tells it the frame rate it is actually achieving. A
program that renders faster than the display should drop or merge frames
rather than queue them, since the terminal shows only the most recent output
at each presentation.

Reports are written to the program's input like keystrokes. A program must
read its input while waiting for a report, since other input, such as key
presses, arrives in the same stream.
