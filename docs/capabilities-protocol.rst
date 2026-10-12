Extension capabilities protocol
==================================

.. versionadded:: 0.50.0

A family of terminal extensions share one framing: ``OSC 777`` followed by a
selector naming the extension, a protocol version and ``key=value`` fields.
The tablet pointer, scroll, gesture and frame presentation protocols are
written this way. Each of them can be probed with its own ``query``, but a
program at the far end of a slow link pays a round trip per probe, and a
program resuming after a reconnection through a relay wants to know which of
the modes it had turned on are still in effect. This protocol answers both
with one exchange. It is an open terminal extension like the others: small,
unobtrusive, easy to implement, and no change to what the TTY is.

Framing
-------------

Messages are ``OSC 777`` with the ``caps`` selector::

    <OSC> 777 ; caps ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal integers that carry no leading ``+``. A
message with a missing required field or an unknown version is ignored as a
whole and never reaches a program as keystrokes. Spaces in the examples below
are for clarity only.

Listing the extensions
-------------------------

A program asks which selectors the terminal speaks::

    <OSC> 777 ; caps ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. The terminal answers::

    <OSC> 777 ; caps ; v=1 : op=cap : id=42 : caps=1 : ext=caps.1,frame.1,gesture.1 : media=d,f,t,s : format=24,32,100 <ST>

``caps`` is a bit set of what the terminal can report, currently always
``1`` for the listing. ``ext`` is a comma separated list, in no particular
order, of every selector the terminal accepts, each followed by a period and
the highest version of its protocol the terminal speaks. ``caps.1`` is always
among them. The list says only that a selector is understood; what it can do
with the display and the input devices at hand is still learned from that
selector's own ``query``, which a program now sends only for the selectors it
intends to use, and may send in the same write as this query since replies
arrive in order.

The answer is the same for every window of a terminal and does not change
while the terminal runs, so a program needs it once. A terminal that does not
support this protocol ignores the query, so a program must time out and may
then fall back to probing the selectors it needs one at a time.

Graphics media and formats
-----------------------------

The same reply says which transmission media and pixel formats of the
:doc:`graphics protocol <graphics-protocol>` the terminal accepts. ``media``
lists the values of the ``t`` key: ``d`` direct, ``f`` a file, ``t`` a
temporary file, ``s`` shared memory, and any medium an extension adds, such
as ``g`` for a GPU surface. ``format`` lists the values of the ``f`` key:
``24`` RGB, ``32`` RGBA, ``100`` PNG, and any format an extension adds, such
as ``64`` for HDR images and ``200`` for vector images. Both describe what the
terminal accepts, not what is wise over a given connection, and the graphics
protocol's own query action (``a=q``) remains the check for one particular
image. A relay answers with what it can carry to the terminal behind it:
files, shared memory and GPU surfaces do not cross machines, so over a
network relay only ``d`` is available.

Reading a mode
-----------------

Most selectors have a per-window mode that a program turns on with
``op=mode : mode=1`` and off with ``mode=0``. A ``mode`` request without a
``mode`` field is a read, answered with the current state::

    <OSC> 777 ; frame ; v=1 : op=mode <ST>
    <OSC> 777 ; frame ; v=1 : op=mode : mode=1 <ST>

and the ``cap`` reply of every selector that has a mode carries a ``mode``
field with the same value, so a single ``query`` tells a program both what the
selector offers and whether its mode is on. The reply uses the version number
the request asked for. A selector the terminal does not speak answers neither,
which is what the listing above is for.

Relays and multiplexers
---------------------------

A multiplexer, or a relay that resynthesizes the screen rather than passing
bytes through, answers the listing itself with the intersection of the
selectors it can carry and the selectors the terminal behind it listed, so a
program never sees a selector that cannot reach the display. It keeps the
modes with the rest of the terminal state. A program that reconnects reads the
modes it depends on rather than assuming they survived, since the terminal at
the other end may have been reset with ``RIS`` in the meantime, and turns them
on again as needed.
