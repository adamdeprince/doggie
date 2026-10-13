An input rig without hardware
================================

This directory tests the input code of the Wayland backend against tablets,
pads, touchscreens and touchpads that do not exist. It needs no hardware, no
root, and creates no device that the kernel or anyone's desktop session can
see.

::

    rig/run.sh /path/to/built/tree [sequence ...]

runs a built tree inside a headless sway, plays the sequences (all of them by
default) and prints how what a program inside the terminal received differs
from what it should have received. It exits with zero when nothing differs.
The logs stay in the ``/tmp/silkie-rig-run.*`` directory it names.

It needs sway, Python 3.12, libxkbcommon and the protocol XML files of
``wayland-protocols`` and ``libwayland-dev``, all of which a machine that
builds kitty for Wayland has.

How it works
---------------

``wlproxy.py`` is a Wayland proxy. The terminal connects to it instead of to
the compositor, and it forwards everything the two say to each other. On top
of that it gives the terminal a keyboard, a pointer, a touchscreen, pointer
gestures and a ``tablet-v2`` manager with tablets, tools and pads. None of
these exist as far as the compositor is concerned: the proxy answers the
terminal's requests to them itself and writes their events on request.

``play.py`` holds the devices and the sequences. It sends the proxy the events
a compositor would send for a real device and writes down the reports a
program should get for them. ``client.py`` is that program: it runs inside the
terminal, turns on the OSC 777 input extensions and logs every frame it is
sent. ``check.py`` compares the two.
