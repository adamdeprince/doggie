Tablet pointer protocol
==========================

.. versionadded:: 0.50.0

Pens and fingers carry far more than the mouse protocol can express:
pressure, tilt, rotation of the barrel, which end of the pen is in use,
hovering, several fingers at once, the shape of each finger on the glass.
A tablet has keys, rings and dials of its own beside the pen. The tablet
pointer protocol is an open terminal extension that reports all of it, from
graphics tablets, pen displays, touchscreens and touchpads, with room for
whatever a device measures. It belongs to no terminal: silkie (this
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
of ``query``, ``cap``, ``mode``, ``device``, ``label`` and ``event``. A frame
with any other version is ignored.

The protocol grows without a new version. A program ignores a frame whose
``op`` it does not know, a report whose ``kind`` it does not know and any
field it does not know, and treats a ``tool`` value it does not know as
``0``. A new kind of report is sent only to a program that asked for it with
a mode bit of its own, so a program is never sent what it was not written
for. Only a change in the meaning of something that exists needs a new
version.

Discovery
-------------

A program asks the terminal whether it supports the protocol::

    <OSC> 777 ; tablet-pointer ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal
answers::

    <OSC> 777 ; tablet-pointer ; v=1 : op=cap : id=42 : caps=101 : mode=0 : w=1200 : h=800 : cw=12 : ch=24 <ST>

``caps`` is a bit set of what the terminal can report:

======= ===================================================================
``1``   Tools
``2``   Fingers on a touchscreen
``4``   Fingers on a touchpad
``8``   The shape of a finger contact
``16``  Pads
``32``  Tool actions
``64``  The hardware identifiers of tools and pads
``128`` Estimated and predicted samples
======= ===================================================================

It describes the terminal on the system it runs on, not the hardware
attached right now. A bit is set only for what the terminal knows it can
report. Where the system does not say beforehand whether it gives the shape
of a contact, bit ``8`` stays clear until a contact has had one, so a
program does not wait for the bit: a report has a shape when its ``valid``
says so. What goes beyond tools and fingers, the last four, is sent only
when asked for with the mode. ``mode`` is the current state of the
mode described below. ``w,h`` are the size of the cell area in pixels (1 to
65535) and ``cw,ch`` the cell size (1 to 4096). A program queries again
after a resize. A terminal that does not support the protocol ignores the
query, so a program must time out and fall back to mouse reporting. A query
does not change the mode.

Mode
--------

Reports are off by default and turned on per terminal window with::

    <OSC> 777 ; tablet-pointer ; v=1 : op=mode : mode=3 <ST>

``mode`` is a bit set of what the program wants, and ``0`` turns everything
off:

======= ===================================================================
``1``   Reports of tools
``2``   Reports of fingers
``4``   Reports of pads, see `Pads`_
``8``   The hardware identifiers of tools and pads, see `Devices`_
``16``  Reports of tool actions, see `Tool actions`_
``32``  Estimated and predicted samples, see `Estimates and predictions`_
======= ===================================================================

While bit ``1`` or ``2`` is on, that kind of input over the window is
reported with this protocol instead of as mouse events, so with ``mode=1`` a
pen draws while a finger still taps and scrolls as a mouse, and with
``mode=3`` a tap is not a click and a drag does not select. A physical
mouse, and the mouse and scroll events a touchpad produces by itself,
continue to use whatever mouse reporting the program asked for. Programs
that merely want pen input to act as a mouse need not use the protocol at
all. Bit ``4`` takes nothing away: what the system itself does with the
controls of a pad, such as a shortcut the user has put on a key, goes on.

The mode is local to the window, is reset by ``RIS``, and changing it
cancels every active contact and lets go of every held key of a pad.
Programs must turn it off when they exit, suspend or fail, and turn it back
on when resumed. Multiplexers keep it with the rest of the terminal state,
restore it on reconnect, and turn it off when detaching. There is no user
setting that overrides the program's choice.

A ``mode`` request without a ``mode`` field reads the state instead of
changing it, and is answered with::

    <OSC> 777 ; tablet-pointer ; v=1 : op=mode : mode=3 <ST>

A terminal keeps only the bits it supports, so a program that asked for
more than the terminal has finds out by reading the mode back. A program
resuming after a reconnection reads the mode to learn whether it survived,
rather than assuming it did.

Devices
-----------

Before the first report of a tool, each time the tool comes into proximity
over a window that has tool reports on, the terminal describes it::

    <OSC> 777 ; tablet-pointer ; v=1 : op=device : device=3 : kind=1 : tool=1 : axes=7 : name=V2Fjb20gSW50dW9zIFBybyBN <ST>

``device`` is the id the reports of that tool carry, ``kind`` is ``1`` and
``tool`` is the type of the tool, with the values it has in reports. The
other fields are present when the system provides them:

================ ==================================================================
``axes``         The measurements the reports of this tool can carry, a bit set
                 with the bits of ``valid``, so a program can set up a brush
                 before the first stroke
``name``         The name of the tablet the tool is on, or of the tool itself,
                 at most 127 bytes of UTF-8 encoded as base64 with padding
``serial``       The serial number of the tool, an unsigned 64 bit integer
``hwid``         The hardware id of the tool, an unsigned 64 bit integer; on
                 Wacom tablets it tells the model of the pen
``vid``, ``pid`` The vendor and product ids of the tablet, unsigned 32 bit
                 integers
``bat``          The charge of the battery of the tool, ``0`` to ``100``
================ ==================================================================

``serial``, ``hwid``, ``vid`` and ``pid`` are the hardware identifiers, and
they are sent only while mode bit ``8`` is on. A serial number names one
physical pen, and so its owner, to every program that turns reports on,
including one on a remote host at the far end of an ssh session. A program
that keeps settings per pen asks for them; a program that only draws has no
need to know whose pen it is.

The description is sent again when the tool comes back after leaving
proximity, when it moves over another window, and when the program changes
the mode while the tool is in proximity. A program must not depend on
getting one: a terminal that knows nothing about a tool beyond its reports
need not describe it. A pad is described in the same way, with ``kind=3``
and fields of its own, see `Pads`_. The device of a finger report is not
described.

Reports
-----------

A report is a single frame per event::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=1 : phase=1 : device=3 : t=408211 : contact=0 : x=25600 : y=51200 : buttons=1 : mods=0 : tool=1 : valid=3 : p=32000 : tx=-1200 : ty=600 <ST>

In the reports of tools and fingers ``kind``, ``phase``, ``device``, ``t``,
``contact``, ``x`` and ``y`` are required. The other fields in this table
default to zero, except ``tool``, which defaults to ``1``:

================ ==================================================================
``kind``         ``1`` tool, ``2`` finger. ``3`` is a pad and ``4`` a tool
                 action, which have fields of their own, see `Pads`_ and
                 `Tool actions`_
``phase``        ``0`` hover, ``1`` down, ``2`` move, ``3`` up, ``4`` cancel,
                 ``5`` the tool left proximity, ``6`` frame, see `Fingers`_,
                 ``7`` correction, see `Estimates and predictions`_
``device``       Identifies the tool or touch device for as long as it is in
                 proximity, a non-negative 31 bit integer, ``0`` when the
                 system does not tell devices apart
``t``            The time of the event in milliseconds on a monotonic clock of
                 the terminal's choosing, or of its delivery when the system
                 does not time stamp it, useful only for differences between
                 reports
``tu``           Microseconds past ``t``, ``0`` to ``999``, present only when
                 the system stamps events more finely than a millisecond. A
                 report without it is on a grid of whole milliseconds
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
                 ``4`` pencil, ``5`` airbrush, ``6`` mouse, ``7`` lens, ``8``
                 totem, see `Totems`_
``valid``        The measurements the report carries, a bit set, see below
``src``          For a finger, ``1`` when it is on a touchpad rather than on
                 the screen; absent otherwise
``stage``        For a finger on a touchpad that measures force, how hard the
                 pad is pressed, see `Fingers`_
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
``major``, ``minor``,   128   The shape of a finger or a totem on the screen: the
``angle``                     axes of the ellipse of the contact in 1/256 pixel
                              and its orientation in hundredths of a degree,
                              clockwise from the vertical
======================= ===== ====================================================

Fingers
~~~~~~~~~~

Finger reports have ``kind=2``, ``tool=0``, ``buttons=1`` while down, one
``contact`` per finger, and usually no measurements beyond the shape. A
touch system delivers all the fingers that moved together before any of them
is acted on, and the terminal keeps that grouping: after the reports of one
such group it sends a frame report, which carries only ``kind=2``,
``phase=6``, ``device`` and ``t``, with ``tu`` when the reports have it::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=1 : device=0 : t=408211 : contact=0 : x=25600 : y=51200 : buttons=1 : mods=0 : tool=0 : valid=0 <ST>
    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=1 : device=0 : t=408211 : contact=1 : x=38400 : y=51200 : buttons=1 : mods=0 : tool=0 : valid=0 <ST>
    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=2 : phase=6 : device=0 : t=408211 <ST>

A program that cares about the relation between fingers, as a pinch
recognizer does, collects reports until the frame and applies them at once.
A program that paints one stroke per finger can act on each report as it
comes. Frames are sent for fingers only; a tool reports one contact at a
time.

A touchpad that measures how hard it is pressed reports that with ``p`` and
``stage``. The force is on the pad as a whole, not under each finger, so
every finger on the pad carries the same two values, and when only the force
changes the fingers are reported again as a ``move`` that did not move.
``stage`` is ``0`` while the pad is pressed less than a click, ``1`` for a
click and ``2`` for a click pressed harder, and ``p`` runs from 0 to 65535
within each stage, so it drops back when the stage goes up.

Tool actions
~~~~~~~~~~~~~~~

Some things done with a tool are not a button held down: a double tap on the
barrel of a pen, a squeeze of it, a click of the button on its end. While
mode bit ``16`` is on they are reported with ``kind=4``::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=4 : device=3 : t=408211 : action=1 : x=25600 : y=51200 : mods=0 <ST>

================ ==================================================================
``device``       The tool, as in its reports, ``0`` when the system does not
                 say which tool it was
``t``, ``tu``    The time of the action, as in the other reports
``action``       ``1`` a double tap on the barrel, ``2`` a squeeze, ``3`` a
                 click of the button on the end of the tool, ``4`` a double
                 click of that button, ``5`` that button pressed and held
``state``        For an action that lasts, as a squeeze does, ``1`` when it
                 begins and ``0`` when it ends; absent for the others
``x``, ``y``     The position of the pointer, as in a tool report
``mods``         As in a tool report
================ ==================================================================

``device``, ``t``, ``action``, ``x``, ``y`` and ``mods`` are always present.
An action has no ``phase`` and no ``contact`` and belongs to no stroke. It
goes to the window that has a stroke of the tool captured, and otherwise to
the window under the pointer. What an action does is the program's choice; a
double tap usually switches between the pen and the eraser. A program
ignores an ``action`` it does not know.

Pads
~~~~~~~

A pad is the keys, touch rings, touch strips and dials on the body of a
tablet, or on a remote of their own. While mode bit ``4`` is on they are
reported with ``kind=3``, one control to a report::

    <OSC> 777 ; tablet-pointer ; v=1 : op=event : kind=3 : device=5 : t=408211 : mods=0 : ring=0 : angle=9000 : src=1 <ST>

``device``, ``t`` and ``mods`` are always present and mean what they do in
the other reports, as does ``tu``. A pad report has no ``phase``, no
``contact`` and no position. The rest of it is one of these:

============================ ======================================================
``button``, ``state``        A key went down, ``state=1``, or came up, ``state=0``
``ring``, ``angle``          Where the finger is on a touch ring, in hundredths of
                             a degree, ``0`` to ``35999``, clockwise from the top
                             of the ring as the tablet is turned
``strip``, ``pos``           Where the finger is on a touch strip, ``0`` at its
                             top or left end to ``65535`` at the other
``ring`` or ``strip``,       The finger lifted off the ring or strip, in place of
``stop=1``                   ``angle`` or ``pos``. What comes next from that
                             control begins a new movement, so the jump from the
                             last position to the next one is not a turn
``dial``, ``delta``          How far a dial was turned since its last report,
                             signed, ``120`` for each detent and less for a dial
                             that turns smoothly. A dial has no position
``group``, ``mode``          A group of controls went into another mode
============================ ======================================================

The value of ``button``, ``ring``, ``strip`` and ``dial`` is the number of
the control, each kind counted from zero across the pad in the order the
system lists them. ``src=1`` is added to a ring or strip report when the
system says a finger is what moves it.

The controls of a pad are in groups, and each group has a mode, a number
from zero that the user changes on the pad, usually with a key the system
keeps for that, and that the pad may show with a light. A mode is nothing
but a number: it is there so that the same controls can do one set of things
in one mode and another in the next, and the program decides what. A
``group`` report gives the number of the group and the mode it is now in.
Terminals also send one for every group when the pad comes to the window, so
a program does not have to wait for the user to switch before it knows.

Pad reports go to the window that has the keyboard focus, not to the one
under the pointer. Before the first of them, each time the pad comes to a
window that has pad reports on, the terminal describes the pad::

    <OSC> 777 ; tablet-pointer ; v=1 : op=device : device=5 : kind=3 : buttons=9 : rings=1 : strips=0 : dials=0 : groups=1 : modes=4 : name=V2Fjb20gSW50dW9zNSB0b3VjaCBNIFBlbg== <ST>

================ ==================================================================
``buttons``,     How many keys, rings, strips and dials the pad has
``rings``,
``strips``,
``dials``
``groups``       How many groups its controls are in
``modes``        How many modes each group has, separated by commas, in the order
                 of the groups
``mode``         The mode each group is in, in the same form, present when the
                 terminal knows it at that moment
``name``         The name of the tablet the pad belongs to, as for a tool
``vid``, ``pid`` The ids of that tablet, sent only while mode bit ``8`` is on
================ ==================================================================

A pad holds nothing open except its keys. When the mode is changed, the
terminal is reset, the keyboard focus goes to another window or the pad goes
away, the terminal reports every key that is down as released,
``state=0``, with the ``t`` of its press, and the release that the pad makes
later is not reported. A key that was already down when the reports began
never reports its release. A program must tolerate a release for a key it
does not have down.

A program can say what a control does at the moment, for the system to show
the user where it has a display for that, such as an overlay of the layout
of the pad::

    <OSC> 777 ; tablet-pointer ; v=1 : op=label : device=5 : button=2 : text=VW5kbw== <ST>

``device`` is the pad and exactly one of ``button``, ``ring``, ``strip`` and
``dial`` names the control, with a number from ``0`` to ``255``. ``text`` is
at most 60 bytes of UTF-8 without control characters, encoded as base64 with
padding, so the frame stays within its 127 bytes; a ``text`` that is empty or
left out takes the label away. A label belongs to the mode the group of the
control is in, so a program sets its labels when the pad is described and
again after each ``group`` report. It is accepted only from the program the
pad is reporting to, there is no reply, and a terminal with nowhere to show
labels ignores it.

Totems
~~~~~~~~~

A totem, ``tool=8``, is a dial or puck that stands on the screen and is
tracked by it. It is reported as a tool: ``x,y`` is its centre, ``twist``
how far it has been turned, and the contact shape, with ``valid`` bit
``128``, the area of the screen it covers. Pressing it down is button ``1``,
so a totem that is pressed and turned is a stroke whose ``twist`` changes.

Estimates and predictions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some systems hand over a sample before all of it has been measured: the
pressure of a pen can arrive by radio after the position of its tip, and
until it does the system fills in an estimate. Some also predict, giving
samples for where the tool is about to be, which a program draws to hide
the delay to the screen and then replaces. A terminal that can pass these on
does so only while mode bit ``32`` is on, with three more fields in the
reports of tools and fingers:

================ ==================================================================
``seq``          A count of the samples of this device, an unsigned 32 bit
                 integer that wraps, by which a later report names an earlier
                 one
``est``          The measurements in this report that are estimates, a bit set
                 with the bits of ``valid``
``pred``         ``1`` for a predicted sample; absent otherwise
================ ==================================================================

An estimate is put right by a correction: a report with ``phase=7`` and the
``seq`` of the report it corrects, which repeats that report with the
measured values. It is not a new point of the stroke. Its own ``est`` names
what is still an estimate, and is absent once nothing is. A correction can
come after the ``up`` of its stroke, and it may never come, in which case
the estimate stands.

A predicted sample is not part of the stroke. A program that draws it takes
every predicted sample of a contact away again when the next report of that
contact arrives that is not predicted. A predicted sample has no ``seq`` and
is never corrected.

Without bit ``32`` a terminal sends an estimate as an ordinary value and
sends no corrections and no predictions, so a program that knows nothing of
this draws what it is given.

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
when the system reports it, sends phase ``5``. That report goes to the
window that was last told of the tool, wherever the tool was when it left:
a pen whose stroke was dragged out of the window and ended there is over no
window, and the program still has to learn that it is gone.

The terminal cancels contacts, with ``buttons=0`` and ``p=0``, when the mode
changes, the terminal is reset, the window's size in cells changes, the
system takes the fingers over for a gesture of its own, or the device goes
away. After a cancel the rest of that stroke is not reported, not even its
``up``.
Programs must tolerate a lost ``hover``, a repeated cancel, and a fresh
``down`` for a contact they still have open, which replaces the earlier
stroke.

A multiplexer translates ``x,y`` of on-screen contacts by the pane's origin
(borders included) and scroll offset, forwards every other field unchanged,
delivers each stroke and each finger sequence only to the pane it began in,
and cancels contacts when panes move or resize. It keeps the mode of each
pane and asks the terminal for the union of them. It keeps the last
description of each tool in proximity and sends it to a pane before that
pane's first report of the tool, without the hardware identifiers unless
that pane asked for them. A tool action goes to the pane that has a stroke
of the tool, and otherwise to the pane under the pointer, with ``x,y``
translated as for a contact. Corrections follow the report they correct to
its pane, and ``seq`` is forwarded unchanged. Pad reports go unchanged to
the pane that has the focus, after the description of the pad, and when the
focus moves to another pane the keys that are down are reported released to
the pane it left. A label is passed on only from the pane the pad is
reporting to. A multiplexer or relay that
detaches or loses its connection while contacts are live sends ``cancel``
for each of them to the program, so a program never holds a dead contact,
and a relay that reconnects forwards nothing it did not see: the fingers
down at that moment are simply reported from their next ``down``.

Implementations
-------------------

* silkie, this fork of kitty: tools on macOS, Wayland and X11; fingers on
  the touchpad on macOS and on touchscreens on Wayland, with contact shape,
  and on X11, without; pads on Wayland; tool actions on macOS. ``kitty --debug-input`` logs the
  tablet, pad and touch events it sees.
* Inkline, Goblin Skiff and GoblinView carry a codec for an earlier draft of
  this protocol and are being brought up to this specification.

Implementation notes for silkie
----------------------------------

silkie reads tablets and touch devices through the window system, so a
program gets what the system reports. It keeps the mode bits ``1``, ``2``,
``4``, ``8`` and ``16``, and ``caps`` says which of them the system it runs
on can do anything for. None of the systems it runs on hands over estimates or
predictions, so it does not take bit ``32``, and it reports no totems and no
battery charge. ``tu`` is sent on macOS only: Wayland and X11 stamp tablet
and touch events in whole milliseconds.

* On macOS, tablet data arrives with the mouse events of the tablet driver.
  Tilt is scaled from the driver's fraction of maximum tilt assuming 60
  degrees, as Wacom tablets report, and ``z`` is the driver's absolute Z.
  While a program takes a tool's reports, AppKit's merging of tablet points
  is turned off, so every sample the tablet sends is reported. AppKit tells
  a pen, an eraser and a puck apart; the airbrush and the lens cursor of a
  Wacom tablet are recognised from the driver's own code for the tool. No
  name is known for the device frame. The one tool action is the double tap
  on an Apple Pencil paired with an iPad that the Mac uses as a display, and
  the system does not say which tool it came from, so ``device`` is ``0``
  unless a single tool is in proximity.
  Fingers are the indirect touches of the trackpad, as AppKit reports them
  to the content view, so a finger resting on the pad is not reported; the
  pad size is the device size AppKit gives, taken to be in points at 72 to
  the inch. Trackpad fingers are reported alongside the mouse and scroll
  events the system makes from them. A trackpad that measures force gives
  ``p`` and ``stage`` once it has been pressed for the first time. The Wacom
  tool types, the double tap and the force are written from the
  documentation of AppKit and have not been tried with the hardware. There
  are no pad reports: AppKit has no events for the controls of a pad, which
  an application gets only through the request interface of Wacom's own
  driver.
* On Wayland, tools come through the ``tablet-v2`` protocol, which reports
  every measurement above, identifies the tool and names the tablet, and
  fingers through ``wl_touch``, with ``shape`` and ``orientation`` on a seat
  of version 6 or later whose compositor sends them, which sway and GNOME
  did not when this was written; ``caps`` claims the shape once a contact
  has had one. The pointer cursor
  follows a tool only on compositors with ``cursor-shape-v1``. GNOME applies
  its own stylus button mapping first (by default the lower button is the
  middle button), sway passes the buttons through. A tool does not move the
  pointer as far as silkie is concerned: a compositor can give tablets a
  cursor of their own, so what is reported at the pointer, such as a scroll,
  stays where the pointer was. Pads come through
  ``tablet-v2`` as well: keys, rings, strips and modes from its first
  version and dials from its second, which the compositor has to offer, and
  a label is passed to the compositor as the feedback for that control. The
  ``name`` and ids of a pad are those of the tablet it is attached to.
  ``caps`` claims tools and pads only on a compositor that has the protocol.
  Pads have been tried against a stand-in for the compositor that sends what
  wlroots sends, not with a tablet.
* On X11, tools come through XInput 2 devices whose names include the tool
  type, as the libinput and wacom drivers name them; that name is the
  ``name`` of the device frame, and the ids of the tablet are not known.
  ``tangent`` carries the device's wheel axis and ``twist`` its rotary Z
  axis. The position of a tool is made from the position its own device
  reports, scaled to the screen as the server does it, because the server
  puts the position of the pointer before an event into that event, which
  is where the tool was one report earlier. The X server does not report a
  tool leaving proximity, so phase
  ``5`` arrives only when the device goes away. Xwayland's tablet devices
  are recognised too, but under GNOME no motion reached them in testing; use
  the Wayland backend there. Fingers on a touchscreen come through the touch
  events of XInput 2.2, and ``caps`` claims them when the server has that
  version. X reports each finger in an event of its own, so every finger
  report is followed by a frame report of its own and fingers that moved
  together are not grouped. There is no contact shape, a touch the system
  takes over ends with an ordinary ``up`` since the server does not say that
  it was taken, and the fingers on a touchpad are not reported. The server
  also moves the pointer to where the first finger lands, which is not passed
  on as mouse reports. This was tried against Xwayland, which makes these
  events from the touches of its compositor, not with a touchscreen. Pads
  are not reported on X11: the wacom driver has a device for the pad, which
  is not read.
