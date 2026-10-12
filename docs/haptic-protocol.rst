Haptic feedback protocol
==========================

.. versionadded:: 0.50.0

Trackpads on Apple laptops and the Magic Trackpad can tap back at the user.
Applications use that for the moment a dragged object snaps into alignment,
for the end of a gesture, or for a pen touching down. The haptic feedback
protocol lets a terminal program ask for such a tap. It is small on purpose:
a program asks whether taps are available and then asks for one, and a
terminal without the hardware, or without the protocol, does nothing.

Framing
-------------

Frames are ``OSC 777`` with the ``haptic`` selector::

    <OSC> 777 ; haptic ; <fields> <ST>

``<OSC>`` is ``<ESC> ]`` and ``<ST>`` is ``<ESC> \``; ``BEL`` is also
accepted as a terminator. Fields are ASCII ``key=value`` pairs separated by
colons, in any order. Keys are case sensitive. Every frame has ``v``, the
protocol version, which must be ``1``, and ``op``, one of ``query``, ``cap``
and ``play``. A frame with a field that is not ``key=value``, an unknown
version, an unknown ``op`` or a missing required field is ignored as a
whole and never reaches a program as keystrokes; unknown keys are ignored.
Spaces in the examples below are for clarity only.

Discovery
-------------

A program asks whether the terminal can play feedback::

    <OSC> 777 ; haptic ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal answers::

    <OSC> 777 ; haptic ; v=1 : op=cap : id=42 : caps=1 <ST>

``caps`` is a bit set: ``1`` means feedback can be played right now, on this
machine, and the user has not turned it off. A terminal that does not
support the protocol ignores the query, so a program must time out. The
answer can change, for example when the user changes the setting, so a
program that has been told ``caps=0`` may ask again later.

Playing
-----------

::

    <OSC> 777 ; haptic ; v=1 : op=play : pattern=generic <ST>

``pattern`` is one of ``generic``, a single tap for a drop or a touch,
``alignment``, the tap used when a dragged object snaps into place, and
``level``, the tap used when a pressure sensitive control changes level.
A terminal plays feedback only for the focused window and at most once every
50 milliseconds per OS window, and silently drops the rest. There is no
reply.

In kitty the user turns feedback off with :opt:`haptic_feedback`. Feedback is
available on macOS; on other platforms kitty answers ``caps=0`` and ignores
``play``.
