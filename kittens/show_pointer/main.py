#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Adam DePrince


import sys

OPTIONS = r"""
--only
type=list
Restrict what is turned on to the named sources, a comma separated list that
can also be given by repeating this option. The sources are :code:`tools`,
:code:`fingers`, :code:`pads`, :code:`actions`, :code:`estimates` and
:code:`accidental` of the tablet pointer protocol, :code:`gestures` and
:code:`hold` of the gesture protocol and :code:`scroll`. :code:`accidental`
is the contacts the system takes for accidents, such as a palm or a thumb
resting on a touchpad, which a terminal otherwise keeps back. The names :code:`tablet-pointer` and
:code:`gesture` stand for every source of that protocol. By default
everything the terminal offers is turned on.


--ids
type=bool-set
Ask the terminal for hardware identifiers and show them. The serial number of
a pen identifies its owner, and the output of this kitten is meant to be
pasted into a bug report, so by default identifiers are not asked for and a
serial number the terminal sends anyway is replaced by a counter.


--raw
type=bool-set
Print the frames as the terminal sent them, one per line, instead of decoding
them. This is the output to attach to a bug report. Lines that are not frames
start with :code:`#`.


--timeout
type=float
default=2
How long to wait, in seconds, for the terminal to answer a round of queries
before going on without the answers.
""".format
help_text = '''\
Show what the terminal reports for pens, tablet pads, touchscreens, touchpads,
gestures and scrolling.

The kitten asks the terminal which of the tablet pointer, gesture and scroll
protocols it speaks, turns on every kind of report the terminal offers and
prints one line for each report it receives, until you press :kbd:`Ctrl+C`,
:kbd:`Ctrl+D` or :kbd:`q`. The reports are turned off again when it exits.

It exits with a non-zero status when the terminal speaks none of the
protocols. When STDOUT is not a terminal the output is written there, while
the terminal the kitten runs in is still the one that is queried.
'''
usage = ''
short_description = 'Show what the terminal reports for pens, tablets, touch, gestures and scrolling'


def main(args: list[str]) -> None:
    raise SystemExit('This should be run as kitten show-pointer')


if __name__ == '__main__':
    main(sys.argv)
elif __name__ == '__doc__':
    cd = sys.cli_docs  # type: ignore
    cd['usage'] = usage
    cd['options'] = OPTIONS
    cd['help_text'] = help_text
    cd['short_desc'] = short_description
