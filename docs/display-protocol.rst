Display protocol
==================

.. versionadded:: 0.50.0

A program that draws knows nothing about the screen its output ends up on:
whether it is a color LCD or sixteen levels of gray on e-ink, how much of the
color spectrum it covers, how bright it can go, how many device pixels a cell
has and how often it refreshes. Each of these changes what the best rendering
is, from the choice of a palette and a dithering strategy to whether animation
is worth doing at all. The display protocol lets a program ask, and be told
when the answer changes, for example because the window was moved to another
screen. It is an open terminal extension in the manner of the other kitty
protocols: small, unobtrusive, easy to implement, and no change to what the
TTY is.

Framing
-------------

Frames are ``OSC 777`` with the ``display`` selector::

    <OSC> 777 ; display ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order, with decimal numbers that carry no leading ``+``. A
frame with a missing required field or an unknown version is ignored as a
whole and never reaches a program as keystrokes. Spaces in the examples below
are for clarity only.

Every frame has ``v``, the protocol version, which is ``1``, and ``op``, one
of ``query``, ``cap``, ``mode`` and ``event``.

Query
-------------

A program asks about the display its window is on::

    <OSC> 777 ; display ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; display ; v=1 : op=cap : id=42 : mode=0 : kind=lcd : color=rgb : bits=8 : gamut=p3 : headroom=1 : scale=2 : period=8333 : ppi=254 <ST>

A terminal that does not support the protocol ignores the query, so a program
must time out and fall back to assuming an ordinary color display.

The fields of the reply are:

``mode``
    The current state of the mode described below, ``0`` or ``1``.

``kind``
    One of ``lcd``, ``oled``, ``eink`` and ``unknown``. On e-ink, updates are
    slow and leave ghosts, so a program avoids animation and smooth scrolling
    and redraws in large, infrequent steps.

``color``
    One of ``rgb``, ``gray`` and ``mono``.

``bits``
    Bits per color channel, ``0`` when unknown. Sixteen levels of gray are
    ``color=gray : bits=4``. Together with ``color`` this is what a program
    needs to choose a palette and whether and how to dither; antialiasing
    works fine with a few levels and is not what this field decides.

``gamut``
    One of ``srgb``, ``p3``, ``rec2020`` and ``unknown``: the widest color
    space the display covers.

``headroom``
    How much brighter than the white of normal text the terminal can show,
    as a multiple: ``1`` when there is no extra brightness. See the HDR
    brightness protocol for how to use it.

``scale``
    Device pixels per logical pixel, so a program that works in pixels knows
    how fine its output can be. ``0`` when unknown.

``period``
    The refresh period of the display in microseconds, ``0`` when unknown.

``ppi``
    Physical pixels per inch, ``0`` when unknown.

Values the terminal cannot determine are ``unknown`` or ``0``, never guessed.
A terminal that knows nothing about its display, a multiplexer that is not
attached, for example, answers with every field unknown and the program is no
worse off than before it asked.

Mode
--------

A program that wants to be told about changes turns them on per terminal
window with::

    <OSC> 777 ; display ; v=1 : op=mode : mode=1 <ST>

and off with ``mode=0``. The mode is local to the window and is reset by
``RIS``. Programs must turn it off when they exit, suspend or fail, and turn
it back on when resumed. Multiplexers keep it with the rest of the terminal
state and turn it off when detaching. There is no user setting that overrides
the program's choice.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; display ; v=1 : op=mode : mode=1 <ST>

A program resuming after a reconnection reads the mode to learn whether it
survived, rather than assuming it did.

Events
-----------

Turning the mode on sends one event with the current values, so a program
needs no separate query. After that, while the mode is on, the terminal sends
one event whenever any field changes: the window was moved to a display with
a different scale or refresh rate, the display's brightness setting changed
the headroom, its color profile was switched::

    <OSC> 777 ; display ; v=1 : op=event : kind=lcd : color=rgb : bits=8 : gamut=srgb : headroom=1 : scale=1 : period=16666 : ppi=96 <ST>

The fields are those of the ``cap`` reply, without ``id`` and ``mode``.
Changes are relative to the last event sent, so turning the mode off and on
again reports the current values once and then only changes. A change can be
reported a short while after it happens, and a program that has turned the
mode off may still receive an event that was already on its way.

Relays and multiplexers
---------------------------

A relay such as a mosh-like client, that draws the terminal's screen on a
display of its own, answers queries for the display it has, since the
terminal at the far end cannot know it. When the relay reconnects to a
different client it sends one event to every window with the mode on, so a
program that laid out its output for a phone can redo it for a desktop, and
the other way round.

A multiplexer answers for the display of the client it is attached to, with
every field unknown while detached, and sends an event when attached to a
client with a different display.

Configuration
----------------

The operating system reports most of these values, but not all. Nothing tells
a terminal that it is on e-ink, so in kitty the :opt:`display_info` option
declares whatever the OS cannot, overriding detection. Currently, kitty reports
``kind`` and ``gamut`` only on macOS. ``headroom`` is the headroom of the
:doc:`hdr-protocol`, after the cap of :opt:`hdr_max_headroom`, so it is ``1``
unless :opt:`hdr` is enabled, which so far only macOS supports.
