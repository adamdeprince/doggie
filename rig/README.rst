An input rig without hardware
================================

This directory tests the input code of the Wayland backend against tablets,
pads, touchscreens and touchpads that do not exist. It needs no hardware and
no root, and it creates no device: nothing it does is visible to the kernel,
to libinput or to a desktop session someone is logged in to on the same
machine.

Running it
-------------

Build the tree to test, copy this directory to the machine if it is not there
(it does not have to be inside the tree), and run::

    rig/run.sh /path/to/built/tree run-name [sequence ...]

For a tree that is only on another machine::

    git archive input-rig rig | ssh naamah 'mkdir -p /tmp/my-rig && tar -x -C /tmp/my-rig'
    ssh naamah /tmp/my-rig/rig/run.sh /path/to/built/tree run-name

``run-name`` names the run: everything it writes is in
``/tmp/silkie-rig-<run-name>``, which is emptied first. Without sequences all
of them are played, in the order of the table below. The script prints how
what a program inside the terminal received differs from what it should have
received, and exits with zero when nothing differs.

Only one run goes at a time, since the reports are timed and two runs would
share the machine. The lock is the directory ``/tmp/silkie-rig.lock``: a run
waits up to half an hour for it and removes it when it ends, however it ends.
If a run is killed with ``SIGKILL`` the lock stays, remove it with ``rmdir``.

It needs sway (1.9 or later), Python 3.12, libxkbcommon, and the protocol XML
files of ``wayland-protocols`` (1.42 or later for dials) and ``libwayland-dev``,
all of which a machine that builds kitty for Wayland has. kitty draws with
Mesa's software renderer, so no GPU is used.

How it works
---------------

``run.sh`` starts a headless sway with no input devices, ``wlproxy.py``, and
the terminal, which connects to the proxy instead of to sway.

``wlproxy.py`` is a Wayland proxy. It forwards everything the terminal and
sway say to each other, and gives the terminal a keyboard, a pointer, a
touchscreen, pointer gestures, and a ``tablet-v2`` manager with tablets, tools
and pads. None of these exist as far as sway is concerned: the proxy answers
the terminal's requests to them itself and writes their events when told to
over its control socket. It reads the wire format from the protocol XML
files, so it follows the creation and destruction of every object.

``play.py`` holds the devices and the sequences. It tells the proxy to send
the events a compositor sends for a real device, in the same order and units,
and writes down the reports a program should get for them according to the
protocol documents. ``client.py`` is that program: it runs inside the
terminal, turns on the OSC 777 input extensions and logs every frame it is
sent. ``check.py`` lines the two up and prints the differences.

The devices are modelled on real ones. The names, USB ids, tool ids and
serial numbers are those of libinput's test devices
(``test/litest-device-*.c``) and of libwacom:

================ ====================================================================
``intuos5``      Wacom Intuos5 touch M: a tablet, with a pad of nine keys and a touch
                 ring with four modes
``pen``,         Its Grip Pen and the eraser at the other end: pressure, tilt and
``eraser``       distance. Both ends have the serial of the pen and their own tool id
``artpen``       A Wacom Art Pen, which also reports rotation around its barrel
``airbrush``     A Wacom Airbrush, with a finger wheel (the slider of ``tablet-v2``)
``lens``         A lens cursor: a puck with five buttons and a wheel, no tip
``cintiq``,      Wacom Cintiq Pro 16, a pen display, and its Pro Pen with three side
``propen``       buttons
``intuos3``      The pad of a Wacom Intuos3 4x6: four keys and a touch strip
``huion``        The pad of a Huion Q620M: a key and a dial
================ ====================================================================

Sequences
------------

================ ====================================================================
``pen``,         The tool comes into proximity, hovers closer, draws a diagonal of
``eraser``,      ten points with every axis it has changing, lifts and leaves
``artpen``,
``airbrush``
``buttons``      The three side buttons of the Pro Pen, while hovering and drawing
``puck``         The lens cursor: its left button draws, the wheel turns, the other
                 four buttons
``burst``        Ten samples that are 5 ms apart but all arrive at once, as after a
                 stall. The ``t`` of the reports must be 5 ms apart
``abort``        A pen flicked out of range, so that the tip coming up and the pen
                 leaving are in one frame, as wlroots sends them; and a tablet
                 unplugged in the middle of a stroke
``mods``         Keyboard modifiers held while a pen moves
``touch``        A touchscreen: one finger draws; three fingers land, move and lift
                 together, one of them with a contact shape; two fingers are taken
                 over by the compositor
``gestures``     A pinch that also rotates, a three finger swipe, a hold
``scroll``       Two fingers scroll on a touchpad and lift, then a wheel turns a
                 notch each way
``pads``         The three pads are plugged in while the terminal runs, then every
                 key, the ring with a finger lift, a mode switch, the strip, the dial
================ ====================================================================

``pads`` is last because a tree that does not handle pads may not survive it.
What it expects are the reports of the pad kind that is being added to the
tablet pointer protocol, ``kind=3`` with ``button`` and ``state``, ``ring``
and ``angle``, ``strip`` and ``pos``, ``dial`` and ``delta``, ``group`` and
``mode``. Change ``pads()`` in ``play.py`` when the protocol settles.

Settings
-----------

Environment variables for ``run.sh``:

``RIG_TABLET_VERSION``
    The version of ``tablet-v2`` the proxy offers. ``2``, the default, has
    dials and the bus type of a tablet. ``1`` is what sway 1.11 offers. ``0``
    offers no tablets at all, as a compositor without the protocol.

``RIG_CLIENT_ARGS``
    Arguments for ``client.py``, for example ``--tablet 0 --mouse`` to leave
    the tablet pointer mode off and log the mouse reports a pen makes instead.

``RIG_WAYLAND_DEBUG``
    Set it to have the terminal log the Wayland messages it sends and gets,
    as libwayland decodes them, in ``kitty.log``.

``RIG_SIZE``
    The size of the output and so of the window, ``1280x800`` by default.

The logs
-----------

``client.log``
    What the program in the terminal saw, one line per item: the time on
    ``CLOCK_MONOTONIC``, a kind and the text. ``osc777`` lines are frames,
    selector first; ``sent`` is what the client wrote; ``csi`` and ``text``
    are other input, such as mouse reports.

``proxy.log``
    ``event`` lines are what the proxy sent the terminal for the invented
    devices, ``request`` lines what the terminal asked of them (cursor
    shapes, pad feedback), and ``compositor`` lines what sway offered that
    the proxy replaced. Any ``error`` or ``warning`` line fails the run.

``expect.jsonl``
    The expected reports, with the time each was played.

``kitty.log``
    The output of the terminal, run with ``--debug-input``.

Playing something else
-------------------------

The control socket of the proxy takes one JSON object per line and answers
each with one, ``{"ok": true}`` or an error:

``{"op": "add", "device": "tablet:NAME", "name": ..., "vid": ..., "pid": ...}``
    Plugs in a tablet. A tool is ``"device": "tool:NAME"`` with ``type``,
    ``serial``, ``hwid`` and ``caps``; a pad is ``"device": "pad:NAME"`` with
    ``buttons`` and ``groups``, each group having ``buttons``, ``rings``,
    ``strips``, ``dials`` and ``modes``. See ``DEVICES`` in ``play.py``.

``{"op": "play", "to": "tool:pen", "events": [["motion", 10, 20], ["frame", "$time"]]}``
    Sends events to one object, in order. An event is its name in the
    protocol XML followed by its arguments. ``$serial`` is a fresh serial,
    ``$surface`` the window, ``$time`` the time in milliseconds and
    ``$time-20`` twenty milliseconds before it. An object argument is given
    by name. The objects are the devices, ``group:PAD:0``, ``ring:PAD:0:0``,
    ``strip:PAD:0:0``, ``dial:PAD:0:0``, and ``keyboard``, ``pointer``,
    ``touch``, ``swipe``, ``pinch`` and ``hold``.

``{"op": "info"}``
    Whether the terminal is connected, the size of its window, the objects
    that can be played to and the version of each interface it bound.

Limits
---------

* The events are those a compositor that follows the protocol sends, in the
  order wlroots sends them. They do not come from libinput, so what a real
  tablet makes libinput and a compositor do is assumed, not tested. Doing
  that needs devices made with uinput, which every session on the seat they
  belong to sees.
* The terminal has to be the only client of the proxy, and sway must have no
  input devices of its own.
* Only the Wayland backend is covered.
