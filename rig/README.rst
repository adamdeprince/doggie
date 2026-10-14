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

Nothing is written outside that directory: the terminal runs with no
configuration file and keeps its caches there.

Only one run goes at a time, since the reports are timed and two runs would
share the machine. The lock is the directory ``/tmp/silkie-rig.lock``: a run
waits up to half an hour for it and removes it when it ends, however it ends.
If a run is killed with ``SIGKILL`` the lock stays, remove it with ``rmdir``.

It needs sway (it was written against 1.11), Python 3.12, libxkbcommon, and
the protocol XML files of ``wayland-protocols`` (1.42 or later for dials) and
``libwayland-dev``, all of which a machine that builds kitty for Wayland has.
kitty draws with Mesa's software renderer, so no GPU is used.

To check the rig itself, without a terminal::

    rig/selftest.sh run-name

builds ``tabletdump.c``, a small client that prints every ``tablet-v2`` event
it is sent, connects it through the proxy, plays a pen, the puck and the pads
to it and compares what it printed with ``selftest.expected``. Run it after
changing ``wlproxy.py`` or the devices.

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
``pair``         A pen and the puck on the tablet at the same time, each with a
                 stroke of its own
``outside``      A stroke dragged out of the window on three sides and ended there
``touch``        A touchscreen: one finger draws; three fingers land, move and lift
                 together, one of them with a contact shape; two fingers are taken
                 over by the compositor; a tap that begins and ends in one frame
``gestures``     A pinch that also rotates, a pinch the compositor takes over,
                 swipes in the four directions, a hold
``scroll``       Two fingers scroll on a touchpad and lift, then a wheel turns a
                 notch each way
``handover``     A pen leaves over the edge of the window, then the touchpad is
                 pinched and scrolled with the pointer resting in the middle, as
                 on a compositor where tablets have a cursor of their own
``pads``         The three pads are plugged in while the terminal runs, then every
                 key, the ring with a finger lift, a mode switch, keys held while the
                 pad leaves, the strip, the dial
``padgroups``    A pad of the second tablet with two groups of controls and a key in
                 neither: which tablet it belongs to, which group each control is in,
                 and its description again when the compositor takes a key out of a
                 group
================ ====================================================================

``pads`` is last because a tree that destroys pads as they are announced does
not survive it. What it expects is what the tablet pointer protocol says of
pads: a description of each pad when it comes to the window, the mode of its
group, which a compositor sends after every enter, and reports of ``kind=3``
with ``button`` and ``state``, ``ring`` and ``angle``, ``strip`` and ``pos``,
``dial`` and ``delta``, ``group`` and ``mode``, with the keys that are down
let go when the pad leaves. The labels a program gives the controls are not
played: ask for ``RIG_WAYLAND_DEBUG`` or read the ``request`` lines of
``proxy.log`` to see them reach the compositor as ``set_feedback``.

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

``RIG_NO_UDEV``
    Set it to play without the stand-in for libudev described below. The
    tablets then name device nodes that do not exist, and a terminal must say
    nothing of their size or of whether they are displays.

The size of a tablet
-----------------------

``tablet-v2`` has neither the size of a tablet nor whether it is a display,
but it names the device node of the tablet, and a terminal can ask libudev
what the kernel and udev say of that node. The tablets here have no node, so
``run.sh`` builds ``fakeudev.c`` as a ``libudev.so.1`` in the directory of the
run and puts that directory into ``LD_LIBRARY_PATH`` for the terminal alone.
It answers for two character devices that every machine has, ``/dev/null``
for the Intuos5 and ``/dev/zero`` for the Cintiq, as udev and the kernel
would for the real tablets: 224 by 140 millimeters and not a display, 345 by
194 and a display. The tablets name those nodes, and ``play.py`` expects
``w``, ``h`` and ``direct`` in the description of every tool. It needs a C
compiler; without one the run goes as with ``RIG_NO_UDEV``.

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

The X11 half
---------------

::

    rig/xrun.sh /path/to/built/tree run-name [sequence ...]

does the same for the X11 backend, with the same client, checker, lock and
run directory. Here nothing has to be invented: the X server has a test
driver, ``inputtest``, whose devices take their events from a socket.
``xrun.sh`` starts an X server of its own with the dummy video driver, no
devices from the kernel and one ``inputtest`` device per kind of hardware,
and ``x11.py`` plays to them. The server runs as the user, on a free display
from ``:70`` up, without a window manager.

It needs ``Xorg`` 21.1 with its ``dummy`` video driver and ``inputtest`` input
driver (``xserver-xorg-core`` and ``xserver-xorg-video-dummy`` on Debian and
Ubuntu).

================ ====================================================================
``stylus``,      A pen, or its eraser, hovers, draws a diagonal with rising pressure
``eraser``       and lifts. The driver's tablet device has pressure and no tilt, and
                 kitty takes the tool from the device's name. Each report says
                 where on the tablet the pen is
``mapped``       The tablet is mapped to the middle half of the screen with
                 ``xinput`` while the terminal runs: the pointer goes where the
                 server puts it and the place on the tablet is still the tablet's
``buttons``      The side buttons of a pen and the back and forward buttons
``touch``        A touchscreen through XInput 2.2: one finger, then two
``gestures``     The gestures of XInput 2.4: pinches and a swipe
``scroll``       The scroll axis: a notch each way, then a notch in ten steps
``mouse``        A mouse moves in eight steps and stops. Nothing is checked: run the
                 client with ``--mouse`` and read the ``csi`` lines of its log
================ ====================================================================

``RIG_XINPUT_TEST=1`` also records what ``xinput test-xi2 --root`` sees in
``xi2.log``. With a window over the root that is only the raw events; to see
the events a window gets, with the positions the X server puts in them, run
``xinput test-xi2`` on the server without a terminal.

The X server stamps an event that comes from a device attached to the core
pointer with the pointer position from before that event, and only the copy
of the event that comes from the core pointer itself has the new position.
The expected reports have the position that was played, so a terminal that
takes positions from the device's own events is one event late throughout.

Limits
---------

* The events are those a compositor that follows the protocol sends, in the
  order wlroots sends them. They do not come from libinput, so what a real
  tablet makes libinput and a compositor do is assumed, not tested. Doing
  that needs devices made with uinput, which every session on the seat they
  belong to sees.
* The terminal has to be the only client of the proxy, and sway must have no
  input devices of its own.
* On X11 a tool has a position, a pressure and buttons, nothing else, and
  there is no pad: that is all the test driver of the X server has.
