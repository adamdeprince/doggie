Haptic feedback protocol
==========================

.. versionadded:: 0.50.0

Some input devices can tap back at the user: the trackpads of Apple laptops
and the Magic Trackpad, pens such as the Surface Slim Pen 2 and the Apple
Pencil Pro, and dials such as the Surface Dial. Applications use that for the
moment a dragged object snaps into alignment, for the end of a gesture, for a
pen touching down, and on a pen for the drag of a pencil or a brush over
paper. The haptic feedback protocol lets a terminal program ask for the same.
It is small on purpose: a program asks what can be played, then asks for a
tap, or starts and stops the feel of a tool. A terminal without the hardware,
or without the protocol, does nothing.

Framing
-------------

Frames are ``OSC 777`` with the ``haptic`` selector::

    <OSC> 777 ; haptic ; v=1 : op=play : pattern=alignment <ST>

They follow the rules every OSC 777 extension shares, which
:doc:`extension-framing` gives: the syntax of the fields, which frames are
rejected and the units. ``v``, the protocol version, is ``1``, and ``op`` is
one of ``query``, ``cap``, ``play``, ``start`` and ``stop``. A request whose
``op`` is not one of these, or with a value that is not one of those defined
for its key, is ignored as a whole as well. The terminal sends only replies,
which are never merged or dropped.

Feedback is played on a *target*, named by the ``target`` field of the
requests below: ``trackpad``, which is what is meant when the field is
absent, ``pen``, the pen in use on a tablet or a screen, or ``dial``. A
request for a target the terminal cannot play on is dropped.

Discovery
-------------

A program asks what the terminal can play::

    <OSC> 777 ; haptic ; v=1 : op=query : id=42 <ST>

``id`` is a non-negative 31 bit integer of the program's choosing, echoed in
the reply so replies can be matched to queries. A supporting terminal answers::

    <OSC> 777 ; haptic ; v=1 : op=cap : id=42 : caps=1 <ST>

``caps`` is a bit set. ``1``, ``2`` and ``4`` mean that taps can be played
on the trackpad, on a pen and on a dial: right now, on this machine, and the
user has not turned them off. ``8`` means that continuous feedback, described
below, can be played on a pen. A terminal that does not support the protocol
ignores the query, so a program must time out. The answer can change, when a
pen is paired or the user changes a setting, so a program that was told a bit
is clear may ask again later.

Taps
-----------

::

    <OSC> 777 ; haptic ; v=1 : op=play : pattern=generic <ST>
    <OSC> 777 ; haptic ; v=1 : op=play : target=pen : pattern=complete <ST>

``pattern`` is required and is one of:

================ ==================================================================
``generic``      A single tap, for a drop or a touch
``alignment``    The tap used when a dragged object snaps into place
``level``        The tap used when a pressure sensitive control changes level
``click``        The tap of a button being pressed or a dial passing a detent
``complete``     The tap that says an action finished: a stroke was recognized as
                 a shape, a path was closed
================ ==================================================================

A terminal plays taps only for the focused window and at most once every 50
milliseconds per OS window, and silently drops the rest. There is no reply.

Continuous feedback
----------------------

A pen with a motor can make the glass feel like paper for as long as it
draws. A program starts that when a stroke begins and stops it when the
stroke ends::

    <OSC> 777 ; haptic ; v=1 : op=start : target=pen : pattern=pencil : intensity=60 <ST>
    <OSC> 777 ; haptic ; v=1 : op=stop : target=pen <ST>

``pattern`` is required for ``start`` and names the tool whose feel is
wanted: ``ink``, ``pencil``, ``marker``, ``brush`` or ``eraser``.
``intensity`` is a percent of full strength, ``0`` to ``100``, and ``100``
when absent. A ``start`` while feedback is playing on that target replaces
the pattern and the intensity, which is how a program follows the pressure
of the pen. ``stop`` ends it; without a ``target`` it ends the continuous
feedback on every target. Neither has a reply, and the limit on how often
taps are played does not apply to them.

Continuous feedback must not outlive the program that asked for it, so a
terminal stops it by itself:

* when the window loses focus,
* when one second passes without another ``start`` for that target, so a
  program that wants it to go on repeats its ``start`` at least twice a
  second; a repeat with the same values is not felt,
* when the terminal is reset.

A relay or a multiplexer forwards these requests for the pane that has the
focus and does not repeat ``start`` on a program's behalf.

Equivalents
--------------

The patterns are those the systems with such hardware already offer, under
the nearest name each has. The first column of systems is the only one kitty
plays; the others are for terminals on those systems.

================ ============================ ============================================ =====================================
Pattern          macOS trackpad,              Windows pen or dial,                         iPadOS Apple Pencil Pro,
                 ``NSHapticFeedbackManager``  ``KnownSimpleHapticsControllerWaveforms``    ``UICanvasFeedbackGenerator``
================ ============================ ============================================ =====================================
``generic``      ``generic``                  ``Click``
``alignment``    ``alignment``                ``Align``                                    ``alignmentOccurred(at:)``
``level``        ``levelChange``              ``Step``
``click``        ``generic``                  ``Click``
``complete``     ``generic``                  ``Success``                                  ``pathCompleted(at:)``
``ink``                                       ``InkContinuous``
``pencil``                                    ``PencilContinuous``
``marker``                                    ``MarkerContinuous``
``brush``                                     ``BrushContinuous``
``eraser``                                    ``EraserContinuous``
================ ============================ ============================================ =====================================

Where a cell is empty the system has nothing close, and the terminal drops
the request.

In kitty
-----------

kitty plays the taps on the trackpad on macOS, with the generic tap standing
in for ``click`` and ``complete``, and the user turns them off with
:opt:`haptic_feedback`. It has no way to drive a pen or a dial on any system
it runs on, so ``caps`` is ``1`` on macOS and ``0`` elsewhere, and requests
for the other targets, ``start`` and ``stop`` are accepted and do nothing.
