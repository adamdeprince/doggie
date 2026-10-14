Show pointer
==================================================

.. only:: man

    Overview
    --------------

    *Show what the terminal reports for pens, tablets, touch, gestures and scrolling*

.. highlight:: sh

The ``show-pointer`` kitten shows what a terminal reports to programs for the
input devices that are more than a mouse: the pens and pads of graphics
tablets, touchscreens, touchpads, the gestures made on them and scrolling. It
speaks the tablet pointer, gesture and scroll protocols, which are open
terminal extensions framed as ``OSC 777``. Run it in the terminal you want to
know about::

    kitten show-pointer

It first asks the terminal which of the protocols it speaks and what it can
report with each, and says so in words. Then it turns on every kind of report
the terminal offers and prints one line for each report it receives, until you
press :kbd:`Ctrl+C`, :kbd:`Ctrl+D` or :kbd:`q`::

    tablet tool down device=3 contact=0 tool=pen x=100.00px y=200.00px cell=8,8 buttons=tip mods=none valid=pressure+tilt pressure=0.488 tilt=-12.00°,6.00° t=408211ms
    tablet tool move device=3 contact=0 tool=pen x=101.00px y=200.00px cell=8,8 buttons=tip mods=none valid=pressure+tilt pressure=0.502 tilt=-12.00°,6.00° t=408215ms dt=4ms
    gesture pinch update x=100.00px y=200.00px cell=8,8 mods=none scale=+12.0% total=x1.340
    scroll precise moving dx=+0.00px dy=+2.50px x=33px y=12px cell=2,0 mods=shift

Values are converted to the units a person reads: positions in pixels and as
the zero based column and row of the cell they fall in, pressure as a fraction
of the full range, angles in degrees. ``dt`` is the time since the previous
report of the same contact, which is how to see the rate a device reports at.
A field or a kind of report the kitten has no name for is printed as the
terminal sent it, never dropped, so a terminal that implements a later version
of a protocol can still be examined.

While the kitten runs, a pen or a finger over its window is reported to it
instead of acting as a mouse, and with scroll reports on the terminal does not
scroll its scrollback. To watch only some of the sources, name them::

    kitten show-pointer --only tools,pads

A system that judges whether a contact is meant, as macOS does for a thumb
resting on the trackpad, has its judgement shown with each finger as
``meant`` or ``accidental``. A terminal keeps the accidental contacts from a
program that does not ask for them, and the kitten asks, so it shows them all.
Leave ``accidental`` out of :option:`--only <kitty +kitten show_pointer --only>`
to see what a program that does not ask is shown instead: a finger that comes
to rest is cancelled, and begins again when it moves off.

On exit, and while it is stopped with :kbd:`Ctrl+Z`, the kitten turns off
everything it turned on. In a terminal that speaks none of the protocols it
says so and exits with a non-zero status, which makes it usable as a test in a
script.


Reporting a problem
----------------------

To send someone what your terminal reports for your tablet, use
:option:`--raw <kitty +kitten show_pointer --raw>`, which prints the frames
exactly as the terminal sent them, and redirect the output to a file::

    kitten show-pointer --raw > report.txt

The terminal you run this in is still the one that is examined, only the
output goes to the file. Move the pen, press its buttons and the keys of the
tablet, then quit and attach the file. Lines starting with ``#`` are the
kitten's own description of the terminal.

The serial number of a pen identifies the pen and so its owner. Unless
:option:`--ids <kitty +kitten show_pointer --ids>` is given, the kitten does
not ask the terminal for hardware identifiers, and replaces a serial number
the terminal sends regardless with a counter, ``#1`` for the first pen seen,
``#2`` for the second, which is enough to tell two pens apart.


.. include:: ../generated/cli-kitten-show_pointer.rst
