Low latency protocol
=======================

.. versionadded:: 0.50.0

A terminal does not show output the moment it arrives. It waits a few
milliseconds for more, so that a burst of output is parsed and drawn once
rather than many times, and it draws at a steady rate rather than after every
write. For a shell or an editor this costs nothing noticeable and saves a lot
of CPU. For a program drawing a stroke as the pen moves, or moving a view
under a finger, every one of those milliseconds is felt. The low latency
protocol lets such a program ask the terminal to give up that batching for the
duration of the interaction. It is an open terminal extension in the manner of
the :doc:`tablet-protocol`: small, unobtrusive, easy to implement, and no
change to what the TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``latency`` selector::

    <OSC> 777 ; latency ; v=1 : op=query : id=42 <ST>

They follow the rules every OSC 777 extension shares, which
:doc:`extension-framing` gives: the syntax of the fields, which frames are
rejected and the units. ``v``, the protocol version, is ``1``, and ``op`` is
one of ``query``, ``cap`` and ``mode``. The terminal sends only replies, which
are never merged or dropped.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; latency ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal answers::

    <OSC> 777 ; latency ; v=1 : op=cap : id=42 : caps=1 : mode=0 : input=3000 : repaint=10000 <ST>

``caps`` is a bit set of what the terminal can do, currently always ``1`` for
the mode below, and ``mode`` is the current state of that mode. ``input`` is how long the terminal normally waits for more
output before parsing what it has, and ``repaint`` how long it normally waits
between drawing frames, both in microseconds and both ``0`` when the terminal
does not batch that way at all. A program compares them with the time it has
to spare to decide whether turning the mode on is worth the CPU. A terminal
that does not support the protocol ignores the query, so a program must time
out and carry on without it.

Mode
--------

The mode is off by default and turned on per terminal window with::

    <OSC> 777 ; latency ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. While it is on, the terminal parses and draws the
program's output as soon as it arrives instead of waiting for more, and it
delivers the user's input to the program as soon as it has it. What the mode
does not change is the wait for the display: a terminal that synchronizes
with the refresh of the monitor still does so, and a frame still reaches the
screen no sooner than the next refresh. The :doc:`frame-protocol` tells a
program when that was.

The mode is local to the window and is reset by ``RIS``. It costs CPU, since
small writes that would have been coalesced are each parsed and drawn on
their own, so it is meant for the duration of an interaction, a stroke or a
drag, not for the lifetime of a program. Programs must turn it off when they
exit, suspend or fail, and turn it back on when resumed. Multiplexers and
relays keep it with the rest of the terminal state and turn it off when
detaching; one that cannot honour it simply keeps the state and passes the
query on. A terminal may let its user refuse the mode, for every program or
for some. A refused mode reads back as off and changes nothing, so a program
reads the mode back rather than assume it was granted.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; latency ; v=1 : op=mode : mode=1 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

In kitty
------------

The two times reported are the :opt:`input_delay` and :opt:`repaint_delay`
options. While a window has the mode on, output arriving from its program
wakes the terminal immediately and is parsed without waiting for the input
delay, and the window is drawn on the same tick. The repaint delay already
does not apply to output in kitty, so turning the mode on changes only the
input side. Input to the program is written to it as soon as it is produced,
with or without the mode.
